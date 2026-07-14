#!/usr/bin/env python3
"""
Dynast-Z Trade Calculator - Local server that proxies API requests
to avoid CORS issues and serves the frontend.

Usage: python3 server.py
Then open http://localhost:8000
"""

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import http.server
import json
import math
import os
import re
import hashlib
import hmac
import secrets
import subprocess
import time
import urllib.request
from datetime import datetime
from urllib.parse import urlparse, parse_qs

PORT = 8000
IS_VERCEL = os.environ.get("VERCEL") == "1"
CACHE_DIR = "/tmp/dynast-z-cache" if IS_VERCEL else os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
CACHE_TTL = 129600  # 36 hours in seconds

# Player-value curve. Each source's players are ranked by value and turned into
# a percentile position p in [0, 1] (0 = best, 1 = worst); the percentiles a
# player appears in are averaged, and the blended p is mapped onto a 0-VALUE_SCALE
# grade via  value = SCALE * exp(-(TOP_DECAY * p + TAIL_DECAY * p**4)).
#   - TOP_DECAY is a gentle, whole-field slope that sets how separated the top is.
#   - TAIL_DECAY is a quartic term: negligible near the top, but it accelerates
#     hard over the bottom third so those players collapse toward zero.
# Together they keep elite players ahead while thoroughly de-emphasizing the tail.
VALUE_SCALE = 100
VALUE_TOP_DECAY = 5.5
VALUE_TAIL_DECAY = 6.0

KTC_URL = "https://keeptradecut.com/dynasty-rankings"
FANTASYCALC_URL = "https://api.fantasycalc.com/values/current?isDynasty=true&numQbs=2&numTeams=12&ppr=1"
SLEEPER_API = "https://api.sleeper.app/v1"
SLEEPER_PLAYERS_TTL = 86400  # 24 hours for the big players file
LEAGUE_DATA_TTL = 3600  # 1 hour for league rosters/users
FP_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "fp.json")
POWER_RANKINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "power_rankings.json")
REGULAR_SEASON_WEEKS = 14
MASTERS_SCORES_TTL = 300  # 5 minutes

# Tournament configuration: (tournament, year) -> mode + source
GOLF_TOURNAMENTS = {
    ("masters", "2026"): {"mode": "archive", "path": "data/masters/2026.json"},
    ("masters", "2027"): {"mode": "live", "url": "https://www.masters.com/en_US/scores/feeds/2027/scores.json"},
    ("pga-championship", "2026"): {"mode": "upcoming"},
    ("us-open", "2026"): {"mode": "upcoming"},
    ("british-open", "2026"): {"mode": "upcoming"},
}
DATA_DIR = os.path.dirname(os.path.abspath(__file__))

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
PBKDF2_ITERATIONS = 200_000
MIN_PASSWORD_LEN = 8


def supabase_request(path, method="GET", body=None, extra_headers=None):
    if not SUPABASE_URL:
        raise Exception("SUPABASE_URL not set — set env vars for account sync")
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("apikey", SUPABASE_KEY)
    req.add_header("Authorization", f"Bearer {SUPABASE_KEY}")
    req.add_header("Content-Type", "application/json")
    if extra_headers:
        for k, v in extra_headers.items():
            req.add_header(k, v)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password, stored):
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iters)
        )
        return hmac.compare_digest(digest.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


def fetch_user(user_id):
    rows = supabase_request(
        f"users?id=eq.{urllib.request.quote(user_id)}&select=role,status"
    )
    return rows[0] if rows else None


def resolve_bets_user(headers, require_active):
    """Resolve the user_id a /api/bets operation acts on. Normally the X-User-Id
    requester; when X-Audit-User-Id is present (an admin managing another user),
    verify the requester is an active admin and act on the target's rows. For
    normal writes, require_active gates the requester's own status. Returns
    (effective_user_id, error) where error is None or a (status, body) tuple."""
    user_id = headers.get("X-User-Id")
    if not user_id:
        return None, (401, {"error": "Not authenticated"})
    audit_id = headers.get("X-Audit-User-Id")
    if audit_id and audit_id != user_id:
        actor = fetch_user(user_id)
        if (not actor or actor.get("status") is not True
                or actor.get("role") != "admin"):
            return None, (403, {"error": "Admin access required"})
        return audit_id, None
    if require_active:
        user = fetch_user(user_id)
        if not user or user.get("status") is not True:
            return None, (403, {"error": "Account is inactive"})
    return user_id, None


def read_cache(name, ttl=None):
    path = os.path.join(CACHE_DIR, name)
    if not os.path.exists(path):
        return None
    age = time.time() - os.path.getmtime(path)
    if age > (ttl if ttl is not None else CACHE_TTL):
        return None
    with open(path, "r") as f:
        return json.load(f)


def write_cache(name, data):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, name)
    with open(path, "w") as f:
        json.dump(data, f)


UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def http_fetch(url):
    result = subprocess.run(
        ["curl", "-s", "-A", UA, "--max-time", "15", url],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"curl failed ({result.returncode}): {result.stderr.strip()}")
    return result.stdout


def fetch_ktc():
    cached = read_cache("ktc.json")
    if cached is not None:
        print("Using cached KTC data")
        return cached
    print("Fetching fresh KTC data...")
    html = http_fetch(KTC_URL)
    match = re.search(r"var\s+playersArray\s*=\s*(\[.*?\]);\s*\n", html, re.DOTALL)
    if not match:
        raise RuntimeError("Could not find playersArray in KTC page")
    data = json.loads(match.group(1))
    write_cache("ktc.json", data)
    print("KTC data complete.")
    return data


def fetch_golf_scores(tournament, year):
    key = (tournament, year)
    config = GOLF_TOURNAMENTS.get(key)
    if not config:
        raise ValueError(f"Unknown tournament: {tournament} {year}")

    mode = config["mode"]

    if mode == "upcoming":
        return {"status": "upcoming", "tournament": tournament, "year": int(year)}

    if mode == "archive":
        data_path = os.path.join(DATA_DIR, config["path"])
        with open(data_path, "r") as f:
            return json.load(f)

    if mode == "live":
        cache_name = f"golf_{tournament}_{year}.json"
        cached = read_cache(cache_name, ttl=MASTERS_SCORES_TTL)
        if cached is not None:
            print(f"Using cached {tournament} {year} scores")
            return cached
        print(f"Fetching fresh {tournament} {year} scores...")
        data = json.loads(http_fetch(config["url"]))
        write_cache(cache_name, data)
        return data

    raise ValueError(f"Unknown mode: {mode}")


def fetch_masters_scores():
    return fetch_golf_scores("masters", "2026")


def fetch_fc():
    cached = read_cache("fc.json")
    if cached is not None:
        print("Using cached FantasyCalc data")
        return cached
    print("Fetching fresh FantasyCalc data...")
    data = json.loads(http_fetch(FANTASYCALC_URL))
    write_cache("fc.json", data)
    print("FantasyCalc data complete.")
    return data


def norm_pos(pos):
    return "PICK" if pos == "RDP" else pos


_SUFFIXES = re.compile(r"\s+(Jr\.?|Sr\.?|III|II|IV|V)$", re.IGNORECASE)
_DOTTED_INITIALS = re.compile(r"\b([A-Z])\.")


def norm_name(name):
    """Normalize a player name for merging: strip suffixes, then dots from initials."""
    name = _DOTTED_INITIALS.sub(r"\1", name)
    name = _SUFFIXES.sub("", name)
    return name.strip()


def normalize_ktc(raw):
    players = {}
    for p in raw:
        name = p.get("playerName", "")
        sf = p.get("superflexValues", {})
        value = sf.get("value", 0)
        if name and value:
            key = norm_name(name)
            players[key] = {
                "name": key,
                "position": norm_pos(p.get("position", "")),
                "team": p.get("team", ""),
                "value": value,
            }
    return players


def normalize_fc(raw):
    players = {}
    for entry in raw:
        p = entry.get("player", {})
        name = p.get("name", "")
        value = entry.get("value", 0)
        if name and value:
            key = norm_name(name)
            players[key] = {
                "name": key,
                "position": norm_pos(p.get("position", "")),
                "team": p.get("maybeTeam", ""),
                "value": value,
            }
    return players


def load_fp():
    """Load FantasyPros data from static JSON file (data/fp.json)."""
    if not os.path.exists(FP_DATA_PATH):
        print("No FP data file found at", FP_DATA_PATH)
        return []
    with open(FP_DATA_PATH, "r") as f:
        return json.load(f)


_PICK_TIER_RE = re.compile(r"^(\d{4})\s+(Early|Mid|Late)\s+(\d+(?:st|nd|rd|th))$")


def _fill_missing_mid_picks(players):
    """FantasyPros publishes 2nd/3rd-round picks in only two tiers (Early/Late),
    while KTC and our internal model use three (Early/Mid/Late). Left alone, an
    Early pick present in FP is blended across a different set of sources than the
    Mid pick FP omits, which can invert their ranking (e.g. Mid 2nd scoring above
    Early 2nd). Synthesize the missing Mid tier by interpolating between Early and
    Late so every tier is covered by every source and the merge stays monotonic."""
    grouped = {}  # (year, ordinal) -> {tier: key}
    for key, p in players.items():
        m = _PICK_TIER_RE.match(key)
        if m:
            year, tier, ordinal = m.groups()
            grouped.setdefault((year, ordinal), {})[tier] = key
    for (year, ordinal), tiers in grouped.items():
        if "Mid" in tiers or "Early" not in tiers or "Late" not in tiers:
            continue
        early = players[tiers["Early"]]
        late = players[tiers["Late"]]
        key = f"{year} Mid {ordinal}"
        players[key] = {
            "name": key,
            "position": early["position"],
            "team": early["team"],
            "value": (early["value"] + late["value"]) / 2,
        }
    return players


def normalize_fp(raw):
    """Normalize FantasyPros data into {name: {name, position, team, value}} dict."""
    players = {}
    for p in raw:
        name = p.get("name", "")
        value = p.get("value", 0)
        if name and value:
            key = norm_name(name)
            players[key] = {
                "name": key,
                "position": p.get("position", ""),
                "team": p.get("team", ""),
                "value": value,
            }
    return _fill_missing_mid_picks(players)


def compute_percentiles(players_dict):
    """Rank a single source's players by value and return each player's
    percentile position in [0, 1] (0 = best, 1 = worst)."""
    order = sorted(players_dict.items(), key=lambda kv: -kv[1]["value"])
    n = len(order)
    if n == 1:
        return {order[0][0]: 0.0}
    return {name: i / (n - 1) for i, (name, _) in enumerate(order)}


def fetch_sleeper_players():
    """Fetch the full Sleeper player database (~5MB). Cached for 24 hours."""
    cached = read_cache("sleeper_players.json", ttl=SLEEPER_PLAYERS_TTL)
    if cached is not None:
        print("Using cached Sleeper players data")
        return cached
    print("Fetching fresh Sleeper players data...")
    data = json.loads(http_fetch(f"{SLEEPER_API}/players/nfl"))
    write_cache("sleeper_players.json", data)
    return data


def fetch_league_data(league_id):
    """Fetch rosters and users for a Sleeper league. Cached for 1 hour."""
    cache_name = f"league_{league_id}.json"
    cached = read_cache(cache_name, ttl=LEAGUE_DATA_TTL)
    if cached is not None:
        print(f"Using cached league data for {league_id}")
        return cached["rosters"], cached["users"], cached["league"]
    print(f"Fetching fresh league data for {league_id}...")
    rosters = json.loads(http_fetch(f"{SLEEPER_API}/league/{league_id}/rosters"))
    users = json.loads(http_fetch(f"{SLEEPER_API}/league/{league_id}/users"))
    league = json.loads(http_fetch(f"{SLEEPER_API}/league/{league_id}"))
    write_cache(cache_name, {"rosters": rosters, "users": users, "league": league})
    return rosters, users, league


def fetch_league_picks(league_id):
    """Fetch traded picks, draft order, and completed-draft seasons for a league.

    completed_seasons are the seasons whose rookie draft has already happened —
    those picks have turned into rostered players and must not be synthesized.
    Cached with league data.
    """
    cache_name = f"picks_{league_id}.json"
    cached = read_cache(cache_name, ttl=LEAGUE_DATA_TTL)
    if cached is not None:
        return (cached["traded_picks"], cached.get("draft_order"),
                set(cached.get("completed_seasons") or []))
    traded_picks = json.loads(http_fetch(f"{SLEEPER_API}/league/{league_id}/traded_picks"))
    drafts = json.loads(http_fetch(f"{SLEEPER_API}/league/{league_id}/drafts"))
    draft_order = drafts[0].get("draft_order") if drafts else None
    completed_seasons = sorted({
        int(d["season"]) for d in drafts
        if d.get("status") == "complete" and d.get("season")
    })
    write_cache(cache_name, {
        "traded_picks": traded_picks, "draft_order": draft_order,
        "completed_seasons": completed_seasons,
    })
    return traded_picks, draft_order, set(completed_seasons)


_ORDINALS = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th", 6: "6th", 7: "7th"}


def _pick_name_variants(season, rd, slot, total_rosters):
    """Return a list of name variants to try matching against z_lookup, best first."""
    ordinal = _ORDINALS.get(rd, f"{rd}th")
    names = []
    if slot:
        names.append(f"{season} Pick {rd}.{slot:02d}")
    third = max(total_rosters // 3, 1)
    if slot:
        if slot <= third:
            tier = "Early"
        elif slot <= third * 2:
            tier = "Mid"
        else:
            tier = "Late"
        names.append(f"{season} {tier} {ordinal}")
    else:
        names.append(f"{season} Mid {ordinal}")
    names.append(f"{season} {ordinal}")
    return names


def build_picks_for_roster(roster_id, rosters, users, league, traded_picks, draft_order, z_lookup,
                           completed_seasons=()):
    """Compute all draft picks owned by a roster and return as player-like dicts.

    Seasons whose draft is already complete are skipped — those picks have become
    rostered players, so synthesizing them would double-count.
    """
    total_rosters = league.get("total_rosters", 12)
    draft_rounds = min(league.get("settings", {}).get("draft_rounds", 4), 4)
    current_season = int(league.get("season", "2026"))
    seasons = sorted(({current_season, current_season + 1, current_season + 2}
                      | {int(tp["season"]) for tp in traded_picks})
                     - set(completed_seasons))

    # Map roster_id -> owner_id (user_id) and short team name
    roster_owner = {r["roster_id"]: r.get("owner_id") for r in rosters}
    user_map = {u["user_id"]: u for u in users}
    def roster_label(rid):
        uid = roster_owner.get(rid)
        u = user_map.get(uid, {})
        return u.get("display_name", f"T{rid}")

    # Map user_id -> draft slot (1-based) from draft_order
    user_slot = {}
    if draft_order:
        for uid, slot in draft_order.items():
            user_slot[uid] = slot

    # traded_picks tells us current ownership overrides
    ownership = {}  # (season, round, original_roster_id) -> current_owner_roster_id
    for tp in traded_picks:
        key = (tp["season"], tp["round"], tp["roster_id"])
        ownership[key] = tp["owner_id"]

    picks = []
    for season in seasons:
        for rd in range(1, draft_rounds + 1):
            for orig_rid in range(1, total_rosters + 1):
                key = (str(season), rd, orig_rid)
                current_owner = ownership.get(key, orig_rid)
                if current_owner != roster_id:
                    continue
                # This roster owns this pick
                owner_uid = roster_owner.get(orig_rid)
                slot = user_slot.get(owner_uid) if owner_uid else None
                pick_slot = slot if season == current_season else None
                variants = _pick_name_variants(str(season), rd, pick_slot, total_rosters)
                # Display name: include original team label if traded
                ordinal = _ORDINALS.get(rd, f"{rd}th")
                if orig_rid != roster_id:
                    display = f"{season} {ordinal} ({roster_label(orig_rid)})"
                else:
                    display = f"{season} {ordinal}"
                # Try to match z_lookup
                z = None
                for v in variants:
                    z = z_lookup.get(norm_name(v))
                    if z:
                        break
                pick_data = {
                    "name": display,
                    "position": "PICK",
                    "team": "",
                    "starter": False,
                }
                if z:
                    pick_data["aggregate"] = z["aggregate"]
                    pick_data["sources"] = z["sources"]
                picks.append(pick_data)

    picks.sort(key=lambda p: -(p.get("aggregate") or -999))
    return picks


def build_teams_list(league_id):
    """Return all teams in a league."""
    rosters, users, league = fetch_league_data(league_id)
    user_map = {u["user_id"]: u for u in users}
    teams = []
    for roster in rosters:
        owner_id = roster.get("owner_id")
        user = user_map.get(owner_id, {})
        avatar_url = user.get("metadata", {}).get("avatar") or (
            f"https://sleepercdn.com/avatars/thumbs/{user['avatar']}" if user.get("avatar") else None
        )
        teams.append({
            "roster_id": roster["roster_id"],
            "team_name": user.get("metadata", {}).get("team_name") or user.get("display_name", "Unknown"),
            "display_name": user.get("display_name", "Unknown"),
            "avatar": avatar_url,
        })
    teams.sort(key=lambda t: t["team_name"].lower())
    return {
        "league_name": league.get("name", "League"),
        "league_id": league_id,
        "teams": teams,
    }


def load_power_rankings(league_id):
    """Load static power rankings for a league. Returns {team_name: pr} or {}."""
    if not os.path.exists(POWER_RANKINGS_PATH):
        return {}
    with open(POWER_RANKINGS_PATH, "r") as f:
        return json.load(f).get(str(league_id), {})


def fetch_league_schedule(league_id):
    """Build the regular-season (weeks 1-14) schedule grid for a league."""
    rosters, users, league = fetch_league_data(league_id)
    user_map = {u["user_id"]: u for u in users}

    pr_map = load_power_rankings(league_id)

    teams = []
    for roster in rosters:
        owner_id = roster.get("owner_id")
        user = user_map.get(owner_id, {})
        team_name = user.get("metadata", {}).get("team_name") or user.get("display_name", "Unknown")
        display_name = user.get("display_name", "Unknown")
        avatar_url = user.get("metadata", {}).get("avatar") or (
            f"https://sleepercdn.com/avatars/thumbs/{user['avatar']}" if user.get("avatar") else None
        )
        pr = pr_map.get(team_name)
        if pr is None:
            pr = pr_map.get(display_name)
        teams.append({
            "roster_id": roster["roster_id"],
            "team_name": team_name,
            "display_name": display_name,
            "avatar": avatar_url,
            "pr": pr,
        })
    teams.sort(key=lambda t: t["team_name"].lower())

    # The Sleeper schedule is fixed for the season; cache until year rollover.
    cache_name = f"schedule_{league_id}.json"
    now = datetime.now()
    year_end_ttl = int((datetime(now.year + 1, 1, 1) - now).total_seconds())
    cached = read_cache(cache_name, ttl=year_end_ttl)
    if cached is not None:
        print(f"Using cached schedule for {league_id}")
        weeks = cached
    else:
        print(f"Fetching fresh schedule for {league_id}...")
        weeks = {}
        for week in range(1, REGULAR_SEASON_WEEKS + 1):
            try:
                raw = json.loads(http_fetch(f"{SLEEPER_API}/league/{league_id}/matchups/{week}"))
            except Exception:
                continue
            by_matchup = {}
            for row in raw:
                mid = row.get("matchup_id")
                if mid is None:
                    continue
                by_matchup.setdefault(mid, []).append(row.get("roster_id"))
            pairs = {}
            for ids in by_matchup.values():
                if len(ids) == 2:
                    a, b = ids
                    pairs[a] = b
                    pairs[b] = a
            weeks[str(week)] = {str(rid): opp for rid, opp in pairs.items()}
        write_cache(cache_name, weeks)

    schedule = {str(t["roster_id"]): {} for t in teams}
    for week_str, pairs in weeks.items():
        for rid_str, opp_rid in pairs.items():
            if rid_str in schedule:
                schedule[rid_str][week_str] = opp_rid

    return {
        "league_name": league.get("name", "League"),
        "league_id": league_id,
        "teams": teams,
        "schedule": schedule,
    }


TRANSACTIONS_CACHE_TTL = 600  # 10 minutes
STORE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
# Vercel's /var/task is read-only; writes must go to /tmp
STORE_WRITE_DIR = "/tmp/dynast-z-store" if IS_VERCEL else STORE_DIR


def read_transaction_store(league_id):
    """Read the persistent transaction store (keyed by transaction_id).

    On Vercel, prefer the writable /tmp copy if present, falling back to the
    repo-bundled seed file.
    """
    filename = f"transactions_{league_id}.json"
    for d in (STORE_WRITE_DIR, STORE_DIR):
        path = os.path.join(d, filename)
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
    return {}


def write_transaction_store(league_id, store):
    """Write the persistent transaction store."""
    os.makedirs(STORE_WRITE_DIR, exist_ok=True)
    path = os.path.join(STORE_WRITE_DIR, f"transactions_{league_id}.json")
    with open(path, "w") as f:
        json.dump(store, f, indent=2)


def transform_transaction(tx, roster_team_map, sleeper_players):
    """Transform a single Sleeper transaction into normalized trade data."""
    roster_ids = tx.get("roster_ids", [])
    if len(roster_ids) < 2:
        return None

    a_id, b_id = roster_ids[0], roster_ids[1]
    default_team = lambda rid: {"team_name": f"Team {rid}", "display_name": f"Team {rid}"}
    a_info = roster_team_map.get(a_id, default_team(a_id))
    b_info = roster_team_map.get(b_id, default_team(b_id))

    adds = tx.get("adds") or {}
    draft_picks = tx.get("draft_picks") or []
    waiver_budget = tx.get("waiver_budget") or []

    a_receives = []
    b_receives = []

    # Players
    for player_id, receiving_roster in adds.items():
        sp = sleeper_players.get(player_id, {})
        name = f"{sp.get('first_name', '')} {sp.get('last_name', '')}".strip() or player_id
        pos = sp.get("position", "OTHER")
        label = f"{pos} {name}"
        if receiving_roster == a_id:
            a_receives.append(label)
        elif receiving_roster == b_id:
            b_receives.append(label)

    # Draft picks
    for pick in draft_picks:
        season = pick.get("season", "")
        rd = pick.get("round", "")
        new_owner = pick.get("owner_id")
        original_roster = pick.get("roster_id")
        original_info = roster_team_map.get(original_roster, {})
        original_team = original_info.get("team_name", "") if isinstance(original_info, dict) else original_info
        pick_label = f"{season} Round {rd}"
        if original_team:
            pick_label += f" ({original_team})"
        if new_owner == a_id:
            a_receives.append(pick_label)
        elif new_owner == b_id:
            b_receives.append(pick_label)

    # FAAB budget
    for wb in waiver_budget:
        sender = wb.get("sender")
        receiver = wb.get("receiver")
        amount = wb.get("amount", 0)
        if amount > 0:
            label = f"${amount} FAAB"
            if receiver == a_id:
                a_receives.append(label)
            elif receiver == b_id:
                b_receives.append(label)

    # Date from millisecond timestamp
    created_ms = tx.get("created", 0)
    dt = datetime.fromtimestamp(created_ms / 1000)
    date_str = dt.strftime("%Y-%m-%d")
    year = dt.year

    return {
        "transaction_id": tx.get("transaction_id"),
        "team_a": a_info["team_name"],
        "team_a_display": a_info["display_name"],
        "team_b": b_info["team_name"],
        "team_b_display": b_info["display_name"],
        "team_a_receives": a_receives,
        "team_b_receives": b_receives,
        "date": date_str,
        "year": year,
    }


def fetch_league_transactions(league_id):
    """Fetch all trades from Sleeper transactions API, transform for display."""
    cache_name = f"transactions_{league_id}.json"
    cached = read_cache(cache_name, ttl=TRANSACTIONS_CACHE_TTL)
    if cached is not None:
        print(f"Using cached transactions for league {league_id}")
        return cached

    print(f"Fetching fresh transactions for league {league_id}...")

    rosters, users, league = fetch_league_data(league_id)
    sleeper_players = fetch_sleeper_players()

    # Build roster_id -> team info map
    user_map = {u["user_id"]: u for u in users}
    roster_team_map = {}
    for roster in rosters:
        owner_id = roster.get("owner_id")
        user = user_map.get(owner_id, {})
        roster_team_map[roster["roster_id"]] = {
            "team_name": user.get("metadata", {}).get("team_name") or user.get("display_name", "Unknown"),
            "display_name": user.get("display_name", "Unknown"),
        }

    # Fetch all weeks from API
    api_trades = []
    for week in range(1, 19):
        try:
            raw = json.loads(http_fetch(f"{SLEEPER_API}/league/{league_id}/transactions/{week}"))
            for tx in raw:
                if tx.get("type") == "trade" and tx.get("status") == "complete":
                    api_trades.append(tx)
        except Exception:
            continue

    # Load persistent store and merge new transactions
    store = read_transaction_store(league_id)
    new_count = 0
    for tx in api_trades:
        tid = tx.get("transaction_id")
        if tid and tid not in store:
            transformed = transform_transaction(tx, roster_team_map, sleeper_players)
            if transformed:
                store[tid] = transformed
                new_count += 1

    if new_count > 0:
        print(f"Stored {new_count} new transaction(s) for league {league_id}")
        write_transaction_store(league_id, store)

    # Return all stored transactions sorted by date descending
    result = list(store.values())
    result.sort(key=lambda t: t["date"], reverse=True)
    write_cache(cache_name, result)
    return result


def build_team_roster(league_id, roster_id):
    """Build roster for a specific team by roster_id."""
    rosters, users, league = fetch_league_data(league_id)
    sleeper_players = fetch_sleeper_players()

    # Build value lookup from trade calculator data
    z_lookup = {}
    try:
        ktc_raw = fetch_ktc()
        fc_raw = fetch_fc()
        fp_raw = load_fp()
        ktc = normalize_ktc(ktc_raw)
        fc = normalize_fc(fc_raw)
        fp = normalize_fp(fp_raw)
        for p in merge_players(
            ("keeptradecut.com", ktc),
            ("fantasycalc.com", fc),
            ("fantasypros.com", fp),
        ):
            z_lookup[p["name"]] = p
    except Exception:
        pass  # values are a bonus, not required

    # Find the roster by roster_id
    target_roster = None
    for roster in rosters:
        if roster.get("roster_id") == int(roster_id):
            target_roster = roster
            break
    if not target_roster:
        raise RuntimeError(f"No roster found with roster_id {roster_id}")

    # Find owner info
    owner_id = target_roster.get("owner_id")
    team_name = None
    for u in users:
        if u.get("user_id") == owner_id:
            team_name = u.get("metadata", {}).get("team_name") or u.get("display_name", "Unknown")
            break

    player_ids = target_roster.get("players") or []
    starters = set(target_roster.get("starters") or [])
    taxi = set(target_roster.get("taxi") or [])

    players = []
    for pid in player_ids:
        sp = sleeper_players.get(pid)
        if not sp:
            continue
        name = f"{sp.get('first_name', '')} {sp.get('last_name', '')}".strip()
        position = norm_pos(sp.get("position", ""))
        team = sp.get("team", "") or ""
        player_data = {
            "name": name,
            "position": position,
            "team": team,
            "starter": pid in starters,
            "taxi": pid in taxi,
            "rookie": sp.get("years_exp") == 0,
        }
        z = z_lookup.get(norm_name(name))
        if z:
            player_data["aggregate"] = z["aggregate"]
            player_data["sources"] = z["sources"]
        players.append(player_data)

    # Add draft picks
    try:
        traded_picks, draft_order, completed_seasons = fetch_league_picks(league_id)
        picks = build_picks_for_roster(
            int(roster_id), rosters, users, league, traded_picks, draft_order, z_lookup,
            completed_seasons,
        )
        players.extend(picks)
    except Exception:
        pass  # draft picks are a bonus

    players.sort(key=lambda p: (
        not p["starter"],
        -(p.get("aggregate") or -999),
        p["name"],
    ))

    return {"league_name": league.get("name", "League"), "team_name": team_name, "players": players}


def merge_players(*source_pairs):
    """Merge any number of (label, players_dict) pairs into ranked list.

    Each source_pair is ("source_name", {name: {name, position, team, value}}).
    """
    # Turn each source's raw values into percentiles (0 = best, 1 = worst)
    pct_maps = []
    for label, players_dict in source_pairs:
        pct_maps.append((label, players_dict, compute_percentiles(players_dict)))

    # Collect all player names
    all_names = set()
    for _, players_dict, _ in pct_maps:
        all_names |= players_dict.keys()

    merged = []
    for name in all_names:
        position = None
        team = None
        sources = {}
        pcts = []
        for label, players_dict, pct_dict in pct_maps:
            p = players_dict.get(name)
            if p:
                if position is None:
                    position = p["position"]
                    team = p["team"]
                sources[label] = p["value"]
                pcts.append(pct_dict[name])
        # Average the percentiles a player appears in, then map onto the value curve
        pct = sum(pcts) / len(pcts)
        aggregate = round(
            VALUE_SCALE * math.exp(-(VALUE_TOP_DECAY * pct + VALUE_TAIL_DECAY * pct ** 4)), 2
        )
        merged.append({
            "name": name,
            "position": position,
            "team": team,
            "aggregate": aggregate,
            "sources": sources,
        })
    merged.sort(key=lambda p: p["aggregate"], reverse=True)
    return merged


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/players":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            if IS_VERCEL:
                self.send_header("Cache-Control", "s-maxage=3600, stale-while-revalidate=86400")
            self.end_headers()
            try:
                ktc_raw = fetch_ktc()
                fc_raw = fetch_fc()
                fp_raw = load_fp()
                ktc = normalize_ktc(ktc_raw)
                fc = normalize_fc(fc_raw)
                fp = normalize_fp(fp_raw)
                players = merge_players(
                    ("keeptradecut.com", ktc),
                    ("fantasycalc.com", fc),
                    ("fantasypros.com", fp),
                )
                self.wfile.write(json.dumps(players).encode())
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        elif re.match(r"/api/league/[^/]+/team/[^/]+", self.path):
            parts = self.path.split("/")
            league_id = parts[3]
            roster_id = parts[5].split("?")[0]
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            if IS_VERCEL:
                self.send_header("Cache-Control", "s-maxage=3600, stale-while-revalidate=86400")
            self.end_headers()
            try:
                data = build_team_roster(league_id, roster_id)
                self.wfile.write(json.dumps(data).encode())
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        elif re.match(r"/api/league/[^/]+/transactions", self.path):
            league_id = self.path.split("/api/league/")[1].split("/transactions")[0]
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                data = fetch_league_transactions(league_id)
                self.wfile.write(json.dumps(data).encode())
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        elif re.match(r"/api/league/[^/]+/teams", self.path):
            league_id = self.path.split("/api/league/")[1].split("/teams")[0]
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            if IS_VERCEL:
                self.send_header("Cache-Control", "s-maxage=3600, stale-while-revalidate=86400")
            self.end_headers()
            try:
                data = build_teams_list(league_id)
                self.wfile.write(json.dumps(data).encode())
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        elif re.match(r"/api/league/[^/]+/schedule", self.path):
            league_id = self.path.split("/api/league/")[1].split("/schedule")[0]
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            if IS_VERCEL:
                self.send_header("Cache-Control", "s-maxage=3600, stale-while-revalidate=86400")
            self.end_headers()
            try:
                data = fetch_league_schedule(league_id)
                self.wfile.write(json.dumps(data).encode())
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        elif self.path == "/api/trades":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                trades_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trades.json")
                with open(trades_path, "r") as f:
                    self.wfile.write(f.read().encode())
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        elif self.path.startswith("/api/sync"):
            user_id = self.headers.get("X-User-Id")
            if not user_id:
                self._json_response(401, {"error": "Not authenticated"})
                return
            try:
                parsed = urlparse(self.path)
                params = parse_qs(parsed.query)
                sport = params.get("sport", [None])[0]
                if not sport:
                    self._json_response(400, {"error": "sport parameter is required"})
                    return
                key = params.get("key", [None])[0]
                query = (
                    f"user_data?user_id=eq.{urllib.request.quote(user_id)}"
                    f"&sport=eq.{urllib.request.quote(sport)}"
                    f"&select=data_key,data,updated_at"
                )
                if key:
                    query += f"&data_key=eq.{urllib.request.quote(key)}"
                rows = supabase_request(query)
                if key:
                    self._json_response(200, rows[0]["data"] if rows else None)
                else:
                    self._json_response(200, {r["data_key"]: r["data"] for r in rows})
            except Exception as e:
                self._json_response(500, {"error": str(e)})
        elif self.path.startswith("/api/bets"):
            eff, err = resolve_bets_user(self.headers, require_active=False)
            if err:
                self._json_response(*err)
                return
            try:
                rows = supabase_request(
                    f"bets?user_id=eq.{urllib.request.quote(eff)}"
                    f"&select=data&order=created_at"
                )
                self._json_response(200, [r["data"] for r in (rows or [])])
            except Exception as e:
                self._json_response(500, {"error": str(e)})
        elif self.path.startswith("/api/users"):
            # Admin-only: list all users for the /bets/audit dropdown.
            user_id = self.headers.get("X-User-Id")
            if not user_id:
                self._json_response(401, {"error": "Not authenticated"})
                return
            try:
                actor = fetch_user(user_id)
                if (not actor or actor.get("status") is not True
                        or actor.get("role") != "admin"):
                    self._json_response(403, {"error": "Admin access required"})
                    return
                rows = supabase_request("users?select=id,username&order=username.asc")
                self._json_response(200, rows or [])
            except Exception as e:
                self._json_response(500, {"error": str(e)})
        elif self.path.startswith("/api/lookup"):
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            username = params.get("username", [None])[0]
            if not username:
                self._json_response(400, {"error": "username parameter is required"})
                return
            try:
                users = supabase_request(
                    f"users?username=eq.{urllib.request.quote(username)}&select=id,username"
                )
                if not users:
                    self._json_response(404, {"error": "no username found"})
                    return
                uid = users[0]["id"]
                sport = params.get("sport", ["masters"])[0]
                rows = supabase_request(
                    f"user_data?user_id=eq.{uid}"
                    f"&sport=eq.{urllib.request.quote(sport)}"
                    f"&data_key=eq.3ball"
                    f"&select=data"
                )
                data = rows[0]["data"] if rows else {"rounds": {}}
                self._json_response(200, {"username": users[0]["username"], "threeBall": data})
            except Exception as e:
                self._json_response(500, {"error": str(e)})
        elif self.path.startswith("/api/golf/scores"):
            parsed_url = urlparse(self.path)
            qparams = parse_qs(parsed_url.query)
            tournament = qparams.get("tournament", [None])[0]
            year = qparams.get("year", [None])[0]
            if not tournament or not year:
                self._json_response(400, {"error": "tournament and year parameters are required"})
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            if IS_VERCEL:
                config = GOLF_TOURNAMENTS.get((tournament, year), {})
                if config.get("mode") == "archive":
                    self.send_header("Cache-Control", "public, max-age=86400, s-maxage=86400")
                else:
                    self.send_header("Cache-Control", "s-maxage=300, stale-while-revalidate=600")
            self.end_headers()
            try:
                data = fetch_golf_scores(tournament, year)
                self.wfile.write(json.dumps(data).encode())
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        elif self.path == "/api/masters/scores":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            if IS_VERCEL:
                self.send_header("Cache-Control", "public, max-age=86400, s-maxage=86400")
            self.end_headers()
            try:
                data = fetch_masters_scores()
                self.wfile.write(json.dumps(data).encode())
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        elif self.path == "/account":
            self.path = "/views/home/account.html"
            super().do_GET()
        elif self.path == "/archive":
            self.path = "/views/home/archive.html"
            super().do_GET()
        # Redirect old /masters/* URLs to /golf/2026/masters/*
        elif self.path == "/masters":
            self.send_response(301)
            self.send_header("Location", "/golf/2026/masters")
            self.end_headers()
        elif self.path.startswith("/masters/"):
            page = self.path[len("/masters/"):].split("?")[0]
            self.send_response(301)
            self.send_header("Location", f"/golf/2026/masters/{page}")
            self.end_headers()
        # Hub pages
        elif self.path == "/golf":
            self.path = "/views/home/golf-hub.html"
            super().do_GET()
        elif self.path == "/football":
            self.path = "/views/home/football.html"
            super().do_GET()
        elif self.path == "/football/grading-system":
            self.path = "/views/home/grading-system.html"
            super().do_GET()
        elif self.path == "/odds":
            self.path = "/views/odds/index.html"
            super().do_GET()
        elif self.path.split("?")[0] == "/bets/audit":
            self.path = "/views/bets/audit.html"
            super().do_GET()
        elif self.path.split("?")[0] == "/bets/place":
            self.path = "/views/bets/place.html"
            super().do_GET()
        elif self.path.split("?")[0] == "/bets/history":
            self.path = "/views/bets/history.html"
            super().do_GET()
        elif self.path.split("?")[0] == "/bets/settle":
            self.path = "/views/bets/settle.html"
            super().do_GET()
        elif self.path.split("?")[0] == "/bets":
            self.path = "/views/bets/index.html"
            super().do_GET()
        elif self.path == "/jane":
            self.path = "/views/jane/index.html"
            super().do_GET()
        elif self.path == "/jane/jobs":
            self.path = "/views/jane/jobs.html"
            super().do_GET()
        elif self.path == "/jane/admin":
            self.path = "/views/jane/admin.html"
            super().do_GET()
        elif self.path == "/jane/marketing-coordinator":
            self.path = "/views/jane/marketing-coordinator.html"
            super().do_GET()
        elif self.path == "/jane/asheville-rentals":
            self.path = "/views/jane/asheville-rentals.html"
            super().do_GET()
        elif self.path == "/jane/builders-claude":
            self.path = "/views/jane/builders-claude.html"
            super().do_GET()
        elif self.path == "/jane/builders-chatgpt":
            self.path = "/views/jane/builders-chatgpt.html"
            super().do_GET()
        # Golf routes: /golf/:year/:tournament/:page
        elif re.match(r"/golf/\d{4}$", self.path) or re.match(r"/season/\d{4}$", self.path):
            self.path = "/views/golf/season.html"
            super().do_GET()
        elif re.match(r"/golf/\d{4}/[^/]+$", self.path):
            self.path = "/views/golf/hub.html"
            super().do_GET()
        elif re.match(r"/golf/\d{4}/[^/]+/leaderboard", self.path):
            self.path = "/views/golf/leaderboard.html"
            super().do_GET()
        elif re.match(r"/golf/\d{4}/[^/]+/select-golfers", self.path):
            self.path = "/views/golf/select-golfers.html"
            super().do_GET()
        elif re.match(r"/golf/\d{4}/[^/]+/3-ball-results", self.path):
            self.path = "/views/golf/3-ball-results.html"
            super().do_GET()
        elif re.match(r"/golf/\d{4}/[^/]+/3-ball-lookup", self.path):
            self.path = "/views/golf/3-ball-lookup.html"
            super().do_GET()
        elif re.match(r"/golf/\d{4}/[^/]+/3-ball$", self.path):
            self.path = "/views/golf/3-ball.html"
            super().do_GET()
        elif re.match(r"/golf/\d{4}/[^/]+/group-results", self.path):
            self.path = "/views/golf/group-results.html"
            super().do_GET()
        elif re.match(r"/golf/\d{4}/[^/]+/groups$", self.path):
            self.path = "/views/golf/groups.html"
            super().do_GET()
        elif re.match(r"/golf/\d{4}/[^/]+/ev-model", self.path):
            self.path = "/views/golf/ev-model.html"
            super().do_GET()
        elif re.match(r"/league/[^/]+/team/", self.path):
            self.path = "/views/league/team.html"
            super().do_GET()
        elif re.match(r"/league/[^/]+/trades", self.path):
            self.path = "/views/league/trades.html"
            super().do_GET()
        elif re.match(r"/league/[^/]+/scout", self.path):
            self.path = "/views/league/scout.html"
            super().do_GET()
        elif re.match(r"/league/[^/]+/power", self.path):
            self.path = "/views/league/power.html"
            super().do_GET()
        elif re.match(r"/league/[^/]+/schedule", self.path):
            self.path = "/views/league/schedule.html"
            super().do_GET()
        elif re.match(r"/league/[^/]+/rosters", self.path):
            self.path = "/views/league/league.html"
            super().do_GET()
        elif re.match(r"/league/[^/]+/?$", self.path):
            league_id = self.path.split("/league/")[1].strip("/")
            self.send_response(302)
            self.send_header("Location", f"/league/{league_id}/scout")
            self.end_headers()
        elif self.path.startswith("/league/"):
            self.path = "/views/league/league.html"
            super().do_GET()
        elif self.path == "/acknowledgements":
            self.path = "/views/home/acknowledgements.html"
            super().do_GET()
        elif self.path == "/trade-calculator":
            self.path = "/views/tools/trade-calculator.html"
            super().do_GET()
        elif self.path == "/" or self.path == "":
            self.path = "/views/index.html"
            super().do_GET()
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == "/api/auth":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            action = body.get("action")
            try:
                if action == "register":
                    username = (body.get("username") or "").strip()
                    password = body.get("password") or ""
                    if not username:
                        self._json_response(400, {"error": "Username is required"})
                        return
                    if len(password) < MIN_PASSWORD_LEN:
                        self._json_response(400, {"error": f"Password must be at least {MIN_PASSWORD_LEN} characters"})
                        return
                    existing = supabase_request(
                        f"users?username=eq.{urllib.request.quote(username)}&select=id"
                    )
                    if existing:
                        self._json_response(409, {"error": "That username is already taken"})
                        return
                    result = supabase_request("users", method="POST", body={
                        "username": username, "password_hash": hash_password(password),
                    }, extra_headers={"Prefer": "return=representation"})
                    user = result[0]
                    self._json_response(200, {
                        "user_id": user["id"], "username": user["username"],
                        "role": user["role"],
                    })
                elif action == "login":
                    username = (body.get("username") or "").strip()
                    password = body.get("password") or ""
                    if not username or not password:
                        self._json_response(400, {"error": "Username and password are required"})
                        return
                    users = supabase_request(
                        f"users?username=eq.{urllib.request.quote(username)}"
                        f"&select=id,username,password_hash,role,status"
                    )
                    if not users or not verify_password(password, users[0].get("password_hash") or ""):
                        self._json_response(401, {"error": "Invalid username or password"})
                        return
                    user = users[0]
                    self._json_response(200, {
                        "user_id": user["id"], "username": user["username"],
                        "role": user["role"],
                    })
                else:
                    self._json_response(400, {"error": "Unknown action"})
            except Exception as e:
                self._json_response(500, {"error": str(e)})
        elif self.path == "/api/asheville-rentals/refresh":
            # Local-only: re-scrape every Asheville rental source by running the
            # Node scraper, which writes both data.json copies. Then return the
            # fresh site-served file. (This endpoint only exists on the local dev
            # server; production has no equivalent, so the page hides the button.)
            root = os.path.dirname(os.path.abspath(__file__))
            scraper_dir = os.path.join(root, "asheville-rentals")
            try:
                proc = subprocess.run(
                    ["node", "scrape.mjs"],
                    cwd=scraper_dir, capture_output=True, text=True, timeout=240,
                )
                if proc.returncode != 0:
                    err = (proc.stderr or proc.stdout or "unknown error").strip()
                    self._json_response(500, {"error": "Scrape failed: " + err[-500:]})
                    return
                with open(os.path.join(root, "data", "asheville-rentals.json")) as f:
                    payload = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(payload.encode())
            except subprocess.TimeoutExpired:
                self._json_response(504, {"error": "Scrape timed out after 240s"})
            except Exception as e:
                self._json_response(500, {"error": str(e)})
        else:
            self.send_response(404)
            self.end_headers()

    def do_PUT(self):
        if self.path == "/api/sync":
            user_id = self.headers.get("X-User-Id")
            if not user_id:
                self._json_response(401, {"error": "Not authenticated"})
                return
            try:
                user = fetch_user(user_id)
                if not user or user.get("status") is not True:
                    self._json_response(403, {"error": "Account is inactive"})
                    return
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length)) if length else {}
                sport = body.get("sport")
                key = body.get("key")
                data = body.get("data")
                if not sport or not key:
                    self._json_response(400, {"error": "sport and key are required"})
                    return
                supabase_request(
                    "user_data?on_conflict=user_id,sport,data_key",
                    method="POST", body={
                        "user_id": user_id, "sport": sport, "data_key": key,
                        "data": data, "updated_at": "now()",
                    }, extra_headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
                )
                self._json_response(200, {"ok": True})
            except Exception as e:
                self._json_response(500, {"error": str(e)})
        elif self.path == "/api/bets":
            eff, err = resolve_bets_user(self.headers, require_active=True)
            if err:
                self._json_response(*err)
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                bet = json.loads(self.rfile.read(length)) if length else {}
                bet_id = bet.get("id")
                if not bet_id:
                    self._json_response(400, {"error": "bet id is required"})
                    return
                # Upsert on (user_id, id) — a client can never touch another
                # user's row even by supplying someone else's bet id.
                supabase_request(
                    "bets?on_conflict=user_id,id",
                    method="POST", body={
                        "user_id": eff, "id": bet_id,
                        "data": bet, "updated_at": "now()",
                    }, extra_headers={"Prefer": "resolution=merge-duplicates,return=representation"},
                )
                self._json_response(200, {"ok": True})
            except Exception as e:
                self._json_response(500, {"error": str(e)})
        else:
            self.send_response(404)
            self.end_headers()

    def do_DELETE(self):
        if self.path.startswith("/api/bets"):
            eff, err = resolve_bets_user(self.headers, require_active=True)
            if err:
                self._json_response(*err)
                return
            try:
                params = parse_qs(urlparse(self.path).query)
                bet_id = params.get("id", [None])[0]
                if not bet_id:
                    self._json_response(400, {"error": "id parameter is required"})
                    return
                supabase_request(
                    f"bets?user_id=eq.{urllib.request.quote(eff)}"
                    f"&id=eq.{urllib.request.quote(bet_id)}",
                    method="DELETE",
                    extra_headers={"Prefer": "return=representation"},
                )
                self._json_response(200, {"ok": True})
            except Exception as e:
                self._json_response(500, {"error": str(e)})
        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-User-Id, X-Audit-User-Id")
        self.end_headers()

    def _json_response(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-User-Id, X-Audit-User-Id")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        if "/api/" in (args[0] if args else ""):
            super().log_message(format, *args)


if __name__ == "__main__":
    print(f"Starting server at http://localhost:{PORT}")
    with http.server.HTTPServer(("", PORT), Handler) as httpd:
        httpd.serve_forever()
