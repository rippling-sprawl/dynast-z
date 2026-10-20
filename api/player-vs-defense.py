"""/api/player-vs-defense -- one player's career game logs, from balldontlie.

GET /api/player-vs-defense?name=Breece%20Hall&pos=RB[&team=NYJ]
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

GET /api/player-vs-defense?offense=NE&defense=CHI&season=2026
    -> {"offense", "defense", "season", "players": [{"id", "name", "pos",
        "team", "status", "season_yds", "vs": [...], "recent": [...]}]}

The matchup mode, for /football/defense-vs-players: the offense's top QB, two
RBs, three WRs and two TEs by this season's yards (passing for a QB,
scrimmage for a back, receiving for the rest) off /season_stats, leaving out
anyone balldontlie's injury report has on IR, PUP, NFI or out. For each,
`vs` is every career game against `defense` and `recent` his last five games
of `season`, both newest first and in the row shape above.

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


def career(player_id):
    """-> every game row for one player, newest first. No `seasons` filter:
    balldontlie then returns the whole career, a page per 100 games."""
    rows, cursor = [], None
    while True:
        params = {"player_ids[]": player_id, "per_page": 100}
        if cursor:
            params["cursor"] = cursor
        page = bdl_get("/stats", params)
        rows += [r for r in (game_row(s) for s in page["data"]) if r]
        cursor = (page.get("meta") or {}).get("next_cursor")
        if not cursor:
            break
    rows.sort(key=lambda r: r["kickoff"], reverse=True)
    return rows


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


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if params.get("offense"):
            self._matchup(params)
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

    def _json(self, status, data, extra=None):
        send_json(self, status, data, {"Access-Control-Allow-Origin": "*", **(extra or {})})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
