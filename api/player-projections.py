"""/api/player-projections -- one player's career game logs, from balldontlie.

GET /api/player-projections?name=Breece%20Hall&pos=RB[&team=NYJ]
    -> {"player": {"id", "name", "pos", "team"}, "games": [...]}

`name`, `pos` and `team` are a row of /api/players (the Trade Calculator's
list), which is what the page searches; they are resolved here to a balldontlie
player id by surname search over the active players (then all players), matched
on full name, then position, then team. `team` only breaks ties -- the one returned is
balldontlie's, which follows trades and signings the dynasty sites lag on.

`games` is every regular-season and postseason game that player has a box score
line in, newest first, one row per game in the defense-vs-players row shape
(scripts/build_defense_vs_players.py `player_row`) plus the game's own fields.
Every opponent is returned, not just this week's: the page picks the defense,
and can switch it without a second request.

GET /api/player-projections?offense=NE&defense=CHI&season=2026
    -> {"offense", "defense", "season", "players": [{"id", "name", "pos",
        "team", "status", "season_yds", "vs": [...], "recent": [...]}]}

The matchup mode, for /football/defense-vs-players: the offense's top QB, two
RBs, three WRs and two TEs by this season's yards (passing for a QB,
scrimmage for a back, receiving for the rest) off /season_stats, leaving out
anyone balldontlie's injury report has on IR, PUP, NFI or out. For each,
`vs` is every career game against `defense` and `recent` his last five games
of `season`, both newest first and in the row shape above.

GET /api/player-projections?props=1392309&player_id=36
    -> this week's lines for one player, for the page's projection. See
       load_props().

GET /api/player-projections?board=1392309,1392310
    -> every DraftKings yards line in those games, with each player's games,
       for the page's top 20 before a player is picked. See load_board().

Live, unlike /api/defense-vs-players: one search and one or two /stats pages
per player, cached at the CDN for six hours. Needs BALLDONTLIE_API_KEY.
"""
from http.server import BaseHTTPRequestHandler
from concurrent.futures import ThreadPoolExecutor
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _http import send_json  # noqa: E402

API_BASE = "https://api.balldontlie.io/nfl/v1"
POSITIONS = ("QB", "RB", "WR", "TE")
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
TEAM_RE = re.compile(r"^[A-Z]{2,3}$")
# Trade Calculator sources spell Washington the old way; balldontlie and the
# schedule file both say WSH.
TEAM_ALIAS = {"WAS": "WSH"}

CACHE_CONTROL = "s-maxage=21600, stale-while-revalidate=86400"

# A warm function answers a repeat lookup without going back to balldontlie.
_memo = {}
MEMO_TTL = 6 * 3600


def bdl_get(path, params):
    key = os.environ.get("BALLDONTLIE_API_KEY", "")
    if not key:
        raise RuntimeError("BALLDONTLIE_API_KEY is not set")
    url = f"{API_BASE}{path}?{urllib.parse.urlencode(params, doseq=True)}"
    req = urllib.request.Request(url, headers={"Authorization": key})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:200]
        raise RuntimeError(f"balldontlie {e.code}: {detail}") from None


def norm(name):
    """'Marvin Harrison Jr.' -> 'marvin harrison'; 'Amon-Ra St. Brown' ->
    'amonra st brown'."""
    words = re.sub(r"[^a-z0-9 ]", "", str(name or "").lower().replace("-", "")).split()
    return " ".join(w for w in words if w not in SUFFIXES)


def surname(name):
    """The word balldontlie's search can find him by: the last one that is not
    a suffix, punctuation kept ('Smith-Njigba', not 'smithnjigba')."""
    words = [w for w in str(name or "").split() if norm(w) and norm(w) not in SUFFIXES]
    return words[-1] if words else ""


def resolve(name, pos, team):
    """-> the balldontlie player for a Trade Calculator row, or None.

    Active players first; a player on injured reserve or a practice squad is
    missing from that list but still carries his team in the full one."""
    for path in ("/players/active", "/players"):
        data = bdl_get(path, {"search": surname(name), "per_page": 100})["data"]
        # The full list is every player who ever played: off the active list,
        # only one on the expected team is trusted to be him.
        if path == "/players" and team:
            data = [p for p in data if (p.get("team") or {}).get("abbreviation") == team]
        hit = match(data, name, pos, team)
        if hit:
            return hit
    return None


def match(data, name, pos, team):
    want = norm(name)
    last = want.split()[-1] if want else ""

    def pick(cands):
        if len(cands) > 1 and team:
            on_team = [p for p in cands if (p.get("team") or {}).get("abbreviation") == team]
            if on_team:
                cands = on_team
        return cands[0] if cands else None

    same_name = [p for p in data if norm(f"{p['first_name']} {p['last_name']}") == want]
    hit = pick([p for p in same_name if p.get("position_abbreviation") == pos]) or pick(same_name)
    if hit:
        return hit
    # A first name the sources spell differently ('Chig' / 'Chigoziem'): the
    # same surname at the same position on the same team is the same man.
    same_last = [p for p in data if p.get("position_abbreviation") == pos and
                 norm(p["last_name"]).split()[-1:] == [last]]
    if team:
        same_last = [p for p in same_last if (p.get("team") or {}).get("abbreviation") == team]
    return same_last[0] if len(same_last) == 1 else None


def n(v):
    return int(v or 0)


def game_row(s):
    """-> one /stats line in the defense-vs-players row shape, or None for a
    preseason game. balldontlie does not flag those; they are the only games a
    season has before September (week 1 is never earlier than the 4th)."""
    g = s["game"]
    if g["date"][:10] < f"{g['season']}-09-01":
        return None
    team = (s.get("team") or {}).get("abbreviation") or ""
    home = g["home_team"]["abbreviation"] == team
    opp = g["visitor_team" if home else "home_team"]["abbreviation"]
    pf, pa = ((g.get("home_team_score"), g.get("visitor_team_score")) if home
              else (g.get("visitor_team_score"), g.get("home_team_score")))
    row = {
        "game_id": g["id"],
        "season": g["season"],
        "week": g["week"],
        "postseason": bool(g.get("postseason")),
        "kickoff": g["date"],
        "status": g.get("status_state"),
        "team": team,
        "opp": opp,
        "home": home,
        "pts_for": pf,
        "pts_against": pa,
        "pass_cmp": n(s.get("passing_completions")),
        "pass_att": n(s.get("passing_attempts")),
        "pass_yds": n(s.get("passing_yards")),
        "pass_td": n(s.get("passing_touchdowns")),
        "pass_int": n(s.get("passing_interceptions")),
        # /stats carries no long completion; the defense table reads it off
        # /plays, which would be a request per game here.
        "pass_lng": None,
        "rush_att": n(s.get("rushing_attempts")),
        "rush_yds": n(s.get("rushing_yards")),
        "rush_td": n(s.get("rushing_touchdowns")),
        "rush_lng": n(s.get("long_rushing")),
        "targets": n(s.get("receiving_targets")),
        "rec": n(s.get("receptions")),
        "rec_yds": n(s.get("receiving_yards")),
        "rec_td": n(s.get("receiving_touchdowns")),
        "rec_lng": n(s.get("long_reception")),
    }
    row["tot_yds"] = row["rush_yds"] + row["rec_yds"]
    row["tot_td"] = row["rush_td"] + row["rec_td"]
    return row


def careers(player_ids):
    """-> {player id: every game row, newest first} for one or more players.
    No `seasons` filter: balldontlie then returns whole careers, a page per
    100 games, and a list of ids costs a page per 100 of their games together."""
    out, cursor = {pid: [] for pid in player_ids}, None
    while True:
        params = {"player_ids[]": list(player_ids), "per_page": 100}
        if cursor:
            params["cursor"] = cursor
        page = bdl_get("/stats", params)
        for s in page["data"]:
            r = game_row(s)
            pid = (s.get("player") or {}).get("id")
            if r and pid in out:
                out[pid].append(r)
        cursor = (page.get("meta") or {}).get("next_cursor")
        if not cursor:
            break
    for rows in out.values():
        rows.sort(key=lambda r: r["kickoff"], reverse=True)
    return out


def career(player_id):
    """-> every game row for one player, newest first."""
    return careers([player_id])[player_id]


# How many of each position the matchup mode returns, and the season yards
# each is ranked by.
MATCHUP_TOP = {"QB": 1, "RB": 2, "WR": 3, "TE": 2}
MATCHUP_YDS = {
    "QB": ("passing_yards",),
    "RB": ("rushing_yards", "receiving_yards"),
    "WR": ("receiving_yards",),
    "TE": ("receiving_yards",),
}
# Statuses that keep a player off the field this week. Questionable and
# doubtful players stay in, with their status shown.
SIDELINED = ("IR", "PUP", "NFI", "OUT", "SUSPENDED")
RECENT_GAMES = 5

_team_ids = {}


def team_id(abbr):
    if not _team_ids:
        for t in bdl_get("/teams", {})["data"]:
            _team_ids[t["abbreviation"]] = t["id"]
    return _team_ids.get(abbr)


def offense_top(offense, season):
    """-> [(player, status, season_yds)]: the offense's best players this
    season by yards, QB first, with two spares per position. The spares are
    for players who have since left -- /season_stats carries no current team,
    so that is checked against each one's latest game afterwards."""
    tid = team_id(offense)
    if tid is None:
        raise RuntimeError(f"unknown team {offense}")
    stats = bdl_get("/season_stats", {"season": season, "team_id": tid, "per_page": 100})["data"]
    injuries = bdl_get("/player_injuries", {"team_ids[]": tid, "per_page": 100})["data"]
    # A game-status tag (questionable, doubtful) is for one week; the feed
    # keeps August's around, so one older than ten days is dropped. A list
    # status (IR, PUP) stands until the player comes off it.
    stale = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 10 * 86400))
    status = {}
    for r in injuries:
        st = r.get("status") or ""
        if st.upper() in ("QUESTIONABLE", "DOUBTFUL", "PROBABLE") and (r.get("date") or "")[:10] < stale:
            continue
        status[(r.get("player") or {}).get("id")] = st
    out = []
    for pos in POSITIONS:
        cands = []
        for r in stats:
            p = r.get("player") or {}
            st = status.get(p.get("id"), "")
            if (p.get("position_abbreviation") != pos or r.get("postseason") or
                    any(x in st.upper() for x in SIDELINED)):
                continue
            yds = sum(n(r.get(k)) for k in MATCHUP_YDS[pos])
            cands.append((p, st, yds, n(r.get("games_played"))))
        cands.sort(key=lambda c: (-c[2], -c[3], c[0].get("last_name") or ""))
        out += [(p, st, yds) for p, st, yds, _ in cands[:MATCHUP_TOP[pos] + 2]]
    return out


def load_matchup(offense, defense, season):
    key = ("matchup", offense, defense, season)
    hit = _memo.get(key)
    if hit and time.time() - hit[0] < MEMO_TTL:
        return hit[1]
    top = offense_top(offense, season)
    with ThreadPoolExecutor(max_workers=8) as pool:
        careers = list(pool.map(lambda t: career(t[0]["id"]), top))
    players, taken = [], {}
    for (p, st, yds), games in zip(top, careers):
        pos = p.get("position_abbreviation")
        # Still on this offense: his latest game was for it.
        if not games or games[0]["team"] != offense or taken.get(pos, 0) >= MATCHUP_TOP[pos]:
            continue
        taken[pos] = taken.get(pos, 0) + 1
        players.append({
            "id": p["id"],
            "name": f"{p['first_name']} {p['last_name']}",
            "pos": pos,
            "team": offense,
            "status": st,
            "season_yds": yds,
            "vs": [g for g in games if g["opp"] == defense],
            "recent": [g for g in games if g["season"] == season][:RECENT_GAMES],
        })
    payload = {"offense": offense, "defense": defense, "season": season, "players": players}
    _memo[key] = (time.time(), payload)
    return payload


def parse_matchup(params):
    """-> (offense, defense, season, error | None)."""
    def team(k):
        t = (params.get(k) or [""])[0].strip().upper()
        return TEAM_ALIAS.get(t, t)
    offense, defense = team("offense"), team("defense")
    season = (params.get("season") or [""])[0].strip()
    if not TEAM_RE.match(offense) or not TEAM_RE.match(defense):
        return None, None, None, "offense and defense must be abbreviations, e.g. ?offense=NE&defense=CHI"
    if not re.match(r"^[0-9]{4}$", season):
        return None, None, None, "season must be a year"
    return offense, defense, int(season), None


def parse_props(params):
    """-> (game_id, player_id, error | None). Both are checked as digits
    before the game id reaches a PostgREST filter."""
    game_id = (params.get("props") or [""])[0].strip()
    player_id = (params.get("player_id") or [""])[0].strip()
    if not GAME_ID_RE.match(game_id) or not GAME_ID_RE.match(player_id):
        return None, None, "props and player_id must be ids, e.g. ?props=1392309&player_id=36"
    return game_id, int(player_id), None


def parse(params):
    """-> (name, pos, team, error | None)."""
    name = (params.get("name") or [""])[0].strip()
    pos = (params.get("pos") or [""])[0].strip().upper()
    team = (params.get("team") or [""])[0].strip().upper()
    team = TEAM_ALIAS.get(team, team)
    if not name or len(name) > 60:
        return None, None, None, "name is required, e.g. ?name=Breece%20Hall&pos=RB"
    if pos not in POSITIONS:
        return None, None, None, "pos must be one of " + ", ".join(POSITIONS)
    if team and not TEAM_RE.match(team):
        team = ""
    return name, pos, team, None


def load(name, pos, team):
    """-> the payload, or None when the player cannot be found."""
    key = (norm(name), pos, team)
    hit = _memo.get(key)
    if hit and time.time() - hit[0] < MEMO_TTL:
        return hit[1]
    p = resolve(name, pos, team)
    if not p:
        return None
    payload = {
        "player": {
            "id": p["id"],
            "name": f"{p['first_name']} {p['last_name']}",
            "pos": p.get("position_abbreviation") or pos,
            "team": (p.get("team") or {}).get("abbreviation") or team,
        },
        "games": career(p["id"]),
    }
    _memo[key] = (time.time(), payload)
    return payload


# ---------------------------------------------------------------------------
# This week's lines
# ---------------------------------------------------------------------------
#
# GET /api/player-projections?props=<game id>&player_id=<balldontlie id>
#     -> {"game_id", "player_id", "props": {prop_type: {"vendor", "line",
#         "over", "under"}}, "anytime_td": {"vendor", "odds"} | null}
#
# The page's projection is drawn against the line a book is actually hanging,
# so it reads the one game bundle scripts/bdl_refresh.py keeps in Supabase
# `game_odds` -- the same rows /football/schedule/game/<id> renders -- and
# returns only this player's full-game over/unders. One book per market, in
# PROP_BOOKS order, as the schedule's lines are: the page shows one price, and
# it has to be a price someone is offering.
#
# A book that shows two lines for one player in one market is quoting a
# second market under the first one's name (views/football/game-odds.html,
# "markets wearing another market's name"): the lowest is the real one,
# because every impostor is a superset of it.

PROP_MARKETS = ("passing_yards", "passing_completions", "passing_tds",
                "rushing_yards", "rushing_attempts", "receptions", "receiving_yards")
PROP_BOOKS = ("draftkings", "fanduel", "betmgm", "caesars", "fanatics", "betrivers")
PROPS_CACHE_CONTROL = "s-maxage=300, stale-while-revalidate=600"
GAME_ID_RE = re.compile(r"^[0-9]{1,12}$")
PROPS_TTL = 300
_props_memo = {}


def supabase_get(path):
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_KEY", "")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY are not set")
    req = urllib.request.Request(f"{url}/rest/v1/{path}", headers={
        "apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:200]
        raise RuntimeError(f"supabase {e.code}: {detail}") from None


def game_props(game_id):
    """-> the game's current player props, memoized for PROPS_TTL: every
    player on the page's two teams reads the same bundle."""
    hit = _props_memo.get(game_id)
    if hit and time.time() - hit[0] < PROPS_TTL:
        return hit[1]
    rows = supabase_get(f"game_odds?game_id=eq.{game_id}"
                        "&select=props:data->player_props->current")
    props = (rows[0].get("props") if rows else None) or []
    _props_memo[game_id] = (time.time(), props)
    return props


def book_rank(vendor):
    return PROP_BOOKS.index(vendor) if vendor in PROP_BOOKS else len(PROP_BOOKS)


def load_props(game_id, player_id):
    best, td = {}, None
    for r in game_props(game_id):
        if r.get("player_id") != player_id:
            continue
        m = r.get("market") or {}
        try:
            line = float(r.get("line_value"))
        except (TypeError, ValueError):
            continue
        vendor = r.get("vendor") or ""
        if r.get("prop_type") == "anytime_td" and m.get("type") == "milestone":
            if m.get("odds") is not None and (td is None or book_rank(vendor) < book_rank(td["vendor"])):
                td = {"vendor": vendor, "odds": m.get("odds")}
            continue
        if r.get("prop_type") not in PROP_MARKETS or m.get("type") != "over_under":
            continue
        quote = {"vendor": vendor, "line": line,
                 "over": m.get("over_odds"), "under": m.get("under_odds")}
        cur = best.get(r["prop_type"])
        # The best-ranked book, and within one book its lowest line.
        if (cur is None or book_rank(vendor) < book_rank(cur["vendor"]) or
                (vendor == cur["vendor"] and line < cur["line"])):
            best[r["prop_type"]] = quote
    return {"game_id": int(game_id), "player_id": player_id, "props": best, "anytime_td": td}


# ---------------------------------------------------------------------------
# The week's board
# ---------------------------------------------------------------------------
#
# GET /api/player-projections?board=1392309,1392310,...
#     -> {"players": [{"id", "name", "pos", "team", "opp", "home", "game_id",
#         "lines": {prop_type: {"vendor", "line", "over", "under"}},
#         "games": [...]}]}
#
# Every player DraftKings hangs a yards over/under for in the listed games --
# the week's games not yet kicked off, which the page knows from its
# schedule -- with the games its model reads, so the page can project each
# line before anyone is picked and rank them by how far off even they land.
# One book on purpose: the board is "where the model disagrees with DK's
# line", and a mix of books would rank one book's soft line against
# another's sharp one. Within the book, its lowest line, as load_props.
#
# `games` is the career rows the model reads, cut down to what it reads:
# this season and last, plus any earlier season with a game against this
# week's opponent, since his history against a defense is a ratio to his
# average that season. ~140 players' whole careers would be megabytes.

BOARD_MARKETS = ("passing_yards", "rushing_yards", "receiving_yards")
BOARD_BOOK = "draftkings"
BOARD_MAX_GAMES = 20
# Players per /stats request, and requests at once.
BOARD_CHUNK = 8
BOARD_WORKERS = 8
# What PlayerProjection.build reads off a game row.
BOARD_FIELDS = ("season", "week", "opp", "postseason",
                "pass_cmp", "pass_att", "pass_yds", "pass_td",
                "rush_att", "rush_yds", "rush_td",
                "targets", "rec", "rec_yds", "rec_td", "tot_yds", "tot_td")


def parse_board(params):
    """-> (game ids, error | None). Checked as digits before they reach a
    PostgREST filter."""
    ids = [s.strip() for s in (params.get("board") or [""])[0].split(",") if s.strip()]
    if not ids or len(ids) > BOARD_MAX_GAMES or not all(GAME_ID_RE.match(i) for i in ids):
        return None, f"board must be 1-{BOARD_MAX_GAMES} game ids, e.g. ?board=1392309,1392310"
    return sorted(set(ids)), None


def cached_careers(player_ids):
    """-> {player id: career rows}, from the warm memo where it has them and
    from balldontlie a chunk of players per request where it does not."""
    now, out, want = time.time(), {}, []
    for pid in player_ids:
        hit = _memo.get(("career", pid))
        if hit and now - hit[0] < MEMO_TTL:
            out[pid] = hit[1]
        else:
            want.append(pid)
    chunks = [want[i:i + BOARD_CHUNK] for i in range(0, len(want), BOARD_CHUNK)]
    with ThreadPoolExecutor(max_workers=BOARD_WORKERS) as pool:
        for got in pool.map(careers, chunks):
            for pid, rows in got.items():
                _memo[("career", pid)] = (now, rows)
                out[pid] = rows
    return out


def board_games(games, opp, season):
    keep = {season, season - 1} | {g["season"] for g in games if g["opp"] == opp}
    return [{k: g[k] for k in BOARD_FIELDS} for g in games if g["season"] in keep]


def load_board(game_ids):
    rows = supabase_get(f"game_odds?game_id=in.({','.join(game_ids)})"
                        "&select=game_id,game:data->game,players:data->players,"
                        "props:data->player_props->current")
    entries, seasons = {}, {}
    for r in rows:
        g = r.get("game") or {}
        away, home = (g.get("away") or {}).get("abbr"), (g.get("home") or {}).get("abbr")
        who = r.get("players") or {}
        for p in r.get("props") or []:
            m = p.get("market") or {}
            if (p.get("vendor") != BOARD_BOOK or p.get("prop_type") not in BOARD_MARKETS or
                    m.get("type") != "over_under"):
                continue
            try:
                line = float(p.get("line_value"))
            except (TypeError, ValueError):
                continue
            pid = p.get("player_id")
            info = who.get(str(pid)) or {}
            team = info.get("team")
            if info.get("position") not in POSITIONS or team not in (away, home):
                continue
            e = entries.get(pid)
            if e is None:
                e = entries[pid] = {
                    "id": pid, "name": info.get("name"), "pos": info["position"], "team": team,
                    "opp": home if team == away else away, "home": team == home,
                    "game_id": r["game_id"], "lines": {},
                }
                seasons[pid] = g.get("season")
            cur = e["lines"].get(p["prop_type"])
            if cur is None or line < cur["line"]:
                e["lines"][p["prop_type"]] = {"vendor": BOARD_BOOK, "line": line,
                                              "over": m.get("over_odds"), "under": m.get("under_odds")}
    games = cached_careers(list(entries))
    for pid, e in entries.items():
        e["games"] = board_games(games.get(pid, []), e["opp"], seasons[pid])
    return {"players": sorted(entries.values(), key=lambda e: e["name"] or "")}


# ---------------------------------------------------------------------------
# Team context
# ---------------------------------------------------------------------------
#
# GET /api/player-projections?context=<game id>
#     -> {"game": {"id", "season", "week", "away", "home", "kickoff", "phase"},
#         "teams": {abbr: {"doc": team_context data | null,
#                          "spread", "total",
#                          "status": {bdl id: {"name", "pos", "status", "label",
#                                              "injury", "practice"}},
#                          "ol": [{"name", "snap", "status"}],
#                          "market": {bdl id: {"name", "pos", "lines": {prop_type: line}}}}}}
#
# Everything the page's team-context factors read for one game, both sides:
# the offense's season from `team_context` (scripts/build_team_context.py)
# and this week's injury report and line from the game's bundle. The
# opponent's side is the same shape, so its defense's plays faced come from
# its own `doc`. `market` is every player the books hang a volume or yards
# line on this week: who the market thinks plays, and how much -- a starter
# just named, a back returning who has not played all season. The
# projections are pregame, so the report and lines are cached for
# CONTEXT_TTL, at the CDN and in a warm function.
#
# GET /api/player-projections?adjustments=1&season=2026&week=7&teams=NE,CHI
#     -> {abbr: {"data", "updated_by", "updated_at"}} for the teams with any.
#
# The hand adjustments from `projection_adjustments`, apart from the context
# and never cached: an editor's save has to show on the next load.
#
# GET /api/player-projections?can_adjust=1   (X-User-Id)
#     -> {"can_adjust": bool}. Roles are read at sign-in and kept in the
#        browser, so an account promoted since would not know; this asks.
#
# PUT /api/player-projections?adjust=1   (X-User-Id: an active admin or editor)
#     body {"season", "week", "team", "data"} -> {"ok": true, "adjust": {...}}
#     `data` is checked field by field (clean_adjust); an empty one clears the
#     week's adjustments for that team.

CONTEXT_TTL = 6 * 3600
CONTEXT_CACHE_CONTROL = f"s-maxage={CONTEXT_TTL}, stale-while-revalidate=3600"
_context_memo = {}
EDIT_ROLES = ("admin", "editor")
# An injury-report status that keeps a player out this week, as a substring:
# "IR-R", "Reserve-Sus" and "PUP-R" are all spelled differently.
OUT_WORDS = ("IR", "PUP", "NFI", "OUT", "SUS", "RESERVE")
GAME_TAGS = ("QUESTIONABLE", "DOUBTFUL", "PROBABLE", "OUT")
STATUS_RANK = {"out": 3, "doubtful": 2, "questionable": 1, "probable": 0}
LINE_POS = ("OT", "G", "C", "OL", "T")
# The share of snaps a lineman needs in one of the last two games to count as
# a starter whose absence is news.
OL_STARTER = 0.6


def supabase_write(path, method, body, prefer="return=representation"):
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_KEY", "")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY are not set")
    req = urllib.request.Request(f"{url}/rest/v1/{path}", data=json.dumps(body).encode(),
                                 method=method, headers={
                                     "apikey": key, "Authorization": f"Bearer {key}",
                                     "Content-Type": "application/json", "Prefer": prefer})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:200]
        raise RuntimeError(f"supabase {e.code}: {detail}") from None


def parse_context(params):
    """-> (game_id, error | None)."""
    game_id = (params.get("context") or [""])[0].strip()
    if not GAME_ID_RE.match(game_id):
        return None, "context must be a game id, e.g. ?context=1392309"
    return game_id, None


def injury_status(injuries, designations):
    """-> {bdl id: {...}} for one team: the bundle's injury report and this
    week's designations, as one status per player.

    A designation's game status is this week's word and wins. The injury feed
    carries a list status (IR, PUP, suspended) until the player comes off it,
    and game-week tags (out, questionable) that it never clears, so a tag older
    than ten days is dropped, as offense_top does."""
    stale = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 10 * 86400))
    out = {}

    def who(p):
        return {"name": f"{p.get('first_name', '')} {p.get('last_name', '')}".strip(),
                "pos": p.get("position_abbreviation") or ""}

    for r in injuries or []:
        p = r.get("player") or {}
        st = (r.get("status") or "").strip()
        up = st.upper()
        if not st or p.get("id") is None:
            continue
        if up in GAME_TAGS and (r.get("date") or "")[:10] < stale:
            continue
        kind = (up.lower() if up in GAME_TAGS
                else "out" if any(w in up for w in OUT_WORDS) else "questionable")
        out[str(p["id"])] = {**who(p), "status": kind, "label": st,
                             "injury": (r.get("comment") or "")[:160], "practice": []}
    for d in designations or []:
        p = d.get("player") or {}
        if p.get("id") is None:
            continue
        gs = (d.get("game_status") or "").lower()
        practice = [x.get("status") for x in d.get("practice_reports") or [] if x.get("status")]
        if d.get("active") is False:
            gs = "out"
        if not gs and not practice:
            continue
        cur = out.setdefault(str(p["id"]), {**who(p), "status": None, "label": "", "injury": "", "practice": []})
        if gs in STATUS_RANK:
            cur["status"], cur["label"] = gs, gs.capitalize()
        if d.get("injury"):
            cur["injury"] = d["injury"]
        cur["practice"] = practice
    return out


def line_status(doc, status):
    """-> the offensive line's starters, [{name, snap, status}]: anyone with
    OL_STARTER of the snaps in either of the last two games, with his status
    this week when the injury report has him (matched by name -- nflverse's
    snap counts and balldontlie share no id)."""
    games = [g for g in (doc or {}).get("games") or [] if not g.get("postseason")][:2]
    snap = {}
    for g in games:
        for name, pct in (g.get("ol") or {}).items():
            if pct >= OL_STARTER:
                snap[name] = max(snap.get(name, 0), pct)
    hurt = {norm(s["name"]): s["status"] for s in status.values() if s["pos"] in LINE_POS}
    return [{"name": name, "snap": pct, "status": hurt.get(norm(name))}
            for name, pct in sorted(snap.items(), key=lambda kv: -kv[1])]


# The over/unders that say how big a role the market expects.
MARKET_ROLE = ("passing_attempts", "passing_yards", "rushing_attempts", "rushing_yards",
               "receptions", "receiving_yards")


def market_roles(props, players, team):
    """-> {bdl id: {"name", "pos", "lines": {prop_type: line}}} for one team's
    QBs, backs and receivers: the best-ranked book's lowest line, as
    load_props."""
    best = {}
    for r in props or []:
        m = r.get("market") or {}
        info = (players or {}).get(str(r.get("player_id"))) or {}
        if (r.get("prop_type") not in MARKET_ROLE or m.get("type") != "over_under" or
                info.get("team") != team or info.get("position") not in POSITIONS):
            continue
        try:
            line = float(r.get("line_value"))
        except (TypeError, ValueError):
            continue
        key = (str(r["player_id"]), r["prop_type"])
        vendor = r.get("vendor") or ""
        cur = best.get(key)
        if (cur is None or book_rank(vendor) < book_rank(cur[0]) or
                (vendor == cur[0] and line < cur[1])):
            best[key] = (vendor, line)
    out = {}
    for (pid, market), (_, line) in best.items():
        info = players[pid]
        out.setdefault(pid, {"name": info.get("name"), "pos": info.get("position"), "lines": {}})["lines"][market] = line
    return out


def side_line(odds, home):
    """-> (this side's spread, total) off the best-ranked book, or (None, None)."""
    for o in sorted(odds or [], key=lambda o: book_rank(o.get("vendor"))):
        try:
            return (float(o["spread_home_value" if home else "spread_away_value"]),
                    float(o["total_value"]))
        except (KeyError, TypeError, ValueError):
            continue
    return None, None


def load_context(game_id):
    hit = _context_memo.get(game_id)
    if hit and time.time() - hit[0] < CONTEXT_TTL:
        return hit[1]
    rows = supabase_get(f"game_odds?game_id=eq.{game_id}&select=phase,game:data->game,"
                        "injuries:data->injuries,designations:data->designations,"
                        "current:data->odds->current,opening:data->odds->opening,"
                        "players:data->players,props:data->player_props->current")
    if not rows:
        return None
    r = rows[0]
    g = r.get("game") or {}
    away, home = (g.get("away") or {}).get("abbr"), (g.get("home") or {}).get("abbr")
    season = g.get("season")
    docs = {d["team"]: d["data"] for d in supabase_get(
        f"team_context?season=eq.{int(season)}&team=in.({away},{home})&select=team,data") or []}
    # Once the game is on, "current" is the in-game number.
    odds = r.get("current") if r.get("phase") == "pregame" else r.get("opening")
    teams = {}
    for side, abbr in (("away", away), ("home", home)):
        status = injury_status((r.get("injuries") or {}).get(side),
                               (r.get("designations") or {}).get(side))
        spread, total = side_line(odds, side == "home")
        teams[abbr] = {"doc": docs.get(abbr), "spread": spread, "total": total,
                       "status": status, "ol": line_status(docs.get(abbr), status),
                       "market": market_roles(r.get("props") if r.get("phase") == "pregame" else None,
                                              r.get("players"), abbr)}
    base = {"game": {"id": int(game_id), "season": season, "week": g.get("week"),
                     "away": away, "home": home, "kickoff": g.get("kickoff_utc"),
                     "phase": r.get("phase")},
            "teams": teams}
    _context_memo[game_id] = (time.time(), base)
    return base


def parse_adjustments(params):
    """-> (season, week, teams, error | None). Checked before they reach a
    PostgREST filter."""
    try:
        season = int((params.get("season") or [""])[0])
        week = int((params.get("week") or [""])[0])
    except ValueError:
        return None, None, None, "season and week must be numbers"
    teams = [t.strip().upper() for t in (params.get("teams") or [""])[0].split(",") if t.strip()]
    if not teams or len(teams) > 2 or not all(TEAM_RE.match(t) for t in teams):
        return None, None, None, "teams must be one or two abbreviations, e.g. teams=NE,CHI"
    return season, week, teams, None


def load_adjustments(season, week, teams):
    return {a["team"]: {"data": a["data"], "updated_by": a.get("updated_by"),
                        "updated_at": a.get("updated_at")}
            for a in supabase_get(f"projection_adjustments?season=eq.{season}&week=eq.{week}"
                                  f"&team=in.({','.join(teams)})"
                                  "&select=team,data,updated_by,updated_at") or []}


def resolve_editor(user_id):
    """-> (username, error): error None or (status, body). Only an active
    admin or editor may adjust."""
    if not user_id:
        return None, (401, {"error": "Not authenticated"})
    rows = supabase_get(f"users?id=eq.{urllib.parse.quote(user_id)}&select=username,role,status")
    user = rows[0] if rows else None
    if not user or user.get("status") is not True:
        return None, (403, {"error": "Account is inactive"})
    if user.get("role") not in EDIT_ROLES:
        return None, (403, {"error": "Only an admin or editor can adjust projections"})
    return user["username"], None


def can_adjust(user_id):
    try:
        return resolve_editor(user_id)[1] is None
    except Exception:  # noqa: BLE001
        return False


def _num(v, lo, hi):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        raise ValueError
    return round(float(v), 3)


# The hand-set fields, each with its bounds. Shares and snap rates are 0-1;
# a multiplier is anything from a quarter to four times.
ADJ_PLAYER = {"snap": (0, 1), "car_share": (0, 1), "tgt_share": (0, 1),
              "vol_mult": (0.25, 4), "eff_mult": (0.5, 2)}
ADJ_GAME = {"spread": (-40, 40), "total": (20, 90), "plays": (40, 95)}
ADJ_STATUS = ("out", "doubtful", "questionable", "in")
ADJ_MAX_ROWS = 60
ADJ_KEY_RE = re.compile(r"^[A-Za-z0-9_:.-]{1,40}$")


def clean_adjust(data):
    """-> (clean data, error | None). Unknown fields are dropped; a field out
    of bounds is an error, so a typo is refused rather than half-saved."""
    if not isinstance(data, dict):
        return None, "data must be an object"
    out = {}
    try:
        status = data.get("status") or {}
        if not isinstance(status, dict) or len(status) > ADJ_MAX_ROWS:
            raise ValueError
        out["status"] = {k: v for k, v in status.items() if GAME_ID_RE.match(str(k))}
        if any(v not in ADJ_STATUS for v in out["status"].values()):
            return None, "a status must be one of " + ", ".join(ADJ_STATUS)
        players = data.get("players") or {}
        if not isinstance(players, dict) or len(players) > ADJ_MAX_ROWS:
            raise ValueError
        out["players"] = {}
        for pid, fields in players.items():
            if not GAME_ID_RE.match(str(pid)) or not isinstance(fields, dict):
                raise ValueError
            row = {k: _num(fields[k], *ADJ_PLAYER[k]) for k in ADJ_PLAYER if fields.get(k) is not None}
            note = str(fields.get("note") or "").strip()[:200]
            if note:
                row["note"] = note
            if row:
                out["players"][str(pid)] = row
        game = data.get("game") or {}
        if not isinstance(game, dict):
            raise ValueError
        out["game"] = {k: _num(game[k], *ADJ_GAME[k]) for k in ADJ_GAME if game.get(k) is not None}
        if data.get("ol_out") is not None:
            out["ol_out"] = int(_num(data["ol_out"], 0, 5))
        off = data.get("off") or {}
        if not isinstance(off, dict) or len(off) > ADJ_MAX_ROWS:
            raise ValueError
        out["off"] = {k: True for k, v in off.items() if v and ADJ_KEY_RE.match(str(k))}
    except (ValueError, TypeError, KeyError):
        return None, "an adjustment is malformed or out of range"
    return {k: v for k, v in out.items() if v not in ({}, None)}, None


def save_adjust(body, username):
    """-> (payload, error | None)."""
    if not isinstance(body, dict):
        return None, "body must be an object"
    team = str(body.get("team") or "").upper()
    try:
        season, week = int(body.get("season")), int(body.get("week"))
    except (TypeError, ValueError):
        return None, "season and week must be numbers"
    if not TEAM_RE.match(team) or not 2000 <= season <= 2100 or not 1 <= week <= 23:
        return None, "team, season and week are required"
    data, error = clean_adjust(body.get("data"))
    if error:
        return None, error
    if not data:
        supabase_write(f"projection_adjustments?season=eq.{season}&week=eq.{week}&team=eq.{team}",
                       "DELETE", None, prefer="return=minimal")
        return {"ok": True, "adjust": None}, None
    rows = supabase_write("projection_adjustments?on_conflict=season,week,team", "POST", {
        "season": season, "week": week, "team": team, "data": data,
        "updated_by": username, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }, prefer="resolution=merge-duplicates,return=representation")
    row = rows[0]
    return {"ok": True, "adjust": {"data": row["data"], "updated_by": row["updated_by"],
                                   "updated_at": row["updated_at"]}}, None


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if params.get("offense"):
            self._matchup(params)
            return
        if params.get("props"):
            self._props(params)
            return
        if params.get("board"):
            self._board(params)
            return
        if params.get("context"):
            self._context(params)
            return
        if params.get("adjustments"):
            self._adjustments(params)
            return
        if params.get("can_adjust"):
            self._json(200, {"can_adjust": can_adjust(self.headers.get("X-User-Id"))},
                       {"Cache-Control": "no-store"})
            return
        name, pos, team, error = parse(params)
        if error:
            self._json(400, {"error": error})
            return
        try:
            payload = load(name, pos, team)
        except Exception as e:  # noqa: BLE001
            self._json(502, {"error": str(e)})
            return
        if payload is None:
            self._json(404, {"error": f"{name} not found in balldontlie"})
            return
        self._json(200, payload, {"Cache-Control": CACHE_CONTROL})

    def _matchup(self, params):
        offense, defense, season, error = parse_matchup(params)
        if error:
            self._json(400, {"error": error})
            return
        try:
            payload = load_matchup(offense, defense, season)
        except Exception as e:  # noqa: BLE001
            self._json(502, {"error": str(e)})
            return
        self._json(200, payload, {"Cache-Control": CACHE_CONTROL})

    def _props(self, params):
        game_id, player_id, error = parse_props(params)
        if error:
            self._json(400, {"error": error})
            return
        try:
            payload = load_props(game_id, player_id)
        except Exception as e:  # noqa: BLE001
            self._json(502, {"error": str(e)})
            return
        self._json(200, payload, {"Cache-Control": PROPS_CACHE_CONTROL})

    def _board(self, params):
        game_ids, error = parse_board(params)
        if error:
            self._json(400, {"error": error})
            return
        try:
            payload = load_board(game_ids)
        except Exception as e:  # noqa: BLE001
            self._json(502, {"error": str(e)})
            return
        self._json(200, payload, {"Cache-Control": PROPS_CACHE_CONTROL})

    def _context(self, params):
        game_id, error = parse_context(params)
        if error:
            self._json(400, {"error": error})
            return
        try:
            payload = load_context(game_id)
        except Exception as e:  # noqa: BLE001
            self._json(502, {"error": str(e)})
            return
        if payload is None:
            self._json(404, {"error": f"no game {game_id}"})
            return
        self._json(200, payload, {"Cache-Control": CONTEXT_CACHE_CONTROL})

    def _adjustments(self, params):
        season, week, teams, error = parse_adjustments(params)
        if error:
            self._json(400, {"error": error})
            return
        try:
            payload = load_adjustments(season, week, teams)
        except Exception as e:  # noqa: BLE001
            self._json(502, {"error": str(e)})
            return
        # Never cached: an editor's save has to show on the next load.
        self._json(200, payload, {"Cache-Control": "no-store"})

    def do_PUT(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if not params.get("adjust"):
            self._json(404, {"error": "PUT ?adjust=1 is the only write"})
            return
        try:
            username, err = resolve_editor(self.headers.get("X-User-Id"))
            if err:
                self._json(*err)
                return
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            payload, error = save_adjust(body, username)
        except json.JSONDecodeError:
            self._json(400, {"error": "Body must be JSON"})
            return
        except Exception as e:  # noqa: BLE001
            self._json(502, {"error": str(e)})
            return
        if error:
            self._json(400, {"error": error})
            return
        self._json(200, payload, {"Cache-Control": "no-store"})

    def _json(self, status, data, extra=None):
        send_json(self, status, data, {"Access-Control-Allow-Origin": "*", **(extra or {})})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-User-Id")
        self.end_headers()
