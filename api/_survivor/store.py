"""Supabase reads and writes for the Survivor pool, and the visibility rule that
decides which of them a request is allowed to see.

The board is pickem_games and it is read through api/_pickem/store.py -- not
copied, imported. "Has this game kicked off?" has exactly one implementation in
this app and both games consult it. What lives here is the survivor_picks table
and nothing else.

THE ONE RULE THAT MATTERS, RESTATED

A pick is secret until its game kicks off. Enforced by not selecting it: the
reveal filter is built out of games whose kickoff has already passed by the
server's clock, so a pick that must stay hidden never enters a Python object at
all. Loading the season and filtering afterwards would work today and break the
first time somebody adds a field to the response.

The filter is expressed in two halves for a reason worth writing down. A week
where every game has kicked off is fully visible, and naming it by week is one
short clause; a week still in progress needs its games named individually. Over
a full season the whole-week half absorbs seventeen weeks and the per-game half
never holds more than one slate, so the URL stays short instead of growing a
272-id `in.()` list by December.
"""
import os
import sys

# api/ is already on sys.path when a handler imports this -- api/survivor.py
# inserts it before importing _survivor, the same __file__-relative insert
# api/pickem.py makes. Repeated here so the module is importable on its own,
# which is what lets scripts and tests load it directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _pickem import store as board  # noqa: E402

# Re-exported so callers have one import for the whole data layer rather than
# reaching into _pickem for half of it. These ARE _pickem's -- same functions,
# not copies -- which is the point.
MIN_WEEK, MAX_WEEK = board.MIN_WEEK, board.MAX_WEEK
now_utc = board.now_utc
iso = board.iso
current_season = board.current_season
current_week = board.current_week
group_by_week = board.group_by_week
load_usernames = board.load_usernames
resolve_actor = board.resolve_actor
# Deliberately NOT re-exported: board.load_games, the Pick 'Em's wide per-week
# read. Survivor needs none of the jsonb it carries and does need the rest of
# the season anyway, so the season read below serves the whole page. Making the
# wide one reachable from here would invite the second board read this is
# arranged to avoid.
load_season_games = board.load_season_games
q = board.q


# ---- the reveal filter -------------------------------------------------------

def visibility_clause(games):
    """-> a PostgREST filter string selecting only picks that may be shown, or
    None if nothing may be.

    `games` are rows the caller has already read, so `locked` was computed from
    our own kickoff column against the server's clock; no client value reaches
    this decision. The ids and week numbers are ints out of our own table, which
    is what makes them safe to interpolate -- the same reasoning as
    load_visible_others() in api/_pickem/store.py.
    """
    by_week = {}
    for game in games:
        by_week.setdefault(int(game["week"]), []).append(game)

    whole, partial = [], []
    for week, slate in sorted(by_week.items()):
        if all(g.get("locked") for g in slate):
            whole.append(week)
        else:
            partial.extend(int(g["game_id"]) for g in slate if g.get("locked"))

    clauses = []
    if whole:
        clauses.append("week.in.(" + ",".join(str(w) for w in whole) + ")")
    if partial:
        clauses.append("game_id.in.(" + ",".join(str(i) for i in partial) + ")")

    if not clauses:
        # Also avoids `in.()`, which PostgREST rejects as a syntax error rather
        # than reading as the empty set.
        return None
    if len(clauses) == 1:
        return clauses[0].replace(".in.(", "=in.(", 1)
    return "or=(" + ",".join(clauses) + ")"


# ---- reads -------------------------------------------------------------------

def _shape(row):
    """One survivor_picks row as the rest of the app sees it. game_id becomes a
    string here and stays one for the whole of the JSON side, for the reason
    _shape_game() gives in api/_pickem/store.py: the column is a bigint and
    JavaScript cannot hold one exactly."""
    return {
        "week": int(row["week"]),
        "game_id": str(row["game_id"]),
        "team": row["team"],
    }


def load_my_picks(user_id, season):
    """Every pick this entry has made, the whole season of it. Never filtered by
    kickoff -- you can always see what you picked, and the used-team rule is
    unusable if you cannot.

    -> {week: {week, game_id, team}}
    """
    rows = board.supabase_request(
        f"survivor_picks?user_id=eq.{q(user_id)}&season=eq.{int(season)}"
        f"&select=week,game_id,team&order=week.asc") or []
    return {int(r["week"]): _shape(r) for r in rows}


def load_visible_picks(season, games, exclude=None):
    """Every entry's picks for the season, restricted to games that have already
    kicked off. Optionally excluding one user, for the pick page, which has
    already read its own picks in full and must not have them filtered.

    -> [{user_id, week, game_id, team}]
    """
    clause = visibility_clause(games)
    if clause is None:
        return []
    query = (f"survivor_picks?season=eq.{int(season)}&{clause}"
             f"&select=user_id,week,game_id,team")
    if exclude:
        query += f"&user_id=neq.{q(exclude)}"
    rows = board.supabase_request(query) or []
    return [dict(_shape(r), user_id=r["user_id"]) for r in rows]


# ---- writes ------------------------------------------------------------------

def save_pick(user_id, season, week, game_id, team):
    """Put this entry's pick for one week. Upserts on the (user_id, season,
    week) primary key, so changing a pick replaces it rather than adding one.

    The composite PK is what makes this safe: user_id comes from the
    authenticated header on the row itself, so a forged game_id can only ever
    write under the caller's own account. Same guarantee as bets.sql and
    pickem_picks.sql.
    """
    board.supabase_request(
        "survivor_picks?on_conflict=user_id,season,week",
        method="POST",
        body=[{
            "user_id": user_id,
            "season": int(season),
            "week": int(week),
            "game_id": int(game_id),
            "team": team,
            "updated_at": "now()",
        }],
        headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
    )


def clear_pick(user_id, season, week):
    """Take this entry's pick for one week back off the board. Only reachable
    while the picked game is still unlocked -- api/survivor.py checks that -- so
    this cannot be used to un-make a pick that has already been revealed."""
    board.supabase_request(
        f"survivor_picks?user_id=eq.{q(user_id)}&season=eq.{int(season)}"
        f"&week=eq.{int(week)}",
        method="DELETE", headers={"Prefer": "return=minimal"})
