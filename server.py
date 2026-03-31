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


def normalize_ktc(raw):
    players = {}
    for p in raw:
        name = p.get("playerName", "")
        sf = p.get("superflexValues", {})
        value = sf.get("value", 0)
        if name and value:
            players[name] = {
                "name": name,
                "position": p.get("position", ""),
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
                "position": p.get("position", ""),
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
        aggregate = round(sum(z_scores) / len(z_scores), 4)
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
