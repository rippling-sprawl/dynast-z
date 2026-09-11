"""/api/pickem -- the week board for the confidence Pick 'Em.

GET /api/pickem?season=2026&week=3
    The week's games with their frozen spreads and lock state, your picks, and
    every other player's picks *for the games that have already kicked off*.
    Any signed-in account; not status-gated, because a deactivated account can
    still see where it finished.

PUT /api/pickem
    Replace your picks for one week. The body is the complete intended set:
    a game you leave out is a game you un-picked. Requires an active account.

WHY A WHOLE WEEK PER REQUEST RATHER THAN ONE PICK AT A TIME

The confidences are a permutation -- 1..k with no gaps and no repeats across
whatever you picked -- so no single pick is valid or invalid on its own.
Changing one side changes the constraint every other pick is checked against.
Submitting the week as a unit is the only way the server can enforce that rule
at all, and it makes an interrupted save leave the week as it was rather than
halfway through a swap.

THE LOCK

Each game locks at its own kickoff, ESPN-style, and the server's clock is the
only one that counts. Two halves:

  read   -- api/_pickem/store.load_visible_others() filters by kickoff in the
            *query*, so an unkicked pick belonging to somebody else is never
            selected, never in memory, and cannot be leaked by a later change
            to the response shape.
  write  -- a submitted week must reproduce every already-kicked-off pick
            exactly. Adding one, changing one or dropping one is a 409. Games
            that have not kicked off are freely editable in the same request,
            which is what lets you re-save on Sunday after the Thursday game.

Storage is Supabase `pickem_games` + `pickem_picks`; see scripts/sql/pickem_*.sql
for the schemas and scripts/pickem_capture.py for what fills the board.
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import sys
import urllib.parse

# Co-located under api/ rather than imported from scripts/: Vercel does not
# bundle scripts/** with a function, which is why /api/odds-ingest is dead in
# production (ARCHITECTURE.md). The path insert is __file__-relative and stays
# inside api/, so it resolves whatever the runtime sets as the working directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _pickem import scoring, store  # noqa: E402


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


def build_week(user_id, season, week, now):
    """The GET payload. Split out of the handler so server.py's dev mirror runs
    the identical function rather than a second implementation of it."""
    games = store.load_games(season, week, now)
    mine_raw = store.load_my_picks(user_id, season, week)
    others_raw = store.load_visible_others(season, week, games, user_id)

    by_id = {g["game_id"]: g for g in games}
    # `n` is how many games are pickable at all, which is what the page prints
    # as the ceiling. A game whose line never froze is not one of them: it would
    # have no spread to grade against, so it is off the board rather than
    # silently graded by a different rule than everything beside it.
    n = sum(1 for g in games if g["spread_home"] is not None)

    mine = {}
    for game_id, data in mine_raw.items():
        game = by_id.get(game_id)
        if not game:
            continue
        pick, confidence = data.get("pick"), data.get("confidence")
        mine[game_id] = dict({"pick": pick, "confidence": confidence},
                             **scoring.score_pick(pick, confidence, game))

    usernames = store.load_usernames() if others_raw else {}
    grouped = {}
    for row in others_raw:
        uid = row["user_id"]
        game = by_id.get(str(row["game_id"]))
        data = row.get("data") or {}
        if not game:
            continue
        pick, confidence = data.get("pick"), data.get("confidence")
        entry = grouped.setdefault(uid, {"user_id": uid,
                                         "username": usernames.get(uid, ""),
                                         "picks": {}})
        entry["picks"][str(row["game_id"])] = dict(
            {"pick": pick, "confidence": confidence},
            **scoring.score_pick(pick, confidence, game))

    others = sorted(grouped.values(), key=lambda r: (r["username"] or "").lower())
    totals = {
        "mine": scoring.score_set(
            ((gid, p["pick"], p["confidence"]) for gid, p in mine.items()), by_id),
        "byUser": {r["user_id"]: scoring.score_set(
            ((gid, p["pick"], p["confidence"]) for gid, p in r["picks"].items()), by_id)
            for r in others},
    }

    # When this week was last saved. Every pick row carries the instant it was
    # written (store.save_week_picks stamps it), so the newest of them is the
    # answer -- and it survives a reload, which a stamp held only in the page
    # would not. The strings are all iso/UTC/second-precision from one writer,
    # so max() on them is a real comparison rather than a lucky one.
    written = [d.get("updatedAt") for d in mine_raw.values() if d.get("updatedAt")]

    stamps = [g for g in games if g.get("_deadline")]
    return {
        "season": season,
        "week": week,
        "now": store.iso(now),
        "deadline_at": stamps[0]["_deadline"] if stamps else None,
        "frozen_at": stamps[0]["_frozen"] if stamps else None,
        "n": n,
        "saved_at": max(written) if written else None,
        # kickoff_ts is a datetime and internal to the lock decision; it must not
        # reach the wire, where it would neither serialise nor mean anything.
        "games": [{k: v for k, v in g.items()
                   if not k.startswith("_") and k != "kickoff_ts"} for g in games],
        "mine": mine,
        "others": others,
        "totals": totals,
    }


def resolve_week(season, week, now):
    """-> (season, week, weeks). A missing week resolves to the current one,
    which costs one narrow read of the season's kickoffs."""
    index = store.group_by_week(store.load_season_games(season, now))
    weeks = sorted(index)
    if week is None:
        week = store.current_week(index, now)
    return season, week, weeks


def apply_week_picks(user_id, season, week, picks, now):
    """The PUT. -> (body, status). Shared with server.py's mirror."""
    games = store.load_games(season, week, now)
    pickable = {g["game_id"]: g for g in games if g["spread_home"] is not None}
    if not games:
        return {"error": f"week {week} of {season} has no games on the board yet"}, 400

    clean, error = scoring.validate_week_picks(picks, pickable)
    if error:
        return {"error": error}, 400

    # The lock, checked against what is stored rather than against what the
    # client says is stored. A game that has kicked off must appear in the
    # submission with exactly the pick and confidence it already has: adding,
    # changing and omitting are all the same kind of retro-edit, so all three
    # are refused together.
    stored = store.load_my_picks(user_id, season, week)
    submitted = {p["game_id"]: p for p in clean}
    locked_ids = {g["game_id"] for g in games if g["locked"]}
    violations = []
    for game_id in sorted(locked_ids):
        was = stored.get(game_id)
        now_pick = submitted.get(game_id)
        if was is None and now_pick is None:
            continue                                    # never picked, still not
        if was is None or now_pick is None \
                or now_pick["pick"] != was.get("pick") \
                or now_pick["confidence"] != was.get("confidence"):
            violations.append(game_id)
    if violations:
        return {"error": "those games have already kicked off and cannot be changed",
                "locked": violations}, 409

    store.save_week_picks(user_id, season, week, clean)
    return {"ok": True, "season": season, "week": week, "count": len(clean)}, 200


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
        if error:
            self._json(400, {"error": error})
            return
        week, error = parse_int(params, "week", store.MIN_WEEK, store.MAX_WEEK)
        if error:
            self._json(400, {"error": error})
            return

        try:
            season = season or store.current_season(now)
            season, week, weeks = resolve_week(season, week, now)
            payload = build_week(user_id, season, week, now)
            payload["weeks"] = weeks
            self._json(200, payload)
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
            payload, status = apply_week_picks(
                user_id, season, week, body.get("picks"), now)
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
