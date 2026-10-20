"""/api/quarter-splits -- one team's points by quarter, game by game.

GET /api/quarter-splits?team=DAL[&season=2026]
    -> {"season", "team", "games": [{"game_id", "week", "postseason",
        "kickoff", "opp", "home", "neutral", "pf", "pa"}, ...],
        "built_at", "updated_at"}

`pf` is what the team scored, `pa` what it allowed, each [q1, q2, q3, q4, ot].
Games are in kickoff order. Public, because the page it feeds is.

Nothing is computed here. The table is built weekly by
scripts/build_quarter_splits.py from the quarter lines in `game_odds` and
stored one row per (season, team) in `quarter_splits`
(scripts/sql/quarter_splits.sql), so this is a single primary-key read.
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

# Validated before either value reaches a PostgREST filter.
TEAM_RE = re.compile(r"^[A-Z]{2,3}$")
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
                "the quarter_splits table does not exist -- run "
                "scripts/sql/quarter_splits.sql in the Supabase SQL editor") from None
        raise RuntimeError(f"supabase {e.code}: {detail}") from None
    return json.loads(raw) if raw else None


def load_team(season, team):
    """-> the stored payload for that team, or None when that season has not
    been built (or the team played no completed game in it). With no season
    given, the newest season stored for the team."""
    where = f"team=eq.{team}" + (f"&season=eq.{season}" if season else "")
    rows = supabase_request(
        f"quarter_splits?select=season,data,updated_at&{where}"
        "&order=season.desc&limit=1")
    if not rows:
        return None
    payload = dict(rows[0].get("data") or {})
    payload["updated_at"] = rows[0].get("updated_at")
    return payload


def parse(params):
    """-> (season | None, team, error | None)."""
    team = (params.get("team") or [""])[0].strip().upper()
    season = (params.get("season") or [""])[0].strip()
    if not TEAM_RE.match(team):
        return None, None, "team must be an abbreviation, e.g. ?team=DAL"
    if season and not SEASON_RE.match(season):
        return None, None, "season must be a year"
    return (int(season) if season else None), team, None


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        season, team, error = parse(params)
        if error:
            self._json(400, {"error": error})
            return
        try:
            payload = load_team(season, team)
        except Exception as e:  # noqa: BLE001
            self._json(500, {"error": str(e)})
            return
        if payload is None:
            self._json(404, {"error": f"no completed games stored for {team}"})
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
