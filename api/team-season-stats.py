"""/api/team-season-stats -- every team's season totals, for and against.

GET /api/team-season-stats[?season=2026]
    -> {"season", "source", "fetched_at", "teams": [{"abbr", "team", "conf",
        "div", "gp", "pf", "pa", "yf", "ya"}, ...], "updated_at"}

Totals, not per-game rates; the page divides by `gp`. Public, because the page
it feeds is.

Nothing is computed here. The row is written weekly by
scripts/fetch_team_stats.py from balldontlie and stored one row per season in
`team_season_stats` (scripts/sql/team_season_stats.sql), so this is a single
primary-key read.
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import sys
import re
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _http import send_json  # noqa: E402

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# Validated before it reaches a PostgREST filter.
SEASON_RE = re.compile(r"^[0-9]{4}$")


def supabase_request(path):
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    req = urllib.request.Request(url)
    req.add_header("apikey", SUPABASE_KEY)
    req.add_header("Authorization", f"Bearer {SUPABASE_KEY}")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        if "PGRST205" in detail:
            raise RuntimeError(
                "the team_season_stats table does not exist -- run "
                "scripts/sql/team_season_stats.sql in the Supabase SQL editor") from None
        raise RuntimeError(f"supabase {e.code}: {detail}") from None
    return json.loads(raw) if raw else None


def load_season(season):
    """-> the stored payload for that season, or None when it has not been
    fetched. With no season given, the newest season stored."""
    where = f"&season=eq.{season}" if season else ""
    rows = supabase_request(
        f"team_season_stats?select=season,data,updated_at{where}"
        "&order=season.desc&limit=1")
    if not rows:
        return None
    payload = dict(rows[0].get("data") or {})
    payload["updated_at"] = rows[0].get("updated_at")
    return payload


def parse(params):
    """-> (season | None, error | None)."""
    season = (params.get("season") or [""])[0].strip()
    if season and not SEASON_RE.match(season):
        return None, "season must be a year"
    return (int(season) if season else None), None


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        season, error = parse(params)
        if error:
            self._json(400, {"error": error})
            return
        try:
            payload = load_season(season)
        except Exception as e:  # noqa: BLE001
            self._json(500, {"error": str(e)})
            return
        if payload is None:
            self._json(404, {"error": "no team stats stored for that season"})
            return
        self._json(200, payload)

    def _json(self, status, data):
        send_json(self, status, data, {"Access-Control-Allow-Origin": "*"})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
