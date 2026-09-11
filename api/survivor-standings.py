"""/api/survivor-standings -- who is still alive, and what everyone has spent.

GET /api/survivor-standings?season=2026
    Every entry, ranked, with one cell per week naming the team it rode --
    for the weeks whose games have already kicked off. Any signed-in account;
    not status-gated, the same as the week board's read.

UNLIKE THE PICK 'EM STANDINGS, THIS DOES CARRY PICKS

api/pickem-standings.py carries points and never a pick, and says so loudly,
because a total is safe at any lock state and a pick is not. This endpoint is
the opposite by design: a survivor table whose cells are blank is not a
standings page, and "who did you have?" is the entire content of the thing. So
it takes on the whole visibility rule instead of avoiding it --
store.load_visible_picks() filters by kickoff in the *query*, so a pick that
must stay hidden is never selected at all.

The one exception is the requester's own row, which is read in full through
store.load_my_picks(). You can always see what you picked; the cells that
nobody else can see yet are flagged `hidden` so the page can say so.

WHAT IS SECRET IS THE PICK, NOT THE PLAYER

A pick is two facts -- that you picked, and what you picked -- and only the
second is a secret worth keeping. The first cannot be kept anyway: the rules
require a pick every week from everyone still alive, so the field is common
knowledge from the moment the pool exists. Withholding it does not protect
anybody, it just makes the page wrong about the size of the pool -- which is
what it was, until store.load_entry_weeks() (`select=user_id,week`, no team, no
game_id) started giving every entry a row. The weeks it names but may not read
carry a teamless cell flagged `masked`, so the table can show that a pick is in
without showing what it is.

WHY THE FILTER COSTS THE STANDINGS NOTHING

An entry's fate turns only on weeks that have been played, and a week that has
been played has kicked off -- so every pick that could change who is alive is
one this request is already allowed to see. The hidden picks all sit on games
that have not started, which rules.walk_entry() stops at regardless. The
visible set is therefore not an approximation of the standings: it is the
standings, exactly.

Its own file rather than a branch of api/survivor.py for the reason
api/pickem-standings.py gives: the two endpoints' warm instances should not
share a memo, since the board is read constantly during a slate and the
standings between them.
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import sys
import urllib.parse

# See the note in api/survivor.py: scripts/** is not bundled with a function, so
# everything shared lives under api/.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _survivor import rules, store  # noqa: E402


def build_standings(user_id, season, now):
    """The whole payload. Four reads plus the roster, then the walk.

    Shared with server.py's dev mirror so the two runtimes cannot disagree about
    who is still in the pool.
    """
    games = store.load_season_games(season, now)
    by_id = {g["game_id"]: g for g in games}
    board_weeks = sorted(store.group_by_week(games))
    shut = rules.closed_weeks(games)

    revealed = store.load_visible_picks(season, games)
    usernames = store.load_usernames()

    by_user = {}
    for row in revealed:
        if row["user_id"] in usernames:
            by_user.setdefault(row["user_id"], {})[row["week"]] = row

    # The requester's own row, in full. `hidden` is what the page prints beside
    # a cell only they can see -- without it a player looking at their own live
    # pick has no way to tell it is still secret. Read before the masking below
    # so `hidden` is decided against what was actually revealed, not against a
    # placeholder this function put there itself.
    hidden = set()
    if user_id in usernames:
        for week, pick in store.load_my_picks(user_id, season).items():
            own = by_user.setdefault(user_id, {})
            if week not in own:
                hidden.add(week)
            own[week] = dict(pick, user_id=user_id)

    # The rest of the field. Every entry gets a row even when nothing it has
    # picked may be shown yet, because "who is in the pool" is not the secret --
    # the secret is what they picked, and store.load_entry_weeks() reads the week
    # numbers without reading the teams. A week with a pick nobody may read gets
    # a teamless placeholder, flagged `masked` for the page and graded PENDING by
    # the walk, which is where the walk would have stopped anyway.
    #
    # Before this the standings withheld the entry along with the pick, so week 1
    # read as a one-entry pool to all seven of its players until the first
    # kickoff that happened to be picked.
    masked = {}
    for uid, weeks in store.load_entry_weeks(season).items():
        if uid not in usernames:
            continue
        own = by_user.setdefault(uid, {})
        for week in weeks:
            if week not in own:
                masked.setdefault(uid, set()).add(week)
                own[week] = {"week": week, "game_id": None, "team": None,
                             "user_id": uid}

    rows = []
    for uid, picks in by_user.items():
        state = rules.walk_entry(picks, by_id, board_weeks, shut)
        if not state["entered"]:
            continue
        rows.append({
            "user_id": uid,
            "username": usernames[uid],
            "status": state["status"],
            "out_week": state["out_week"],
            "out_reason": state["out_reason"],
            "entered": state["entered"],
            "survived": state["survived"],
            "teams": state["teams"],
            "weeks": {str(wk): dict(cell,
                                    hidden=(uid == user_id and wk in hidden),
                                    masked=(wk in masked.get(uid, ())))
                      for wk, cell in state["weeks"].items()},
        })
    rules.rank_rows(rows)

    # Only the games somebody's visible pick actually names. A standings cell
    # wants the opponent and the score behind it, and shipping the season's 272
    # rows to label at most eighteen cells a player would be a payload built for
    # the table's convenience rather than for its content.
    named = {c["game_id"] for r in rows for c in r["weeks"].values() if c.get("game_id")}
    alive = sum(1 for r in rows if r["status"] == rules.ALIVE)

    return {
        "season": season,
        "weeks": board_weeks,
        "rows": rows,
        "games": {gid: {k: by_id[gid][k] for k in
                        ("away", "home", "away_score", "home_score",
                         "status", "kickoff", "week")}
                  for gid in sorted(named) if gid in by_id},
        "pool": {"entries": len(rows), "alive": alive, "out": len(rows) - alive},
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
        try:
            season = int(raw_season) if raw_season else store.current_season(now)
        except ValueError:
            self._json(400, {"error": "season must be a number"})
            return
        if not 2000 <= season <= 2100:
            self._json(400, {"error": "season is out of range"})
            return

        try:
            self._json(200, build_standings(user_id, season, now))
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
