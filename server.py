#!/usr/bin/env python3
"""
Dynast-Z Trade Calculator - Local server that proxies API requests
to avoid CORS issues and serves the frontend.

Usage: python3 server.py
Then open http://localhost:8000
"""

import http.server
import json
import os
import re
import time
import urllib.request

PORT = 8000
IS_VERCEL = os.environ.get("VERCEL") == "1"
CACHE_DIR = "/tmp/dynast-z-cache" if IS_VERCEL else os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
CACHE_TTL = 129600  # 36 hours in seconds

KTC_URL = "https://keeptradecut.com/dynasty-rankings"
FANTASYCALC_URL = "https://api.fantasycalc.com/values/current?isDynasty=true&numQbs=2&numTeams=12&ppr=1"
SLEEPER_API = "https://api.sleeper.app/v1"
SLEEPER_PLAYERS_TTL = 86400  # 24 hours for the big players file
SLEEPER_USERNAME = "baker28"


def read_cache(name):
    path = os.path.join(CACHE_DIR, name)
    if not os.path.exists(path):
        return None
    age = time.time() - os.path.getmtime(path)
    if age > CACHE_TTL:
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
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8")


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
    return data


def fetch_fc():
    cached = read_cache("fc.json")
    if cached is not None:
        print("Using cached FantasyCalc data")
        return cached
    print("Fetching fresh FantasyCalc data...")
    data = json.loads(http_fetch(FANTASYCALC_URL))
    write_cache("fc.json", data)
    return data


def norm_pos(pos):
    return "PICK" if pos == "RDP" else pos


def normalize_ktc(raw):
    players = {}
    for p in raw:
        name = p.get("playerName", "")
        sf = p.get("superflexValues", {})
        value = sf.get("value", 0)
        if name and value:
            players[name] = {
                "name": name,
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
            players[name] = {
                "name": name,
                "position": norm_pos(p.get("position", "")),
                "team": p.get("maybeTeam", ""),
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
    """Fetch rosters and users for a Sleeper league."""
    rosters = json.loads(http_fetch(f"{SLEEPER_API}/league/{league_id}/rosters"))
    users = json.loads(http_fetch(f"{SLEEPER_API}/league/{league_id}/users"))
    league = json.loads(http_fetch(f"{SLEEPER_API}/league/{league_id}"))
    return rosters, users, league


def resolve_sleeper_user_id():
    """Resolve SLEEPER_USERNAME to a user_id."""
    cached = read_cache("sleeper_user.json")
    if cached is not None and cached.get("username") == SLEEPER_USERNAME:
        return cached["user_id"]
    data = json.loads(http_fetch(f"{SLEEPER_API}/user/{SLEEPER_USERNAME}"))
    user_id = data.get("user_id")
    write_cache("sleeper_user.json", {"username": SLEEPER_USERNAME, "user_id": user_id})
    return user_id


def build_my_roster(league_id):
    my_user_id = resolve_sleeper_user_id()
    rosters, users, league = fetch_league_data(league_id)
    sleeper_players = fetch_sleeper_players()

    # Build z-score lookup from trade calculator data
    z_lookup = {}
    try:
        ktc_raw = fetch_ktc()
        fc_raw = fetch_fc()
        ktc = normalize_ktc(ktc_raw)
        fc = normalize_fc(fc_raw)
        for p in merge_players(ktc, fc):
            z_lookup[p["name"]] = p
    except Exception:
        pass  # z-scores are a bonus, not required

    # Find my user info and roster
    my_team_name = None
    for u in users:
        if u.get("user_id") == my_user_id:
            my_team_name = u.get("metadata", {}).get("team_name") or u.get("display_name", SLEEPER_USERNAME)
            break

    my_roster = None
    for roster in rosters:
        if roster.get("owner_id") == my_user_id:
            my_roster = roster
            break
    if not my_roster:
        raise RuntimeError(f"No roster found for user {SLEEPER_USERNAME} in this league")

    player_ids = my_roster.get("players") or []
    starters = set(my_roster.get("starters") or [])

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
        }
        z = z_lookup.get(name)
        if z:
            player_data["aggregate"] = z["aggregate"]
            player_data["sources"] = z["sources"]
        players.append(player_data)

    players.sort(key=lambda p: (
        not p["starter"],
        -(p.get("aggregate") or -999),
        p["name"],
    ))

    return {"league_name": league.get("name", "League"), "team_name": my_team_name, "players": players}


def merge_players(ktc, fc):
    ktc_z = compute_z_scores(ktc)
    fc_z = compute_z_scores(fc)

    all_names = set(ktc.keys()) | set(fc.keys())
    merged = []
    for name in all_names:
        k = ktc.get(name)
        f = fc.get(name)
        position = (k or f)["position"]
        team = (k or f)["team"]
        sources = {}
        z_scores = []
        if k:
            sources["keeptradecut.com"] = k["value"]
            z_scores.append(ktc_z[name])
        if f:
            sources["fantasycalc.com"] = f["value"]
            z_scores.append(fc_z[name])
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
                ktc = normalize_ktc(ktc_raw)
                fc = normalize_fc(fc_raw)
                players = merge_players(ktc, fc)
                self.wfile.write(json.dumps(players).encode())
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        elif self.path.startswith("/api/league/"):
            league_id = self.path.split("/api/league/")[1].split("?")[0]
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            if IS_VERCEL:
                self.send_header("Cache-Control", "s-maxage=3600, stale-while-revalidate=86400")
            self.end_headers()
            try:
                data = build_my_roster(league_id)
                self.wfile.write(json.dumps(data).encode())
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        elif self.path.startswith("/league/"):
            self.path = "/league.html"
            super().do_GET()
        elif self.path == "/trade-calculator":
            self.path = "/trade-calculator.html"
            super().do_GET()
        elif self.path == "/" or self.path == "":
            self.path = "/index.html"
            super().do_GET()
        else:
            super().do_GET()

    def log_message(self, format, *args):
        if "/api/" in (args[0] if args else ""):
            super().log_message(format, *args)


if __name__ == "__main__":
    print(f"Starting server at http://localhost:{PORT}")
    with http.server.HTTPServer(("", PORT), Handler) as httpd:
        httpd.serve_forever()
