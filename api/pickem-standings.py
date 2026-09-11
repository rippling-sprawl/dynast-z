"""/api/pickem-standings -- the Pick 'Em leaderboard.

GET /api/pickem-standings?season=2026[&week=3]
    Every player's season total with a per-week breakdown, ranked. With ?week=
    it collapses to that single week's leaderboard. Any signed-in account; not
    status-gated, the same as the week board's read.

WHY THIS CARRIES POINTS AND NEVER A PICK

The week board has to work out which of somebody else's picks may be shown,
because it shows picks (api/pickem.py). This endpoint does not have that
problem and must not acquire it: a total is safe at any lock state, so the
response shape contains no `pick` field anywhere and there is nothing here for
a kickoff filter to protect. Keep it that way -- the moment a pick appears in
this payload it needs the whole visibility rule and will not have it.

Only graded games count. A Sunday in progress therefore credits nobody early
and reports `pending` instead, which is what stops a leaderboard from
reshuffling every few minutes on numbers that are not final.

Its own file rather than a branch of api/pickem.py so the two endpoints' warm
instances do not share a memo: the week board is read constantly during a slate
and the standings between them, and the smaller one should not keep evicting
the larger.
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import sys
import urllib.parse

# See the note in api/pickem.py: scripts/** is not bundled with a function, so
# everything shared lives under api/.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _pickem import scoring, store  # noqa: E402


def build_standings(season, week, now):
    """The whole payload. Two reads plus the roster, then arithmetic.

    Shared with server.py's dev mirror so the two runtimes cannot disagree
    about how a season is added up.
    """
    games = store.load_season_games(season, now)
    by_id = {g["game_id"]: g for g in games}
    picks = store.load_all_picks(season, week)
    usernames = store.load_usernames()

    # The weeks worth offering as a filter: the ones with a verdict on at least
    # one game. A week that has been picked but not played would otherwise show
    # a column of zeroes that reads as sixteen wrong picks.
    graded_weeks = sorted({g["week"] for g in games if g["result"] is not None})

    players = {}
    for row in picks:
        uid = row["user_id"]
        # A pick belonging to a deleted or deactivated account is dropped rather
        # than rendered as a blank name: `users` is the roster, and someone who
        # is not on it is not in the standings.
        if uid not in usernames:
            continue
        data = row.get("data") or {}
        entry = players.setdefault(uid, {"user_id": uid, "username": usernames[uid],
                                         "picks": [], "byWeekPicks": {}})
        item = (str(row["game_id"]), data.get("pick"), data.get("confidence"))
        entry["picks"].append(item)
        entry["byWeekPicks"].setdefault(row["week"], []).append(item)

    rows = []
    for entry in players.values():
        total = scoring.score_set(entry["picks"], by_id)
        rows.append({
            "user_id": entry["user_id"],
            "username": entry["username"],
            "points": total["points"],
            "correct": total["correct"],
            "picked": total["picked"],
            "pending": total["pending"],
            "byWeek": {str(wk): scoring.score_set(items, by_id)
                       for wk, items in sorted(entry["byWeekPicks"].items())},
        })

    return {
        "season": season,
        "week": week,
        "weeks": graded_weeks,
        "rows": scoring.rank_rows(rows),
        "updated_at": store.iso(now),
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        user_id, err = store.resolve_actor(self.headers.get("X-User-Id"),
                                           require_active=False)
        if err:
            self._json(*err)
            return

        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        now = store.now_utc()

        raw_season = (params.get("season") or [""])[0].strip()
        raw_week = (params.get("week") or [""])[0].strip()
        try:
            season = int(raw_season) if raw_season else store.current_season(now)
            week = int(raw_week) if raw_week else None
        except ValueError:
            self._json(400, {"error": "season and week must be numbers"})
            return
        if not 2000 <= season <= 2100:
            self._json(400, {"error": "season is out of range"})
            return
        if week is not None and not store.MIN_WEEK <= week <= store.MAX_WEEK:
            self._json(400, {"error": f"week must be between {store.MIN_WEEK} "
                                      f"and {store.MAX_WEEK}"})
            return

        try:
            self._json(200, build_standings(season, week, now))
        except Exception as e:  # noqa: BLE001
            self._json(500, {"error": str(e)})

    def _json(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-User-Id")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-User-Id")
        self.end_headers()
