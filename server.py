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
from datetime import datetime, timedelta, timezone
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
RESET_CODE_TTL_MINUTES = 30
# No 0/O/1/I/L: these codes get read aloud or retyped off a screenshot.
RESET_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


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
        raw = resp.read()          # PATCH/DELETE answer 204 with no body
        return json.loads(raw) if raw else None


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


def q(value):
    """Escape a PostgREST filter value. safe='' matters for timestamps, where a
    bare '+' in the UTC offset would otherwise decode as a space."""
    return urllib.request.quote(str(value), safe="")


def new_reset_code():
    raw = "".join(secrets.choice(RESET_CODE_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def hash_reset_code(code):
    """Codes are stored as a digest only, so a dump of password_resets can't be
    replayed. Normalized first, so '8f3k-92qx', '8F3K92QX' and ' 8F3K 92QX '
    all redeem the same row."""
    normalized = "".join(ch for ch in (code or "").upper() if ch.isalnum())
    return hashlib.sha256(normalized.encode()).hexdigest()


def retire_reset_codes(user_id):
    """Burn every outstanding code for a user. Called when one is redeemed, when
    a fresh one is issued, and when the password changes by any route — so at
    most one code is ever live, and changing your password kills a code an admin
    handed out while you still knew the old one."""
    supabase_request(
        f"password_resets?user_id=eq.{q(user_id)}&used_at=is.null",
        method="PATCH",
        body={"used_at": datetime.now(timezone.utc).isoformat()},
    )


def set_password(user_id, password):
    supabase_request(
        f"users?id=eq.{q(user_id)}",
        method="PATCH",
        body={"password_hash": hash_password(password)},
    )
    retire_reset_codes(user_id)


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


_bun_notes_api = None


def bun_notes_api():
    """Load api/bun-notes.py for its note validation, so this local mirror and
    the deployed function can never disagree about what a valid note is. Loaded
    by path because the filename has a hyphen in it, and lazily because a dev
    who never opens Baker's Buns should not pay for it."""
    global _bun_notes_api
    if _bun_notes_api is None:
        import importlib.util
        path = os.path.join(DATA_DIR, "api", "bun-notes.py")
        spec = importlib.util.spec_from_file_location("bun_notes_api", path)
        _bun_notes_api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_bun_notes_api)
    return _bun_notes_api


def resolve_notes_actor(headers):
    """Baker's Buns notes are a published, global store: anyone may read them,
    any active account may add to them, and a note belongs to whoever filed it.
    Returns (user_id, is_admin, error) — the ownership check itself is
    api.may_write, against the authors api.fetch_authors reads back.

    Delegated to the deployed function so the two can never disagree about who
    may write. No audit-target indirection: a note's owner writes it directly,
    and an admin can already edit any of them."""
    return bun_notes_api().resolve_actor(headers.get("X-User-Id"))


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


# Value sources use their own team codes; canonicalize to Sleeper's convention
# (Sleeper is what player resolution joins against).
_TEAM_ALIASES = {
    "GBP": "GB", "JAC": "JAX", "KCC": "KC", "LVR": "LV",
    "NEP": "NE", "NOS": "NO", "SFO": "SF", "TBB": "TB",
}


def normalize_team(team):
    """Canonicalize a team code to Sleeper's convention. Empty/None and 'FA'
    both mean free agent -> 'FA'. Not for picks (they have no team)."""
    t = (team or "").strip().upper()
    if not t or t == "FA":
        return "FA"
    return _TEAM_ALIASES.get(t, t)


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
            pos = norm_pos(p.get("position", ""))
            players[key] = {
                "name": key,
                "position": pos,
                "team": "" if pos == "PICK" else normalize_team(p.get("team", "")),
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
            pos = norm_pos(p.get("position", ""))
            players[key] = {
                "name": key,
                "position": pos,
                "team": "" if pos == "PICK" else normalize_team(p.get("maybeTeam", "")),
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
            pos = p.get("position", "")
            players[key] = {
                "name": key,
                "position": pos,
                "team": "" if pos == "PICK" else normalize_team(p.get("team", "")),
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
_ORDINAL_TO_ROUND = {v: k for k, v in _ORDINALS.items()}


def canonical_pick_key(season, rd, tier):
    """One canonical identifier for a rookie draft pick, e.g. '2026|1|Early'.

    Shared by the value pool and the roster views so both sides match picks the
    same way instead of via two different name-variant heuristics. `tier` is
    'Early' | 'Mid' | 'Late'.
    """
    return f"{int(season)}|{int(rd)}|{tier}"


def pick_tier_from_slot(slot, total_rosters):
    """Bucket a draft slot (1-based) into Early/Mid/Late by thirds, or None if
    the slot is unknown (e.g. a future season whose draft order isn't set)."""
    if not slot:
        return None
    third = max(total_rosters // 3, 1)
    if slot <= third:
        return "Early"
    if slot <= third * 2:
        return "Mid"
    return "Late"


def parse_pick_name(name):
    """Parse a value-source pick name like '2026 Early 1st' into a canonical
    pick key, or None if it isn't a tiered pick. Lets the pool index its picks
    under the same keys the roster views look them up by."""
    m = _PICK_TIER_RE.match(name)
    if not m:
        return None
    season, tier, ordinal = m.groups()
    rd = _ORDINAL_TO_ROUND.get(ordinal)
    if not rd:
        return None
    return canonical_pick_key(season, rd, tier)


def _pick_name_variants(season, rd, slot, total_rosters):
    """Return a list of name variants to try matching against z_lookup, best first.

    Legacy fallback for picks the canonical-key lookup misses.
    """
    ordinal = _ORDINALS.get(rd, f"{rd}th")
    names = []
    if slot:
        names.append(f"{season} Pick {rd}.{slot:02d}")
    tier = pick_tier_from_slot(slot, total_rosters)
    names.append(f"{season} {tier or 'Mid'} {ordinal}")
    names.append(f"{season} {ordinal}")
    return names


def build_picks_for_roster(roster_id, rosters, users, league, traded_picks, draft_order, z_lookup,
                           completed_seasons=(), pick_lookup=None):
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
                # Display name: include original team label if traded
                ordinal = _ORDINALS.get(rd, f"{rd}th")
                if orig_rid != roster_id:
                    display = f"{season} {ordinal} ({roster_label(orig_rid)})"
                else:
                    display = f"{season} {ordinal}"
                # Match values by canonical pick key (same key the pool indexes
                # under); fall back to legacy name-variant matching on a miss.
                tier = pick_tier_from_slot(pick_slot, total_rosters) or "Mid"
                z = (pick_lookup or {}).get(canonical_pick_key(season, rd, tier))
                if z is None:
                    for v in _pick_name_variants(str(season), rd, pick_slot, total_rosters):
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

    # Build value lookups from trade calculator data: z_lookup keyed by
    # normalized name (players), pick_lookup keyed by canonical pick key (picks).
    z_lookup = {}
    pick_lookup = {}
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
            if p["position"] == "PICK":
                key = parse_pick_name(p["name"])
                if key:
                    pick_lookup[key] = p
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
        team = normalize_team(sp.get("team"))
        player_data = {
            "player_id": pid,
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
            completed_seasons, pick_lookup,
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


FANTASY_POSITIONS = {"QB", "RB", "WR", "TE", "K"}


def build_player_resolver():
    """Build a name -> Sleeper player index for resolving value-pool entries to
    stable player_ids.

    The value sources (KTC/FantasyCalc/FantasyPros) identify players by name
    only, so resolving to a Sleeper player_id is still a name lookup at its core
    — but doing it once here lets everything downstream (rookie flag, dedup,
    roster cross-referencing) key on the ID instead of on name+position.

    Returns (index, ok) where index maps norm_name -> list of compact Sleeper
    records; ok is False if Sleeper data was unavailable. Restricted to fantasy
    positions to cut collisions with the DB's thousands of inactive/IDP entries.
    """
    try:
        sleeper_players = fetch_sleeper_players()
    except Exception:
        return {}, False
    index = {}
    for pid, sp in sleeper_players.items():
        if not isinstance(sp, dict):
            continue
        pos = norm_pos(sp.get("position", "") or "")
        if pos not in FANTASY_POSITIONS:
            continue
        name = f"{sp.get('first_name', '')} {sp.get('last_name', '')}".strip()
        if not name:
            continue
        index.setdefault(norm_name(name), []).append({
            "player_id": pid,
            "position": pos,
            "team": normalize_team(sp.get("team")),
            "years_exp": sp.get("years_exp"),
            "active": bool(sp.get("active")),
        })
    return index, True


def resolve_player(index, name, position, team):
    """Resolve a value-pool entry to a single Sleeper record, or None if there's
    no unambiguous match. Disambiguates same-name players by position, then team
    (the only signals the value sources carry); a genuinely ambiguous entry —
    same name, position, and team — stays unresolved rather than guess."""
    candidates = index.get(norm_name(name))
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    pos = norm_pos(position or "")
    pool = [c for c in candidates if c["position"] == pos] or candidates
    if len(pool) == 1:
        return pool[0]
    team_c = normalize_team(team)
    if team_c != "FA":
        by_team = [c for c in pool if c["team"] == team_c]
        if len(by_team) == 1:
            return by_team[0]
        if by_team:
            pool = by_team
    # Last resort: a single active candidate breaks the remaining tie.
    active = [c for c in pool if c["active"]]
    return active[0] if len(active) == 1 else None


### Baker's Oven ###############################################################
# Resolving board rows to Sleeper player_ids happens once, at CSV upload, so the
# live draft path is an exact ID match and no fuzzy matching can fail mid-draft.

# FantasyPros calls team defenses "DST", Sleeper calls them "DEF". Sleeper also
# uses the team abbreviation itself as the defense's player_id ("SEA"), so
# defenses resolve by team code and never touch the name index.
_DEF_POSITIONS = {"DEF", "DST", "D/ST", "DS"}

# Team defenses are commonly written as a city or full team name in a hand-built
# board ("Seattle", "Seattle Seahawks", "Seahawks"); map the nickname/city back
# to Sleeper's abbreviation.
_DEF_NAME_HINTS = {
    "cardinals": "ARI", "arizona": "ARI", "falcons": "ATL", "atlanta": "ATL",
    "ravens": "BAL", "baltimore": "BAL", "bills": "BUF", "buffalo": "BUF",
    "panthers": "CAR", "carolina": "CAR", "bears": "CHI", "chicago": "CHI",
    "bengals": "CIN", "cincinnati": "CIN", "browns": "CLE", "cleveland": "CLE",
    "cowboys": "DAL", "dallas": "DAL", "broncos": "DEN", "denver": "DEN",
    "lions": "DET", "detroit": "DET", "packers": "GB", "green bay": "GB",
    "texans": "HOU", "houston": "HOU", "colts": "IND", "indianapolis": "IND",
    "jaguars": "JAX", "jacksonville": "JAX", "chiefs": "KC", "kansas city": "KC",
    "raiders": "LV", "las vegas": "LV", "chargers": "LAC", "rams": "LAR",
    "dolphins": "MIA", "miami": "MIA", "vikings": "MIN", "minnesota": "MIN",
    "patriots": "NE", "new england": "NE", "saints": "NO", "new orleans": "NO",
    "giants": "NYG", "jets": "NYJ", "eagles": "PHI", "philadelphia": "PHI",
    "steelers": "PIT", "pittsburgh": "PIT", "49ers": "SF", "niners": "SF",
    "san francisco": "SF", "seahawks": "SEA", "seattle": "SEA",
    "buccaneers": "TB", "bucs": "TB", "tampa bay": "TB", "titans": "TEN",
    "tennessee": "TEN", "commanders": "WAS", "washington": "WAS",
}


def _loose_name(name):
    """Aggressive name key for hand-typed board entries: lowercase, suffixes and
    all punctuation removed. Only used as a fallback after norm_name() misses —
    norm_name() itself is left alone because the trade calculator depends on its
    exact behavior."""
    return re.sub(r"[^a-z0-9]", "", norm_name(name or "").lower())


def resolve_defense(name, team):
    """Resolve a team defense to Sleeper's player_id (the team abbreviation)."""
    code = normalize_team(team)
    if code != "FA":
        return code
    key = (name or "").strip().lower()
    if key in _DEF_NAME_HINTS:
        return _DEF_NAME_HINTS[key]
    # Fall back to any nickname/city appearing in the string ("Seattle D/ST").
    for hint, abbr in _DEF_NAME_HINTS.items():
        if hint in key:
            return abbr
    guess = normalize_team(name)
    return guess if guess != "FA" else None


def resolve_board_players(entries):
    """Resolve board rows to Sleeper player_ids.

    Takes [{name, pos, team}, ...] and returns one result per entry, in order,
    with player_id set to None when no unambiguous match exists. Unmatched rows
    are always returned rather than dropped, so the UI can name them.
    """
    index, ok = build_player_resolver()
    if not ok:
        raise RuntimeError("Sleeper player data unavailable")

    # Loose index built once, consulted only when the strict pass misses.
    loose = {}
    for norm, candidates in index.items():
        loose.setdefault(re.sub(r"[^a-z0-9]", "", norm.lower()), []).extend(candidates)

    results = []
    for entry in entries:
        name = (entry.get("name") or "").strip()
        pos = (entry.get("pos") or "").strip().upper()
        team = (entry.get("team") or "").strip()

        if not name:
            results.append({"player_id": None, "reason": "empty name"})
            continue

        if pos in _DEF_POSITIONS:
            pid = resolve_defense(name, team)
            results.append({
                "player_id": pid, "position": "DEF", "team": pid,
                "reason": None if pid else "unknown defense",
            })
            continue

        match = resolve_player(index, name, pos, team)
        if not match:
            candidates = loose.get(_loose_name(name)) or []
            if pos:
                narrowed = [c for c in candidates if c["position"] == norm_pos(pos)]
                if narrowed:
                    candidates = narrowed
            if len(candidates) == 1:
                match = candidates[0]
            elif candidates:
                active = [c for c in candidates if c.get("active")]
                match = active[0] if len(active) == 1 else None

        if match:
            results.append({
                "player_id": match["player_id"],
                "position": match["position"],
                "team": match["team"],
                "rookie": match.get("years_exp") == 0,
                "reason": None,
            })
        else:
            results.append({"player_id": None, "reason": "no unambiguous match"})

    return results


def rookie_keys_from_resolver(index):
    """Fallback rookie set ('normname|POS') derived from the resolver index, for
    pool entries that don't resolve to a unique player_id. One DB pass, same
    name+position signal the pool used before IDs."""
    keys = set()
    for norm, candidates in index.items():
        for c in candidates:
            if c.get("years_exp") == 0:
                keys.add(f"{norm}|{c['position']}")
    return keys


class Handler(http.server.SimpleHTTPRequestHandler):
    # Mirror vercel.json: HTML is no-store so a refresh always gets the current
    # build. Locally we extend that to /styles and /scripts too, because dev
    # serves them unhashed (build.py only runs on deploy) and a cached copy
    # under an unversioned URL would survive an edit.
    NO_STORE_PREFIXES = ("/views/", "/styles/", "/scripts/")

    def send_head(self):
        # Only static serving reaches send_head; the /api branches in do_GET
        # write their own headers and set their own Cache-Control.
        self._no_store = self.path.startswith(self.NO_STORE_PREFIXES)
        try:
            return super().send_head()
        finally:
            self._no_store = False

    def end_headers(self):
        if getattr(self, "_no_store", False):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

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
                resolver, resolver_ok = build_player_resolver()
                rookie_fallback = rookie_keys_from_resolver(resolver) if resolver_ok else set()
                for p in players:
                    match = resolve_player(resolver, p["name"], p["position"], p["team"])
                    if match:
                        # Resolved to a stable Sleeper player_id: flag rookies the
                        # same ID-based way the roster views do (years_exp == 0).
                        p["player_id"] = match["player_id"]
                        p["rookie"] = match.get("years_exp") == 0
                    else:
                        # Unresolved (ambiguous name or Sleeper down): fall back to
                        # the name+position rookie signal so it isn't lost.
                        p["rookie"] = f"{p['name']}|{p['position']}" in rookie_fallback
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
        elif self.path.startswith("/api/bun-notes"):
            # Public: the notes are published reading, and the page renders them
            # for signed-out visitors.
            try:
                params = parse_qs(urlparse(self.path).query, keep_blank_values=True)
                query = "bun_notes?select=data&order=created_at"
                if "team" in params:
                    team = (params["team"][0] or "").upper()
                    query += "&team=eq." + urllib.request.quote(team)
                rows = supabase_request(query)
                self._json_response(200, [r["data"] for r in (rows or [])])
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
        # Query string tolerated: gated pages link here as /account?next=…, and
        # Vercel's rewrites match on the path alone, so dev must too.
        elif self.path.split("?")[0] == "/account":
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
        # The Action Network book. One page per slate: /football/action is the
        # index, /futures the season book, /week/{n} one week of the schedule.
        # Admin-only in the UI (auth.js requireAdmin), but the files themselves
        # are static and public — same caveat as every other page here.
        #
        # Matched longest-path-first, and the week id is digits-only so a junk
        # segment 404s rather than serving a page that does not exist. Mirrors
        # the rewrites block in vercel.json, which orders them the same way for
        # the same reason.
        elif self.path.split("?")[0] == "/football/action/futures":
            self.path = "/views/football/action-futures.html"
            super().do_GET()
        elif re.match(r"^/football/action/week/\d+/?$", self.path.split("?")[0]):
            week = self.path.split("?")[0].rstrip("/").rsplit("/", 1)[1]
            self.path = f"/views/football/action-week-{week}.html"
            super().do_GET()
        elif self.path.split("?")[0] in ("/football/action/preseason",
                                         "/football/action/postseason",
                                         "/football/action/other"):
            slate = self.path.split("?")[0].rsplit("/", 1)[1]
            self.path = f"/views/football/action-{slate}.html"
            super().do_GET()
        elif self.path.split("?")[0] == "/football/action":
            self.path = "/views/football/action.html"
            super().do_GET()
        # The book used to be one page at /football/futures. Anything already
        # bookmarked lands on its replacement in one hop, as in vercel.json.
        elif self.path.split("?")[0] == "/football/futures":
            self.send_response(301)
            self.send_header("Location", "/football/action/futures")
            self.end_headers()
        # Query string tolerated: the schedule page keeps its week/team filters
        # in ?week=&team= so a view is linkable, and Vercel matches on the path
        # alone, so dev must too.
        elif self.path.split("?")[0] == "/football/schedule":
            self.path = "/views/football/schedule.html"
            super().do_GET()
        # Methodology is its own route rather than a section of the table's
        # page, so it must be matched before the page it hangs off.
        elif self.path.split("?")[0] == "/football/bakers-buns/methodology":
            self.path = "/views/football/bakers-buns-methodology.html"
            super().do_GET()
        elif self.path.split("?")[0] == "/football/bakers-buns":
            self.path = "/views/football/bakers-buns.html"
            super().do_GET()
        # Baker's Oven — live draft companion. /football/bakers-oven is the
        # account's saved-league list; /{leagueId} is that league's draft and
        # team picker; /{leagueId}/{rosterId} is that team's big board. Only
        # digits match: Sleeper ids are always numeric, and a junk segment
        # should 404 rather than boot a page that will fail against Sleeper.
        # A legacy one-segment roster id lands on oven-league.html, which
        # detects it by length and redirects.
        elif self.path.split("?")[0] == "/football/bakers-oven":
            self.path = "/views/football/oven-leagues.html"
            super().do_GET()
        # Ahead of the roster-id branch below, and ahead of the equivalent
        # rewrite in vercel.json for the same reason: Vercel's :rosterId is a
        # wildcard that would swallow "week-1". The regex here is digits-only
        # and could not, but the two files should read alike.
        elif re.match(r"^/football/bakers-oven/\d+/week-1/?$", self.path.split("?")[0]):
            self.path = "/views/football/oven-week1.html"
            super().do_GET()
        elif re.match(r"^/football/bakers-oven/\d+/\d+/?$", self.path.split("?")[0]):
            self.path = "/views/football/oven-board.html"
            super().do_GET()
        elif re.match(r"^/football/bakers-oven/\d+/?$", self.path.split("?")[0]):
            self.path = "/views/football/oven-league.html"
            super().do_GET()
        elif self.path.split("?")[0] == "/football/trade-calculator":
            self.path = "/views/football/trade-calculator.html"
            super().do_GET()
        # Both tools used to live at the top level, and the Oven before that at
        # /the-bakers-oven. Saved bookmarks and any board link already shared
        # keep working via a 301 onto the nested route. Mirrors the redirects
        # block in vercel.json — the old prefixes go straight to the final
        # path, so there is never a second hop.
        elif self.path.split("?")[0] in ("/the-bakers-oven", "/bakers-oven") or (
            self.path.startswith("/the-bakers-oven/") or self.path.startswith("/bakers-oven/")
        ):
            article = "/the-bakers-oven" if self.path.startswith("/the-bakers-oven") else "/bakers-oven"
            self.send_response(301)
            self.send_header(
                "Location", "/football/bakers-oven" + self.path[len(article):]
            )
            self.end_headers()
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
        elif self.path.split("?")[0] == "/trade-calculator":
            self.send_response(301)
            self.send_header("Location", "/football/trade-calculator")
            self.end_headers()
        elif self.path == "/" or self.path == "":
            self.path = "/views/index.html"
            super().do_GET()
        else:
            super().do_GET()

    def do_POST(self):
        # Baker's Oven: resolve uploaded board rows to Sleeper player_ids
        # once, at import, so the live draft path is an exact ID match.
        if self.path == "/api/football/resolve":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length)) if length else {}
                entries = body.get("players") or []
                if not isinstance(entries, list):
                    self._json_response(400, {"error": "players must be a list"})
                    return
                if len(entries) > 2000:
                    self._json_response(400, {"error": "Too many players (max 2000)"})
                    return
                results = resolve_board_players(entries)
                self._json_response(200, {
                    "players": results,
                    "matched": sum(1 for r in results if r.get("player_id")),
                    "total": len(results),
                })
            except Exception as e:
                self._json_response(500, {"error": str(e)})
            return
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
                # Signed-in change. The current password is the proof of
                # identity, which is why this doesn't settle for X-User-Id.
                elif action == "change_password":
                    user_id = self.headers.get("X-User-Id")
                    if not user_id:
                        self._json_response(401, {"error": "Not authenticated"})
                        return
                    current = body.get("current_password") or ""
                    new_password = body.get("new_password") or ""
                    if len(new_password) < MIN_PASSWORD_LEN:
                        self._json_response(400, {"error": f"Password must be at least {MIN_PASSWORD_LEN} characters"})
                        return
                    users = supabase_request(
                        f"users?id=eq.{q(user_id)}&select=id,password_hash,status"
                    )
                    if not users or users[0].get("status") is not True:
                        self._json_response(403, {"error": "Account is inactive"})
                        return
                    if not verify_password(current, users[0].get("password_hash") or ""):
                        self._json_response(401, {"error": "Current password is incorrect"})
                        return
                    set_password(user_id, new_password)
                    self._json_response(200, {"ok": True})
                # Admin hands the returned code to the locked-out user out of
                # band. It is shown once and never stored in the clear.
                elif action == "issue_reset":
                    actor_id = self.headers.get("X-User-Id")
                    if not actor_id:
                        self._json_response(401, {"error": "Not authenticated"})
                        return
                    actor = fetch_user(actor_id)
                    if (not actor or actor.get("status") is not True
                            or actor.get("role") != "admin"):
                        self._json_response(403, {"error": "Admin access required"})
                        return
                    username = (body.get("username") or "").strip()
                    if not username:
                        self._json_response(400, {"error": "Username is required"})
                        return
                    rows = supabase_request(
                        f"users?username=eq.{q(username)}&select=id,username"
                    )
                    if not rows:
                        self._json_response(404, {"error": "No such user"})
                        return
                    user = rows[0]
                    retire_reset_codes(user["id"])
                    code = new_reset_code()
                    expires = datetime.now(timezone.utc) + timedelta(minutes=RESET_CODE_TTL_MINUTES)
                    supabase_request("password_resets", method="POST", body={
                        "code_hash": hash_reset_code(code),
                        "user_id": user["id"],
                        "expires_at": expires.isoformat(),
                    }, extra_headers={"Prefer": "return=representation"})
                    self._json_response(200, {
                        "code": code, "username": user["username"],
                        "expires_in_minutes": RESET_CODE_TTL_MINUTES,
                    })
                # Redeem a code. Signs the user straight in, the same shape
                # login returns, so they aren't bounced to a form they can't fill.
                elif action == "reset_password":
                    username = (body.get("username") or "").strip()
                    code = body.get("code") or ""
                    new_password = body.get("new_password") or ""
                    if not username or not code:
                        self._json_response(400, {"error": "Username and reset code are required"})
                        return
                    if len(new_password) < MIN_PASSWORD_LEN:
                        self._json_response(400, {"error": f"Password must be at least {MIN_PASSWORD_LEN} characters"})
                        return
                    # One filter covers the whole check — right code,
                    # unredeemed, unexpired — so a stale row fails to match.
                    now = datetime.now(timezone.utc).isoformat()
                    rows = supabase_request(
                        f"password_resets?code_hash=eq.{hash_reset_code(code)}"
                        f"&used_at=is.null&expires_at=gt.{q(now)}&select=user_id"
                    )
                    users = supabase_request(
                        f"users?username=eq.{q(username)}&select=id,username,role,status"
                    ) if rows else []
                    # The code must belong to the account being named, so a code
                    # issued for one user can't be spent on another.
                    if not rows or not users or users[0]["id"] != rows[0]["user_id"]:
                        self._json_response(400, {"error": "That reset code is invalid or has expired"})
                        return
                    user = users[0]
                    if user.get("status") is not True:
                        self._json_response(403, {"error": "Account is inactive"})
                        return
                    set_password(user["id"], new_password)   # also burns the code
                    self._json_response(200, {
                        "user_id": user["id"], "username": user["username"],
                        "role": user["role"],
                    })
                else:
                    self._json_response(400, {"error": "Unknown action"})
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
        elif self.path.startswith("/api/bun-notes"):
            api = bun_notes_api()
            user_id, is_admin, err = resolve_notes_actor(self.headers)
            if err:
                self._json_response(*err)
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length)) if length else {}
            except Exception:
                self._json_response(400, {"error": "Body must be JSON"})
                return
            notes = body.get("notes") if isinstance(body, dict) and "notes" in body else [body]
            if not isinstance(notes, list) or not notes:
                self._json_response(400, {"error": "No notes in the request"})
                return
            if len(notes) > api.MAX_BATCH:
                self._json_response(400, {"error": f"At most {api.MAX_BATCH} notes per request"})
                return
            ids = []
            for note in notes:
                note_id, error = api.note_id_of(note)
                if error:
                    self._json_response(400, {"error": error})
                    return
                ids.append(note_id)
            try:
                authors = api.fetch_authors(ids)
            except Exception as e:
                self._json_response(500, {"error": str(e)})
                return
            rows = []
            for note, note_id in zip(notes, ids):
                refused = api.may_write(authors, note_id, user_id, is_admin)
                if refused:
                    self._json_response(403, {"error": refused})
                    return
                # An existing note keeps the author it was filed under; a new
                # one is owned by whoever is writing it.
                row, error = api.normalize(note, authors.get(note_id, user_id))
                if error:
                    self._json_response(400, {"error": error})
                    return
                rows.append(row)
            try:
                supabase_request(
                    "bun_notes?on_conflict=id",
                    method="POST", body=rows,
                    extra_headers={"Prefer": "resolution=merge-duplicates,return=representation"},
                )
                self._json_response(200, {"ok": True, "notes": [r["data"] for r in rows]})
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
        if self.path.startswith("/api/bun-notes"):
            api = bun_notes_api()
            user_id, is_admin, err = resolve_notes_actor(self.headers)
            if err:
                self._json_response(*err)
                return
            params = parse_qs(urlparse(self.path).query)
            note_id = (params.get("id", [None])[0] or "").strip()
            if not note_id:
                self._json_response(400, {"error": "id parameter is required"})
                return
            if not api.NOTE_ID.match(note_id):
                self._json_response(400, {"error": f"invalid note id {note_id!r}"})
                return
            try:
                # An id that matches nothing stays a 200 no-op, as it always was.
                refused = api.may_write(
                    api.fetch_authors([note_id]), note_id, user_id, is_admin)
            except Exception as e:
                self._json_response(500, {"error": str(e)})
                return
            if refused:
                self._json_response(403, {"error": refused})
                return
            try:
                supabase_request(
                    "bun_notes?id=eq." + urllib.request.quote(note_id),
                    method="DELETE",
                    extra_headers={"Prefer": "return=representation"},
                )
                self._json_response(200, {"ok": True})
            except Exception as e:
                self._json_response(500, {"error": str(e)})
        elif self.path.startswith("/api/bets"):
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
        # send_error() routes through here with an HTTPStatus as args[0], not a
        # string, so coerce before the substring test — otherwise every 404 in
        # local dev raises inside the logger and resets the connection.
        if "/api/" in str(args[0] if args else ""):
            super().log_message(format, *args)


if __name__ == "__main__":
    print(f"Starting server at http://localhost:{PORT}")
    with http.server.HTTPServer(("", PORT), Handler) as httpd:
        httpd.serve_forever()
