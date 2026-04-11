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
import os
import re
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

KTC_URL = "https://keeptradecut.com/dynasty-rankings"
FANTASYCALC_URL = "https://api.fantasycalc.com/values/current?isDynasty=true&numQbs=2&numTeams=12&ppr=1"
SLEEPER_API = "https://api.sleeper.app/v1"
SLEEPER_PLAYERS_TTL = 86400  # 24 hours for the big players file
LEAGUE_DATA_TTL = 3600  # 1 hour for league rosters/users
FP_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "fp.json")
MASTERS_SCORES_URL = "https://www.masters.com/en_US/scores/feeds/2026/scores.json"
MASTERS_SCORES_TTL = 300  # 5 minutes

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


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


def fetch_masters_scores():
    cached = read_cache("masters_scores.json", ttl=MASTERS_SCORES_TTL)
    if cached is not None:
        print("Using cached Masters scores")
        return cached
    print("Fetching fresh Masters scores...")
    data = json.loads(http_fetch(MASTERS_SCORES_URL))
    write_cache("masters_scores.json", data)
    print("Masters scores complete.")
    return data


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
    return players


def compute_z_scores(players_dict):
    """Convert raw values to z-scores for a single source's player dict."""
    values = [p["value"] for p in players_dict.values()]
    if len(values) < 2:
        return {name: 0.0 for name in players_dict}
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    std = variance ** 0.5
    if std == 0:
        return {name: 0.0 for name in players_dict}
    return {name: (p["value"] - mean) / std for name, p in players_dict.items()}


def fetch_sleeper_players():
    """Fetch the full Sleeper player database (~5MB). Cached for 24 hours."""
    cached = read_cache("sleeper_players.json")
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
    """Fetch traded picks and draft order for a league. Cached with league data."""
    cache_name = f"picks_{league_id}.json"
    cached = read_cache(cache_name, ttl=LEAGUE_DATA_TTL)
    if cached is not None:
        return cached["traded_picks"], cached.get("draft_order")
    traded_picks = json.loads(http_fetch(f"{SLEEPER_API}/league/{league_id}/traded_picks"))
    drafts = json.loads(http_fetch(f"{SLEEPER_API}/league/{league_id}/drafts"))
    draft_order = drafts[0].get("draft_order") if drafts else None
    write_cache(cache_name, {"traded_picks": traded_picks, "draft_order": draft_order})
    return traded_picks, draft_order


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


def build_picks_for_roster(roster_id, rosters, users, league, traded_picks, draft_order, z_lookup):
    """Compute all draft picks owned by a roster and return as player-like dicts."""
    total_rosters = league.get("total_rosters", 12)
    draft_rounds = min(league.get("settings", {}).get("draft_rounds", 4), 4)
    current_season = int(league.get("season", "2026"))
    seasons = sorted({current_season, current_season + 1, current_season + 2}
                     | {int(tp["season"]) for tp in traded_picks})

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


TRANSACTIONS_CACHE_TTL = 600  # 10 minutes
STORE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def read_transaction_store(league_id):
    """Read the persistent transaction store (keyed by transaction_id)."""
    path = os.path.join(STORE_DIR, f"transactions_{league_id}.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return json.load(f)


def write_transaction_store(league_id, store):
    """Write the persistent transaction store."""
    os.makedirs(STORE_DIR, exist_ok=True)
    path = os.path.join(STORE_DIR, f"transactions_{league_id}.json")
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

    # Build z-score lookup from trade calculator data
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
        pass  # z-scores are a bonus, not required

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
        }
        z = z_lookup.get(norm_name(name))
        if z:
            player_data["aggregate"] = z["aggregate"]
            player_data["sources"] = z["sources"]
        players.append(player_data)

    # Add draft picks
    try:
        traded_picks, draft_order = fetch_league_picks(league_id)
        picks = build_picks_for_roster(
            int(roster_id), rosters, users, league, traded_picks, draft_order, z_lookup
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
    # Compute z-scores per source
    z_maps = []
    for label, players_dict in source_pairs:
        z_maps.append((label, players_dict, compute_z_scores(players_dict)))

    # Collect all player names
    all_names = set()
    for _, players_dict, _ in z_maps:
        all_names |= players_dict.keys()

    merged = []
    for name in all_names:
        position = None
        team = None
        sources = {}
        z_scores = []
        for label, players_dict, z_dict in z_maps:
            p = players_dict.get(name)
            if p:
                if position is None:
                    position = p["position"]
                    team = p["team"]
                sources[label] = p["value"]
                z_scores.append(z_dict[name])
        aggregate = round(sum(z_scores) / len(z_scores), 3)
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
        elif self.path.startswith("/api/lookup"):
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            username = params.get("username", [None])[0]
            if not username:
                self._json_response(400, {"error": "username parameter is required"})
                return
            try:
                users = supabase_request(
                    f"users?display_name=eq.{urllib.request.quote(username)}&select=id,display_name"
                )
                if not users:
                    self._json_response(404, {"error": "no username found"})
                    return
                uid = users[0]["id"]
                rows = supabase_request(
                    f"user_data?user_id=eq.{uid}"
                    f"&sport=eq.masters"
                    f"&data_key=eq.3ball"
                    f"&select=data"
                )
                data = rows[0]["data"] if rows else {"rounds": {}}
                self._json_response(200, {"username": users[0]["display_name"], "threeBall": data})
            except Exception as e:
                self._json_response(500, {"error": str(e)})
        elif self.path == "/api/masters/scores":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            if IS_VERCEL:
                self.send_header("Cache-Control", "s-maxage=300, stale-while-revalidate=600")
            self.end_headers()
            try:
                data = fetch_masters_scores()
                self.wfile.write(json.dumps(data).encode())
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        elif self.path == "/account":
            self.path = "/views/account.html"
            super().do_GET()
        elif self.path == "/masters":
            self.path = "/views/masters/index.html"
            super().do_GET()
        elif self.path.startswith("/masters/select-golfers"):
            self.path = "/views/masters/select-golfers.html"
            super().do_GET()
        elif self.path.startswith("/masters/3-ball-results"):
            self.path = "/views/masters/3-ball-results.html"
            super().do_GET()
        elif self.path.startswith("/masters/group-results"):
            self.path = "/views/masters/group-results.html"
            super().do_GET()
        elif re.match(r"/masters/groups$", self.path):
            self.path = "/views/masters/groups.html"
            super().do_GET()
        elif self.path.startswith("/masters/3-ball-lookup"):
            self.path = "/views/masters/3-ball-lookup.html"
            super().do_GET()
        elif re.match(r"/masters/3-ball$", self.path):
            self.path = "/views/masters/3-ball.html"
            super().do_GET()
        elif self.path.startswith("/masters/leaderboard"):
            self.path = "/views/masters/leaderboard.html"
            super().do_GET()
        elif re.match(r"/masters/ev-model", self.path):
            self.path = "/views/masters/ev-model.html"
            super().do_GET()
        elif re.match(r"/league/[^/]+/team/", self.path):
            self.path = "/views/team.html"
            super().do_GET()
        elif re.match(r"/league/[^/]+/new-trades", self.path):
            self.path = "/views/new-trades.html"
            super().do_GET()
        elif re.match(r"/league/[^/]+/scout", self.path):
            self.path = "/views/league-scout.html"
            super().do_GET()
        elif re.match(r"/league/[^/]+/trades", self.path):
            self.path = "/views/league-trades.html"
            super().do_GET()
        elif re.match(r"/league/[^/]+/power", self.path):
            self.path = "/views/league-power.html"
            super().do_GET()
        elif self.path.startswith("/league/"):
            self.path = "/views/league.html"
            super().do_GET()
        elif self.path == "/acknowledgements":
            self.path = "/views/acknowledgements.html"
            super().do_GET()
        elif self.path == "/trade-calculator":
            self.path = "/views/trade-calculator.html"
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
                    display_name = (body.get("display_name") or "").strip()
                    if not display_name:
                        self._json_response(400, {"error": "Display name is required"})
                        return
                    existing = supabase_request(
                        f"users?display_name=eq.{urllib.request.quote(display_name)}&select=id"
                    )
                    if existing:
                        self._json_response(409, {"error": "That name is already taken"})
                        return
                    for _ in range(10):
                        code = "".join(secrets.choice(CODE_CHARS) for _ in range(6))
                        taken = supabase_request(f"users?claim_code=eq.{code}&select=id")
                        if not taken:
                            break
                    result = supabase_request("users", method="POST", body={
                        "display_name": display_name, "claim_code": code,
                    }, extra_headers={"Prefer": "return=representation"})
                    user = result[0]
                    self._json_response(200, {
                        "user_id": user["id"], "display_name": user["display_name"],
                        "claim_code": user["claim_code"],
                    })
                elif action == "login":
                    display_name = (body.get("display_name") or "").strip()
                    claim_code = (body.get("claim_code") or "").strip().upper()
                    if not display_name or not claim_code:
                        self._json_response(400, {"error": "Display name and code are required"})
                        return
                    users = supabase_request(
                        f"users?display_name=eq.{urllib.request.quote(display_name)}"
                        f"&claim_code=eq.{urllib.request.quote(claim_code)}&select=id,display_name,claim_code"
                    )
                    if not users:
                        self._json_response(401, {"error": "Invalid name or code"})
                        return
                    user = users[0]
                    self._json_response(200, {
                        "user_id": user["id"], "display_name": user["display_name"],
                        "claim_code": user["claim_code"],
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
        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-User-Id")
        self.end_headers()

    def _json_response(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-User-Id")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        if "/api/" in (args[0] if args else ""):
            super().log_message(format, *args)


if __name__ == "__main__":
    print(f"Starting server at http://localhost:{PORT}")
    with http.server.HTTPServer(("", PORT), Handler) as httpd:
        httpd.serve_forever()
