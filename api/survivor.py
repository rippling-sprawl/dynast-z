"""/api/survivor -- the week board for the Survivor pool.

GET /api/survivor?season=2026&week=3
    The week's games, your pick, the teams you have already spent, where your
    entry stands, and every other entry's pick *for the games that have already
    kicked off*. Any signed-in account; not status-gated, because a deactivated
    account can still see how far it got.

PUT /api/survivor
    Set or clear your pick for one week. Body is
    {season, week, game_id, team} to set, or {season, week, team: null} to
    clear. Requires an active account, and an entry that is still alive.

ONE READ SERVES THE WHOLE PAGE

Unlike the Pick 'Em board, this reads the season narrow (store.load_season_games)
rather than the week wide, and slices the week out of it in Python. Survivor
does not grade against the frozen line, so it needs none of the jsonb the wide
read carries -- and it *does* need the rest of the season, because the used-team
rule and the elimination walk are both season-long. Two reads of the board would
be one more than the page can be built from.

The line still comes back on the row and is still shown, greyed. It is not what
anything is graded on here, and it is the single best answer to the only
question the page is really asking.

THE LOCK

Each game locks at its own kickoff and the server's clock is the only one that
counts -- the same rule the Pick 'Em runs, and for the same reason. Two halves:

  read   -- api/_survivor/store.load_visible_picks() builds the filter out of
            games whose kickoff has passed, so another entry's unkicked pick is
            never selected and cannot be leaked by a later change to the
            response shape.
  write  -- a pick may be set, changed or cleared right up until the game it
            names kicks off, and not one second after. A pick already made on a
            game that has started is immovable, which is what makes the reveal
            safe: what everyone sees is final.

WHY A GAME WITH NO LINE IS STILL PICKABLE HERE

The Pick 'Em drops a game whose line never froze, because there is nothing to
grade it against. Survivor grades on the score, so such a game is on this board
like any other. That difference is the reason `n` does not appear in this
payload at all: every game in the week is pickable, always.

Storage is Supabase `survivor_picks` over the shared `pickem_games` board; see
scripts/sql/survivor_picks.sql for the schema and the two indexes that ARE the
rules, and scripts/pickem_capture.py for the job that fills the board and
writes the scores back.
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import sys
import urllib.parse

# Co-located under api/ rather than imported from scripts/: Vercel does not
# bundle scripts/** with a function. The path insert is __file__-relative and
# stays inside api/, so it resolves whatever the runtime sets as the working
# directory. Same preamble as api/pickem.py.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _survivor import rules, store  # noqa: E402


def parse_int(params, key, lo, hi):
    """-> (value, error). Absent is (None, None): the caller picks a default."""
    raw = (params.get(key) or [""])[0].strip()
    if not raw:
        return None, None
    try:
        value = int(raw)
    except ValueError:
        return None, f"{key} must be a number"
    if not lo <= value <= hi:
        return None, f"{key} must be between {lo} and {hi}"
    return value, None


def wire_game(game):
    """One board row as the page sees it. kickoff_ts is a datetime and internal
    to the lock decision; it must not reach the wire, where it would neither
    serialise nor mean anything."""
    return {k: v for k, v in game.items()
            if not k.startswith("_") and k != "kickoff_ts"}


def build_week(user_id, season, week, now, games=None):
    """The GET payload. Split out of the handler so server.py's dev mirror runs
    the identical function rather than a second implementation of it."""
    season_games = games if games is not None else store.load_season_games(season, now)
    by_week = store.group_by_week(season_games)
    board_weeks = sorted(by_week)
    slate = sorted(by_week.get(week, []), key=lambda g: (g["kickoff"] or "", g["game_id"]))
    by_id = {g["game_id"]: g for g in season_games}
    shut = rules.closed_weeks(season_games)

    mine = store.load_my_picks(user_id, season)
    entry = rules.walk_entry(mine, by_id, board_weeks, shut)

    # Everyone else's revealed picks. Read season-wide in one request because
    # the pool summary below needs the whole season anyway -- walking a partial
    # history would report an entry as alive when week 4 already killed it.
    revealed = store.load_visible_picks(season, season_games, exclude=user_id)
    usernames = store.load_usernames()

    by_user = {}
    for row in revealed:
        by_user.setdefault(row["user_id"], {})[row["week"]] = row

    # The rest of the field, as teamless picks. Same read and same reasoning as
    # api/survivor-standings.py: an entry is not a secret, its pick is, and
    # store.load_entry_weeks() names the weeks without reading the teams. What
    # this buys here is only the count -- the hub's Entries tile said 1 while the
    # pool card beside it listed seven names, because an entry whose every pick
    # was still unreadable was dropped rather than counted.
    #
    # It cannot leak into the board itself: chips() keys a name to a game by
    # game_id, and these rows have none, so a masked pick attaches to nothing.
    # That is the right outcome as well as the accidental one -- naming the field
    # is fine, naming which of sixteen games each of them took is not.
    for uid, weeks in store.load_entry_weeks(season).items():
        if uid == user_id:
            continue
        picks = by_user.setdefault(uid, {})
        for wk in weeks:
            if wk not in picks:
                picks[wk] = {"week": wk, "game_id": None, "team": None}

    # WHY THE VISIBLE SET IS ENOUGH TO SETTLE WHO IS ALIVE
    #
    # An entry's status turns on graded weeks only, and a graded week is a week
    # whose games have kicked off -- so every pick that could change the answer
    # is one this request is already allowed to see. A pick that is still hidden
    # sits on a game that has not started, which walk_entry() would stop at
    # anyway. Filtering for secrecy therefore costs the standings nothing, which
    # is the property that lets this endpoint be honest and complete at once.
    #
    # The masked picks above do not disturb that. A pick is unreadable only while
    # its game is unstarted, so walk_entry() grades one PENDING and stops -- the
    # same place it stopped when the pick was absent entirely. They change the
    # count and nobody's status.
    others, alive = [], 0
    for uid, picks in by_user.items():
        if uid not in usernames:
            continue
        state = rules.walk_entry(picks, by_id, board_weeks, shut)
        if not state["entered"]:
            continue
        if state["status"] == rules.ALIVE:
            alive += 1
        pick = picks.get(week)
        others.append({
            "user_id": uid,
            "username": usernames[uid],
            "status": state["status"],
            "out_week": state["out_week"],
            "team": pick["team"] if pick else None,
            "game_id": pick["game_id"] if pick else None,
        })
    others.sort(key=lambda r: (r["username"] or "").lower())

    entries = len(others) + (1 if entry["entered"] else 0)
    if entry["entered"] and entry["status"] == rules.ALIVE:
        alive += 1

    return {
        "season": season,
        "week": week,
        "now": store.iso(now),
        "weeks": board_weeks,
        "games": [wire_game(g) for g in slate],
        # This week's own pick, lifted out of the entry for the page's
        # convenience -- it is the one thing the board is a control for.
        "pick": mine.get(week),
        # abbreviation -> the week it was spent in. The page greys these out;
        # the server refuses them again in rules.validate_pick, and the unique
        # index refuses them a third time.
        "used": {p["team"]: p["week"] for p in mine.values()},
        "entry": entry,
        "others": others,
        "pool": {"entries": entries, "alive": alive, "out": entries - alive},
    }


def resolve_week(season, week, now, games):
    """-> (week, board_weeks). A missing week resolves to the current one: the
    first with a game still to kick off, so a slate stays current while it is
    being played."""
    index = store.group_by_week(games)
    if week is None:
        week = store.current_week(index, now)
    return week, sorted(index)


def apply_pick(user_id, season, week, game_id, team, now):
    """The PUT. -> (body, status). Shared with server.py's mirror.

    `team` of None clears the week. Everything else is a set, and a set that
    names the team already down for the week is idempotent rather than an error
    -- two tabs and a slow network should not produce a rejection.
    """
    season_games = store.load_season_games(season, now)
    by_week = store.group_by_week(season_games)
    slate = by_week.get(week) or []
    if not slate:
        return {"error": f"week {week} of {season} is not on the board yet"}, 400

    by_id = {g["game_id"]: g for g in season_games}
    mine = store.load_my_picks(user_id, season)
    current = mine.get(week)

    # AN ELIMINATED ENTRY MAY STILL PICK
    #
    # This used to 409. It no longer does, and the reason is that the refusal was
    # never protecting anything: rules.walk_entry() stops at the week the entry
    # died, so a pick after it is already scored VOID and already changes no
    # status, no `survived` and no rank. The 409 bought nothing and cost the
    # thing the pool is actually short of in November -- a reason for the people
    # already out to keep opening the page.
    #
    # What still holds, and must:
    #   * The lock, below. A kicked-off game is immovable for everyone.
    #   * The reuse rule, in validate_pick(). Not a policy choice -- the unique
    #     index on (user_id, season, team) is real for eliminated entries too, so
    #     relaxing it here would trade a sentence for a 23505.
    #   * One pick per week, by the primary key.
    # Only the "you are out, go away" branch is gone.

    # A pick whose game has kicked off is immovable -- that is the whole point
    # of the lock, and it is what makes the reveal safe. Both directions:
    # changing it and clearing it are the same retro-edit.
    if current:
        held = by_id.get(current["game_id"])
        if held and held.get("locked"):
            return {"error": f"{current['team']} has already kicked off, so your "
                             f"week {week} pick is final",
                    "locked": current["game_id"]}, 409

    if team is None:
        if current:
            store.clear_pick(user_id, season, week)
        return {"ok": True, "season": season, "week": week, "pick": None}, 200

    week_games = {g["game_id"]: g for g in slate}
    used = {p["team"]: p["week"] for p in mine.values() if p["week"] != week}
    clean, error = rules.validate_pick(game_id, team, week_games, used, current)
    if error:
        return {"error": error}, 400

    store.save_pick(user_id, season, week, clean["game_id"], clean["team"])
    return {"ok": True, "season": season, "week": week,
            "pick": {"week": week, "game_id": clean["game_id"],
                     "team": clean["team"]}}, 200


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        user_id, err = store.resolve_actor(self.headers.get("X-User-Id"),
                                           require_active=False)
        if err:
            self._json(*err)
            return

        now = store.now_utc()
        season, error = parse_int(params, "season", 2000, 2100)
        if not error:
            week, error = parse_int(params, "week", store.MIN_WEEK, store.MAX_WEEK)
        if error:
            self._json(400, {"error": error})
            return

        try:
            season = season or store.current_season(now)
            games = store.load_season_games(season, now)
            week, _ = resolve_week(season, week, now, games)
            self._json(200, build_week(user_id, season, week, now, games))
        except Exception as e:  # noqa: BLE001
            self._json(500, {"error": str(e)})

    def do_PUT(self):
        user_id, err = store.resolve_actor(self.headers.get("X-User-Id"),
                                           require_active=True)
        if err:
            self._json(*err)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
        except Exception:  # noqa: BLE001
            self._json(400, {"error": "Body must be JSON"})
            return
        if not isinstance(body, dict):
            self._json(400, {"error": "Body must be an object"})
            return

        now = store.now_utc()
        season = body.get("season") or store.current_season(now)
        week = body.get("week")
        if not isinstance(season, int) or not isinstance(week, int) \
                or not store.MIN_WEEK <= week <= store.MAX_WEEK:
            self._json(400, {"error": "season and week are required"})
            return

        try:
            payload, status = apply_pick(user_id, season, week,
                                         body.get("game_id"), body.get("team"), now)
            self._json(status, payload)
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
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-User-Id")
        self.end_headers()
