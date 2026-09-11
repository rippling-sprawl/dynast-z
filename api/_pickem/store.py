"""Supabase reads and writes for the Pick 'Em, and the visibility rule that
decides which of them a request is allowed to see.

Service-key PostgREST over urllib, the same shape as every other endpoint in
this app (api/bets.py, api/bun-notes.py). RLS on both tables is enabled and
closed; authorization is enforced here, in Python.

THE ONE RULE THAT MATTERS

A pick is secret until its game kicks off. That is enforced by not selecting it:
load_visible_others() builds an `in.(...)` filter out of the games whose kickoff
has already passed by the server's clock, so a pick that must stay hidden never
enters a Python object at all and cannot be leaked by a later change to the
response shape. Loading everything and filtering afterwards would work today and
break the first time somebody adds a field.
"""
from datetime import datetime, timezone
import json
import os
import urllib.parse
import urllib.request

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# The regular season. Anything outside this is a 400 rather than a query.
MIN_WEEK, MAX_WEEK = 1, 18


def supabase_request(path, method="GET", body=None, headers=None):
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("apikey", SUPABASE_KEY)
    req.add_header("Authorization", f"Bearer {SUPABASE_KEY}")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else None


def q(value):
    """Escape a value for a PostgREST filter. safe="" matters: a uuid is inert
    but a timestamp carries a '+' offset, which survives the default safe list
    and arrives as a space. Same helper as api/auth.py."""
    return urllib.parse.quote(str(value), safe="")


def fetch_user(user_id):
    rows = supabase_request(f"users?id=eq.{q(user_id)}&select=role,status")
    return rows[0] if rows else None


def resolve_actor(user_id, require_active):
    """-> (user_id, error), error being None or a (status, body) pair.

    Reads are authenticated but not status-gated; writes are both. That split is
    the app-wide rule (docs/bets-persistence-supabase.md): a deactivated account
    stops being able to change anything immediately, but can still see where it
    finished.
    """
    if not user_id:
        return None, (401, {"error": "Not authenticated"})
    if require_active:
        user = fetch_user(user_id)
        if not user or user.get("status") is not True:
            return None, (403, {"error": "Account is inactive"})
    return user_id, None


def resolve_reader(user_id):
    """-> (user_id or None, error). The read gate for the pages that are public.

    resolve_actor() above answers "who is this, and may they act". This answers
    "who is this, if anybody" -- the Pick 'Em and Survivor hubs and standings
    are readable signed out, the arrangement /football/bakers-oven already has,
    where the thing can be seen before it is used. A missing X-User-Id is
    therefore an anonymous reader rather than a 401.

    The error half of the tuple is always None. It stays in the signature so a
    handler reads the same whichever gate it calls, and so closing one of these
    reads again is a one-word edit rather than a reshaped branch.

    EVERY ANONYMOUS PAYLOAD GOES THROUGH anonymise() BEFORE IT IS WRITTEN

    That is not a nicety. Both games' reads carry other accounts' usernames --
    which on this site are often email addresses -- and they carry `user_id`,
    which IS the whole of X-User-Id: an id is a credential here, not a label, so
    handing one to the open internet hands over the account. A handler that
    calls this and skips anonymise() is a much worse leak than the 401 it
    replaced.
    """
    return (user_id or None), None


# ---- anonymising a public read -----------------------------------------------

def anonymise(payload):
    """-> a copy of `payload` with every account identity replaced.

    Each distinct user_id becomes "anon-<n>" and the username beside it becomes
    "Player <n>", numbered in the order the ids are first met. The numbering is
    per response and means nothing outside it, which is the point: it is enough
    for a table to keep one player's cells together and not enough to be a
    handle on anybody.

    WHY THIS IS A WALK AND NOT A LIST OF FIELDS

    Naming the places a user_id appears would be correct today and wrong the
    first time somebody adds a field to one of these four responses. This
    codebase's rule for the Survivor reveal is that a secret is kept by never
    selecting it rather than by remembering to strip it; the same instinct
    applies here, so the default is "masked" and a new field inherits it without
    anyone having to notice.

    Two passes, because user_id is a dict KEY as well as a value --
    api/pickem.py keys totals.byUser by it -- and a single walk would reach some
    of those keys before the object that named the account, filing one player's
    data under two labels.
    """
    order = []
    _scan_ids(payload, order)
    names = {uid: {"user_id": f"anon-{i}", "username": f"Player {i}"}
             for i, uid in enumerate(order, start=1)}
    return _mask_ids(payload, names)


def _scan_ids(node, order):
    """Pass one: every user_id in the payload, in first-seen order."""
    if isinstance(node, dict):
        uid = node.get("user_id")
        if isinstance(uid, str) and uid not in order:
            order.append(uid)
        for value in node.values():
            _scan_ids(value, order)
    elif isinstance(node, list):
        for value in node:
            _scan_ids(value, order)


def _mask_ids(node, names):
    """Pass two: rewrite the identities, keys included.

    An id or a username that pass one did not account for is blanked rather than
    passed through. There should be no such value -- a username always travels
    beside the id it belongs to in these payloads -- and if one ever does, the
    failure this chooses is a missing name, not a published one.
    """
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            # A mapping keyed BY account: totals.byUser is the one today.
            masked_key = names[key]["user_id"] if key in names else key
            if key == "user_id":
                out[masked_key] = names[value]["user_id"] if value in names else None
            elif key == "username":
                owner = names.get(node.get("user_id"))
                out[masked_key] = owner["username"] if owner else ""
            else:
                out[masked_key] = _mask_ids(value, names)
        return out
    if isinstance(node, list):
        return [_mask_ids(value, names) for value in node]
    return node


# ---- time and season ---------------------------------------------------------

def now_utc():
    return datetime.now(timezone.utc)


def parse_ts(value):
    """Postgres hands back '2026-09-27T17:00:00+00:00'; balldontlie hands back
    '2026-09-27T17:00:00.000Z'. fromisoformat takes the first and, before 3.11,
    not the second, so the Z is rewritten rather than trusted."""
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    stamp = datetime.fromisoformat(text)
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def iso(stamp):
    return stamp.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z") \
        if stamp else None


def current_season(now=None):
    """The season a date falls in. March onward is that calendar year's season,
    so January and February still belong to the season that started the autumn
    before. Same rule as scripts/bdl_refresh.py."""
    now = now or now_utc()
    return now.year if now.month >= 3 else now.year - 1


# ---- reads -------------------------------------------------------------------

# The week board renders the line, so it needs `data` for the consensus workings
# and the line_status flag. Nothing else does: a whole season is 272 rows and
# every one of them carries eight sportsbooks' quotes, so the standings and the
# week index read the narrow set instead and leave ~2 MB of jsonb in Postgres.
GAME_COLUMNS = ("game_id,season,week,away,home,kickoff,spread_home,deadline_at,"
                "frozen_at,away_score,home_score,status,result,data")
SCORE_COLUMNS = ("game_id,season,week,away,home,kickoff,spread_home,"
                 "away_score,home_score,status,result")


def _shape_game(row, now):
    """One database row as the page sees it.

    game_id becomes a string here and stays one for the whole of the JSON side:
    the column is a bigint, JavaScript cannot hold a bigint exactly, and the
    committed schedule file has always carried these ids as strings. int on the
    SQL side, str on the wire, converted in exactly these two places.
    """
    kickoff = parse_ts(row["kickoff"])
    data = row.get("data") or {}
    return {
        "game_id": str(row["game_id"]),
        "season": row["season"],
        "week": row["week"],
        "away": row["away"],
        "home": row["home"],
        "kickoff": iso(kickoff),
        "kickoff_ts": kickoff,          # stripped before the response is sent
        "locked": kickoff is not None and kickoff <= now,
        "spread_home": None if row.get("spread_home") is None else float(row["spread_home"]),
        "line_status": data.get("line_status", "ok" if row.get("spread_home") is not None
                                else "unavailable"),
        "away_score": row.get("away_score"),
        "home_score": row.get("home_score"),
        "status": row.get("status") or "scheduled",
        "result": row.get("result"),
        # Underscored, and stripped before the response is sent: these are per
        # game in the table but per week in practice -- one capture run stamps
        # a whole slate -- so the week board lifts one of each to the top level
        # rather than repeating them on sixteen rows. Absent on the narrow read.
        "_deadline": iso(parse_ts(row.get("deadline_at"))) if "deadline_at" in row else None,
        "_frozen": iso(parse_ts(row.get("frozen_at"))) if "frozen_at" in row else None,
    }


def load_games(season, week, now):
    """Every game on the board for one week, kickoff order. The wide read."""
    rows = supabase_request(
        f"pickem_games?season=eq.{int(season)}&week=eq.{int(week)}"
        f"&select={GAME_COLUMNS}&order=kickoff.asc") or []
    return [_shape_game(r, now) for r in rows]


def load_season_games(season, now):
    """Every game in a season, narrow columns. What the standings grade against
    and what a default week is resolved from."""
    rows = supabase_request(
        f"pickem_games?season=eq.{int(season)}"
        f"&select={SCORE_COLUMNS}&order=week.asc,kickoff.asc") or []
    return [_shape_game(r, now) for r in rows]


def load_my_picks(user_id, season, week=None):
    """The requester's own picks. Never filtered by kickoff -- you can always
    see what you picked.

    A signed-out reader has none, which is answered here rather than left to the
    filter: `user_id=eq.None` is a string comparison that matches nothing by
    luck, and luck is not a rule.
    """
    if not user_id:
        return {}
    query = (f"pickem_picks?user_id=eq.{q(user_id)}&season=eq.{int(season)}"
             f"&select=game_id,week,data")
    if week is not None:
        query += f"&week=eq.{int(week)}"
    rows = supabase_request(query) or []
    return {str(r["game_id"]): (r.get("data") or {}) for r in rows}


def load_visible_others(season, week, games, me):
    """Every OTHER user's picks for the week, restricted to games that have
    already kicked off.

    `games` are rows this request has already read, so `locked` was computed
    from our own kickoff column against the server's clock -- no client value
    reaches this decision. The ids are ints out of our own table, which is what
    makes them safe to interpolate into the filter; the same reasoning as
    fetch_authors() in api/bun-notes.py.
    """
    unlocked = [int(g["game_id"]) for g in games if g["locked"]]
    if not unlocked:
        # Also avoids `in.()`, which PostgREST rejects as a syntax error rather
        # than reading as the empty set.
        return []
    ids = ",".join(str(i) for i in unlocked)
    query = (f"pickem_picks?season=eq.{int(season)}&week=eq.{int(week)}"
             f"&game_id=in.({ids})&select=user_id,game_id,data")
    # "Everyone else" is everyone when there is no caller to exclude. Spelled as
    # an absent clause rather than `neq.None`, which would filter against the
    # literal string 'None' and quietly keep working for the wrong reason.
    if me:
        query += f"&user_id=neq.{q(me)}"
    return supabase_request(query) or []


def load_all_picks(season, week=None):
    """Every user's picks, for the standings. Safe without a kickoff filter
    only because the standings response carries points and never a pick -- see
    api/pickem-standings.py, which is the one caller."""
    query = f"pickem_picks?season=eq.{int(season)}&select=user_id,game_id,week,data"
    if week is not None:
        query += f"&week=eq.{int(week)}"
    return supabase_request(query) or []


def load_usernames():
    """id -> username for every active account.

    Deliberate exposure: a leaderboard names the people on it, so any signed-in
    player learns the roster of active usernames. api/users.py stays admin-only;
    this is a narrower read (no role, no status, no created_at) for the one
    place that has to print names.
    """
    rows = supabase_request("users?select=id,username&status=eq.true") or []
    return {r["id"]: r.get("username") or "" for r in rows}


def current_week(games_by_week, now):
    """The week a reader means by "this week".

    The first week that still has an unlocked game, so a slate stays current
    while it is being played rather than flipping the moment the last kickoff
    passes -- Sunday evening is exactly when someone opens the page to see how
    they did. Falls through to the last week the board knows about once every
    game of the season has started.
    """
    for week in sorted(games_by_week):
        if any(g["kickoff_ts"] and g["kickoff_ts"] > now for g in games_by_week[week]):
            return week
    return max(games_by_week) if games_by_week else MIN_WEEK


def group_by_week(games):
    index = {}
    for game in games:
        index.setdefault(game["week"], []).append(game)
    return index


# ---- writes ------------------------------------------------------------------

def save_week_picks(user_id, season, week, clean):
    """Replace a user's picks for one week with exactly `clean`.

    Upsert first, delete second, deliberately: a failure between the two leaves
    too many rows rather than too few, and the next save repairs it. The other
    order can lose a pick outright.

    The composite PK (user_id, game_id) is what makes this safe -- user_id comes
    from the header on every row, so a forged game_id can only ever write a row
    under the caller's own account.
    """
    stamp = iso(now_utc())
    if clean:
        supabase_request(
            "pickem_picks?on_conflict=user_id,game_id",
            method="POST",
            body=[{
                "user_id": user_id,
                "game_id": int(p["game_id"]),
                "season": int(season),
                "week": int(week),
                "data": {"pick": p["pick"], "confidence": p["confidence"],
                         "updatedAt": stamp},
                "updated_at": "now()",
            } for p in clean],
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
        )

    keep = ",".join(str(int(p["game_id"])) for p in clean)
    where = (f"pickem_picks?user_id=eq.{q(user_id)}&season=eq.{int(season)}"
             f"&week=eq.{int(week)}")
    # not.in.() is the same empty-set syntax error in.() is, so an empty week
    # deletes everything rather than filtering against nothing.
    if keep:
        where += f"&game_id=not.in.({keep})"
    supabase_request(where, method="DELETE", headers={"Prefer": "return=minimal"})
