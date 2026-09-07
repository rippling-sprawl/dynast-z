#!/usr/bin/env python3
"""
Pull one NFL game from balldontlie into a single normalized bundle in cache/.

What this is for
----------------
Two worked examples, chosen because between them they cover every state a game
is ever in:

  sb-lx    Super Bowl LX, 8 Feb 2026, Seahawks 29-13 Patriots at Levi's Stadium.
           Settled history. Exercises the full box score: team stats, per-player
           stats, every play, and closing odds. The score is known, so the
           bundle can be checked against the truth rather than merely parsed.

  week1    Patriots at Seahawks, Wed 9 Sep 2026, 8:20pm ET at Lumen Field — the
           rematch, and the league's first Wednesday opener since 2012.
           Exercises the pregame state: null scores, opening and current odds,
           player props, injuries and designations. Run it again during and
           after the game and the same command covers live and final too.

The phase is read off the game's own status_state, never off a flag, so one code
path serves scheduled, in-progress and final. That is what makes the Week 1
example a rehearsal for the live one rather than a separate program.

Tiers, and why a run on a free key is still useful
--------------------------------------------------
/games and /teams are free. /stats and /team_stats need ALL-STAR ($9.99/mo).
/plays, /odds and /player_props need GOAT ($39.99/mo, with a 48-hour trial).
An endpoint above your tier answers 401 — the same status as a bad key — so
bdl_common separates the two and this script records the refusal instead of
dying on it. A free-key run therefore still produces a valid bundle: the game
layer is real, and every paid layer is present as a recorded probe saying which
tier it wants. Re-run on a paid key and the same command fills them in.

Every response is cassetted under cache/bdl/, so after the trial lapses
--replay reproduces any bundle offline, indefinitely, for nothing.

Output goes to cache/ — gitignored, so a bundle stays private until someone
decides otherwise. --publish additionally upserts it into Supabase `game_odds`,
which is what /game-odds renders from.

It goes to Supabase rather than to a committed file under data/ because a bundle
is ~900 KB, almost all of it player props — 34 players x 25 markets x 6
sportsbooks, both sides of every over/under. A full 16-game slate would add ~15
MB a week to the repo, permanently, for numbers that are stale within minutes.
Same split as the Action Network book: data moves on a push, with no deploy.

Publishing stays opt-in for the reason build_action.py --push is: fetching
something and putting it on the public internet are two different decisions.
balldontlie's ToS §6 expressly permits publishing and displaying this data.

Usage:
    python3 scripts/fetch_bdl_game.py --example sb-lx
    python3 scripts/fetch_bdl_game.py --example week1
    python3 scripts/fetch_bdl_game.py --example week1 --replay   # offline
    python3 scripts/fetch_bdl_game.py --example week1 --record --label week1_final
    python3 scripts/fetch_bdl_game.py --game-id 1341307 --label probe
    python3 scripts/fetch_bdl_game.py --example week1 --publish   # also to Supabase
    python3 scripts/fetch_bdl_game.py --example week1 --all-books
    python3 scripts/fetch_bdl_game.py --example week1 --books draftkings
"""

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bdl_common as bdl  # noqa: E402

ET = ZoneInfo("America/New_York")

REGULAR_SEASON, POSTSEASON = 2, 3

# The books worth carrying. balldontlie quotes eight for a current game
# (betmgm, betrivers, caesars, draftkings, fanatics, fanduel, and the two
# prediction markets kalshi and polymarket) and ten on a settled one, but these
# are the two with accounts behind them -- the Odds Recorder bookmarklet reads
# DK and FD, and a line at a book you cannot bet into is not a line you can act
# on. Override with --books, or take everything with --all-books.
DEFAULT_BOOKS = ("draftkings", "fanduel")

# expect_* are assertions, not lookups: the resolver finds the game by matchup
# and then has to agree with what we already know about it. A silently wrong
# game is the worst outcome here, and it is not a hypothetical — a Patriots /
# Seahawks pairing exists in both the 2025 postseason and 2026 week 1.
EXAMPLES = {
    "sb-lx": {
        "label": "sb_lx", "season": 2025, "season_type": POSTSEASON,
        "away": "SEA", "home": "NE",
        "expect_date": "2026-02-08", "expect_score": [29, 13],
        "title": "Super Bowl LX",
    },
    "week1": {
        "label": "week1", "season": 2026, "season_type": REGULAR_SEASON, "week": 1,
        "away": "NE", "home": "SEA",
        "expect_date": "2026-09-10",
        "title": "Week 1, 2026 — Patriots at Seahawks",
    },
}

# The /stats row is ~60 flat columns. These group it the way a box score reads.
# Anything not listed lands in "other" rather than being dropped: the field list
# is transcribed from the docs and the docs are not the API.
STAT_GROUPS = {
    "passing": ("passing_completions", "passing_attempts", "passing_yards",
                "yards_per_pass_attempt", "passing_touchdowns", "passing_interceptions",
                "sacks", "sacks_loss", "qbr", "qb_rating"),
    "rushing": ("rushing_attempts", "rushing_yards", "yards_per_rush_attempt",
                "rushing_touchdowns", "long_rushing"),
    "receiving": ("receptions", "receiving_yards", "yards_per_reception",
                  "receiving_touchdowns", "long_reception", "receiving_targets"),
    "fumbles": ("fumbles", "fumbles_lost", "fumbles_recovered", "fumbles_touchdowns"),
    "defense": ("total_tackles", "defensive_sacks", "solo_tackles", "tackles_for_loss",
                "passes_defended", "qb_hits", "defensive_interceptions",
                "interception_yards", "interception_touchdowns"),
    "returns": ("kick_returns", "kick_return_yards", "yards_per_kick_return",
                "long_kick_return", "kick_return_touchdowns", "punt_returns",
                "punt_return_yards", "yards_per_punt_return", "long_punt_return",
                "punt_return_touchdowns"),
    "kicking": ("field_goal_attempts", "field_goals_made", "field_goal_pct",
                "long_field_goal_made", "extra_points_made", "total_points"),
    "punting": ("punts", "punt_yards", "gross_avg_punt_yards", "touchbacks",
                "punts_inside_20", "long_punt"),
}
GROUPED_FIELDS = {f for fields in STAT_GROUPS.values() for f in fields}

# Skipped when regrouping a stat row — they identify the row, they are not stats.
STAT_IDENTITY = ("player", "team", "game")


class PublishError(RuntimeError):
    """A --publish problem worth showing verbatim rather than as a traceback."""


def repo_path(*parts):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", *parts)


def iso_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def q(v):
    """Quarter scores are null for a scoreless quarter, not for a missing one —
    verified on Super Bowl LX, where New England's q1..q3 are null and q4 is 13,
    summing to its 13-point final. Reading null as "unknown" would break the
    check that the quarter line adds up to the final score."""
    return 0 if v is None else int(v)


def parse_date(s):
    t = (s or "").strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    return datetime.fromisoformat(t).astimezone(timezone.utc)


# --------------------------------------------------------------------------
# Resolution
# --------------------------------------------------------------------------

def resolve_game(spec, mode):
    """Find the one game matching the spec, or say precisely why it could not."""
    params = {"seasons[]": [spec["season"]], "season_types[]": [spec["season_type"]]}
    if spec.get("week"):
        params["weeks[]"] = [spec["week"]]
    rows = list(bdl.paginate("/games", params, mode=mode, quiet=True))

    want = {spec["away"], spec["home"]}
    hits = [g for g in rows
            if {g["visitor_team"]["abbreviation"], g["home_team"]["abbreviation"]} == want]

    if len(hits) != 1:
        print(f"ERROR: expected exactly 1 {spec['away']}/{spec['home']} game, "
              f"found {len(hits)} among {len(rows)} candidates", file=sys.stderr)
        for g in hits or rows[:12]:
            print(f"  id={g['id']} wk={g.get('week')} "
                  f"{g['visitor_team']['abbreviation']}@{g['home_team']['abbreviation']} "
                  f"{g['date']}", file=sys.stderr)
        return None

    g = hits[0]
    if spec.get("expect_date") and not g["date"].startswith(spec["expect_date"]):
        print(f"ERROR: resolved game {g['id']} is dated {g['date']}, "
              f"expected {spec['expect_date']}", file=sys.stderr)
        return None
    return g


def fetch_game_by_id(game_id, mode):
    payload, _ = bdl.bdl_get(f"/games/{game_id}", mode=mode)
    return payload.get("data") or payload


# --------------------------------------------------------------------------
# Bundle
# --------------------------------------------------------------------------

def phase_of(g):
    state = (g.get("status_state") or "").lower()
    if state == "final":
        return "final"
    if state in ("in", "in_progress", "live"):
        return "live"
    return "pregame"


def try_rows(path, params, mode, paginated=True, notes=None):
    """-> (rows, note). A tier refusal is recorded, not raised: a free-key run
    should still produce a bundle, with the gaps labelled."""
    try:
        if paginated:
            rows = list(bdl.paginate(path, params, mode=mode, quiet=True))
        else:
            payload, _ = bdl.bdl_get(path, params, mode=mode)
            rows = payload.get("data") or []
        print(f"  {path:<26} {len(rows):>4} rows")
        return rows, None
    except bdl.BdlError as e:
        note = {"path": path, "error": type(e).__name__,
                "detail": str(e).splitlines()[0],
                "needs_tier": bdl.min_tier(path)}
        print(f"  {path:<26}    -  {note['error']}: needs {note['needs_tier'].upper()}")
        if notes is not None:
            notes.append(note)
        return [], note


def resolve_players(prop_rows, stat_rows, mode):
    """-> {player_id: {name, position, team}} for every player the bundle names.

    Batched 100 at a time, which is /players' per_page ceiling. A lookup that
    fails is not fatal: the page falls back to the id, which is worse to read
    but still correct."""
    known = {}
    for r in stat_rows:
        pl = dict(r.get("player") or {})
        if not pl.get("id"):
            continue
        # A /stats player object carries no team of its own — the team is on the
        # stat row, because it is the team he played this game for. Without this
        # the props table's Team column is blank for anyone who also has a stat
        # line.
        if not pl.get("team") and r.get("team"):
            pl["team"] = r["team"]
        known[pl["id"]] = pl
    want = sorted({r["player_id"] for r in prop_rows if r.get("player_id")}
                  - set(known))
    for i in range(0, len(want), 100):
        chunk = want[i:i + 100]
        try:
            for pl in bdl.paginate("/players", {"player_ids[]": chunk},
                                   mode=mode, quiet=True):
                known[pl["id"]] = pl
        except bdl.BdlError as e:
            print(f"  /players lookup failed for {len(chunk)} ids: "
                  f"{str(e).splitlines()[0]}")
            break
    out = {}
    for pid, pl in known.items():
        out[str(pid)] = {
            "name": " ".join(filter(None, [pl.get("first_name"), pl.get("last_name")]))
                    or str(pid),
            "position": pl.get("position_abbreviation") or pl.get("position"),
            "team": ((pl.get("team") or {}).get("abbreviation")),
        }
    print(f"  {'players':<26} {len(out):>4} resolved")
    return out


def group_stat_row(row):
    out = {"player": row.get("player"), "team": row.get("team")}
    other = {}
    for k, v in row.items():
        if k in STAT_IDENTITY or k in GROUPED_FIELDS:
            continue
        other[k] = v
    for group, fields in STAT_GROUPS.items():
        vals = {f: row[f] for f in fields if f in row}
        # /stats returns all ~60 columns for every player, so a receiver still
        # carries a full set of null passing fields. Keeping those would put all
        # 33 players in the passing table with a row of dashes each. A category
        # earns its place only if the player actually did something in it.
        if vals and any(v for v in vals.values()):
            out[group] = vals
    if other:
        out["other"] = other
    return out


def keep_books(rows, books):
    """Drop rows quoted by a book we are not carrying.

    Applied even to responses that were already filtered server-side. That is
    not paranoia about this endpoint in particular: balldontlie *ignores* a
    filter it does not recognize on some paths and 400s on others, and the
    difference between the two is not documented anywhere. A filter applied
    twice costs nothing; a filter silently dropped costs eight books of props
    masquerading as two."""
    if not books:
        return rows
    return [r for r in rows if r.get("vendor") in books]


def side_of(row, home_id, away_id):
    """Which team a row belongs to.

    Not every endpoint says it the same way: /stats and /team_stats carry a
    top-level `team`, but /player_injuries carries none at all and the team is
    only reachable through the player. Without the fallback every injury row
    lands in "unknown"."""
    team = row.get("team") or (row.get("player") or {}).get("team") or {}
    tid = team.get("id")
    if tid == home_id:
        return "home"
    if tid == away_id:
        return "away"
    return None


def build_bundle(g, label, title, mode, books=DEFAULT_BOOKS):
    home, away = g["home_team"], g["visitor_team"]
    phase = phase_of(g)
    gid = g["id"]
    notes = []

    print(f"\n{title or ''}".rstrip())
    print(f"  game {gid}: {away['abbreviation']}@{home['abbreviation']} "
          f"{g['date']}  status={g.get('status')!r} phase={phase}")

    kickoff = parse_date(g["date"])
    bundle = {
        "label": label,
        "title": title,
        "phase": phase,
        "fetched_at": iso_now(),
        "fetched_ts": int(time.time()),
        "game": {
            "id": gid,
            "season": g.get("season"),
            "season_type": POSTSEASON if g.get("postseason") else REGULAR_SEASON,
            "week": g.get("week"),
            "postseason": bool(g.get("postseason")),
            "kickoff_raw": g["date"],
            "kickoff_utc": kickoff.strftime("%Y-%m-%dT%H:%MZ"),
            "kickoff_et": kickoff.astimezone(ET).strftime("%a %Y-%m-%d %H:%M %Z"),
            "status": g.get("status"),
            "status_state": g.get("status_state"),
            "venue": g.get("venue"),
            "summary": g.get("summary"),
            "away": {"id": away["id"], "abbr": away["abbreviation"],
                     "name": away["full_name"]},
            "home": {"id": home["id"], "abbr": home["abbreviation"],
                     "name": home["full_name"]},
        },
    }

    if phase == "pregame":
        bundle["game"]["score"] = None
    else:
        bundle["game"]["score"] = {
            "away": g.get("visitor_team_score"),
            "home": g.get("home_team_score"),
            "away_line": [q(g.get(f"visitor_team_{k}")) for k in
                          ("q1", "q2", "q3", "q4", "ot")],
            "home_line": [q(g.get(f"home_team_{k}")) for k in
                          ("q1", "q2", "q3", "q4", "ot")],
        }

    # Array filters take brackets -- game_ids[] -- everywhere except /plays and
    # the two props endpoints, which take a singular game_id. Note that the
    # OpenAPI spec at https://www.balldontlie.io/openapi/nfl.yml documents /odds
    # and /team_stats as taking a bare `game_ids`, and that is wrong: the API
    # answers 400 with "game_ids must be an array (use game_ids[]=value)". The
    # HTML docs are wrong about the props path. Where the three disagree, the
    # running API wins -- these names were settled by probing it.
    gp = {"game_ids[]": [gid]}              # /odds, /odds/opening, /stats, /team_stats
    gp_single = {"game_id": gid}            # /plays, /odds/player_props

    # Only the props endpoints take a book filter; /odds does not, so its eight
    # rows come back whole and are cut below. `vendors[]` with brackets is the
    # only form that works for a single book -- a bare `vendors=draftkings`
    # answers 400 "vendors must be an array", though a repeated bare
    # `vendors=a&vendors=b` is accepted. Brackets are right in both cases.
    props_params = dict(gp_single)
    if books:
        props_params["vendors[]"] = list(books)
    tp = {"team_ids[]": [home["id"], away["id"]]}
    stype = bundle["game"]["season_type"]

    # Always attempted. On a scheduled game these are the whole point of the
    # example, and balldontlie stores no prop history — a line not captured
    # before kickoff cannot be bought back afterwards at any price.
    odds_cur, _ = try_rows("/odds", gp, mode, notes=notes)
    odds_open, _ = try_rows("/odds/opening", gp, mode, notes=notes)
    props_cur, _ = try_rows("/odds/player_props", props_params, mode, notes=notes)
    props_open, _ = try_rows("/odds/player_props/opening", props_params, mode,
                             notes=notes)
    injuries, _ = try_rows("/player_injuries", tp, mode, notes=notes)

    # /player_designations has no team filter -- season, week and season_types
    # are all it takes -- so the whole slate comes back and the two teams are
    # picked out here.
    dp = {"season": g.get("season"),
          "season_types[]": [bundle["game"]["season_type"]]}
    if g.get("week"):
        dp["week"] = g["week"]
    designations, _ = try_rows("/player_designations", dp, mode, notes=notes)
    designations = [d for d in designations
                    if ((d.get("team") or {}).get("id") in (home["id"], away["id"]))]

    # Attempted in every phase, including pregame. Whether a scheduled game's
    # /stats answers with an empty array, a 404, or a row of zeroes decides how
    # the live poller has to be written, and it is unanswerable once the trial
    # has lapsed. So probe now and record whatever comes back.
    # season_types[] is not optional here even though a game id fully identifies
    # the game: without it /team_stats silently returns zero rows for a
    # postseason game rather than erroring. /stats has no such quirk.
    ts_params = dict(gp)
    ts_params["season_types[]"] = [stype]
    team_stats, _ = try_rows("/team_stats", ts_params, mode, notes=notes)
    player_stats, _ = try_rows("/stats", gp, mode, notes=notes)
    plays, _ = try_rows("/plays", gp_single, mode, notes=notes)

    hid, aid = home["id"], away["id"]

    def split(rows):
        out = {"home": [], "away": [], "unknown": []}
        for r in rows:
            out[side_of(r, hid, aid) or "unknown"].append(r)
        if not out["unknown"]:
            del out["unknown"]
        return out

    ts = split(team_stats)
    bundle["team_stats"] = {"home": (ts["home"] or [None])[0],
                            "away": (ts["away"] or [None])[0]}

    ps = split(player_stats)
    bundle["player_stats"] = {side: [group_stat_row(r) for r in rows]
                              for side, rows in ps.items()}

    scoring = [p for p in plays if p.get("scoring_play")]
    bundle["plays"] = {"count": len(plays), "scoring_count": len(scoring),
                       "scoring": scoring, "all": plays}

    # Rows are stored exactly as returned. The two summary fields below are
    # derived from what actually arrives: the sportsbook is `vendor` (not
    # `sportsbook` or `book`), and a prop's market is `prop_type` -- `market` is
    # a nested {type, odds} object, so summarizing on it yields stringified
    # dicts rather than market names.
    def vendors(*rowsets):
        return sorted({r["vendor"] for rows in rowsets for r in rows if r.get("vendor")})

    odds_cur = keep_books(odds_cur, books)
    odds_open = keep_books(odds_open, books)
    props_cur = keep_books(props_cur, books)
    props_open = keep_books(props_open, books)

    bundle["books_filter"] = sorted(books) if books else None
    bundle["odds"] = {
        "current": odds_cur, "opening": odds_open,
        "books": vendors(odds_cur, odds_open),
    }
    bundle["player_props"] = {
        "current": props_cur, "opening": props_open,
        "books": vendors(props_cur, props_open),
        "markets": sorted({r["prop_type"] for r in props_cur + props_open
                           if r.get("prop_type")}),
    }

    # Props carry a bare player_id and no name, so without this the page would
    # render several thousand rows of integers. /stats rows already embed the
    # whole player object, so only the prop ids need looking up.
    bundle["players"] = resolve_players(props_cur + props_open, player_stats, mode)
    if books:
        print(f"  {'books kept':<26} {', '.join(sorted(books))}")
    bundle["injuries"] = split(injuries)
    bundle["designations"] = split(designations)
    bundle["unavailable"] = notes
    bundle["timing"] = bdl.latency_summary()
    return bundle


# --------------------------------------------------------------------------
# Verify
# --------------------------------------------------------------------------

def verify(bundle, spec):
    ok = True
    g = bundle["game"]
    phase = bundle["phase"]
    print(f"\n{phase} bundle for game {g['id']}")

    for side in ("home", "away"):
        if not g[side]["abbr"]:
            print(f"ERROR: {side} team has no abbreviation", file=sys.stderr)
            ok = False

    if phase == "pregame":
        if g["score"] is not None:
            print("ERROR: a scheduled game carries a score", file=sys.stderr)
            ok = False
    else:
        sc = g["score"]
        if sc["away"] is None or sc["home"] is None:
            print("ERROR: a final game has a null score", file=sys.stderr)
            ok = False
        else:
            for side in ("away", "home"):
                line, total = sc[f"{side}_line"], sc[side]
                if sum(line) != total:
                    print(f"ERROR: {side} quarter line {line} sums to {sum(line)}, "
                          f"not the {total} final", file=sys.stderr)
                    ok = False
            want = spec.get("expect_score")
            if want and [sc["away"], sc["home"]] != want:
                print(f"ERROR: score is {[sc['away'], sc['home']]}, expected {want}",
                      file=sys.stderr)
                ok = False

        # Only assert the box score when it actually came back. On a free key
        # every one of these is a recorded 401, and refusing to write then would
        # mean refusing to write the one thing a free key CAN produce.
        if bundle["plays"]["count"]:
            last = bundle["plays"]["all"][-1]
            got = [last.get("away_score"), last.get("home_score")]
            if got != [sc["away"], sc["home"]]:
                print(f"ERROR: last play reads {got}, game says "
                      f"{[sc['away'], sc['home']]}", file=sys.stderr)
                ok = False
            if bundle["plays"]["count"] < 100:
                print(f"ERROR: only {bundle['plays']['count']} plays for a full game",
                      file=sys.stderr)
                ok = False
        n_players = sum(len(v) for v in bundle["player_stats"].values())
        if n_players and n_players < 30:
            print(f"ERROR: only {n_players} player stat lines", file=sys.stderr)
            ok = False

    counts = {
        "plays": bundle["plays"]["count"],
        "player_stats": sum(len(v) for v in bundle["player_stats"].values()),
        "team_stats": sum(1 for v in bundle["team_stats"].values() if v),
        "odds": len(bundle["odds"]["current"]),
        "odds_opening": len(bundle["odds"]["opening"]),
        "props": len(bundle["player_props"]["current"]),
        "injuries": sum(len(v) for v in bundle["injuries"].values()),
        "designations": sum(len(v) for v in bundle["designations"].values()),
    }
    print("  " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    if bundle["unavailable"]:
        tiers = sorted({n["needs_tier"] for n in bundle["unavailable"]})
        why = ("never recorded" if all(n["error"] == "CassetteMiss"
                                       for n in bundle["unavailable"])
               else "unavailable on this key")
        print(f"  {len(bundle['unavailable'])} endpoints {why} "
              f"(need {', '.join(t.upper() for t in tiers)})")
    return ok, counts


def write_shapes(bundle, path):
    """What the endpoints actually returned, key by key.

    Three of the four gaps the research doc left open — which sportsbooks are
    covered, what the prop markets are called, what an odds row even looks like
    — are answerable only from a live paid response, and are not documented
    anywhere. This file is where that knowledge survives the trial."""
    shapes = {}

    def record(name, rows):
        if not rows:
            shapes[name] = {"rows": 0}
            return
        r = rows[0]
        shapes[name] = {
            "rows": len(rows),
            "keys": {k: type(v).__name__ for k, v in sorted(r.items())},
        }

    record("odds", bundle["odds"]["current"])
    record("odds_opening", bundle["odds"]["opening"])
    record("player_props", bundle["player_props"]["current"])
    record("plays", bundle["plays"]["all"])
    record("injuries", sum(bundle["injuries"].values(), []))
    record("designations", sum(bundle["designations"].values(), []))
    for side in ("home", "away"):
        if bundle["team_stats"][side]:
            record(f"team_stats_{side}", [bundle["team_stats"][side]])
            break
    ps = sum(bundle["player_stats"].values(), [])
    record("player_stats_grouped", ps)

    existing = {}
    if os.path.exists(path):
        try:
            with open(path) as f:
                existing = json.load(f)
        except ValueError:
            pass
    existing[bundle["label"]] = {
        "observed_at": bundle["fetched_at"],
        "phase": bundle["phase"],
        "books": bundle["odds"]["books"],
        "prop_markets": bundle["player_props"]["markets"],
        "endpoints": shapes,
        "unavailable": bundle["unavailable"],
    }
    with open(path, "w") as f:
        json.dump(existing, f, indent=2)
    return path


def publish(bundle):
    """Upsert the bundle into Supabase `game_odds`. -> list of log lines.

    Writes straight to PostgREST with the service key from .env rather than
    through an ingest endpoint, which is what build_action.py --seed does and is
    enough here: this script already needs a keyed .env to have fetched anything,
    and there is no second machine pushing game bundles. If that changes, the
    endpoint to add is the api/action-ingest.py shape — an admin-gated PUT.

    The summary columns are duplicated out of the bundle on purpose so the
    listing at /api/game-odds can render without pulling a megabyte per row."""
    url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_KEY") or ""
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_KEY are needed to --publish.\n"
            "Both are already in .env for the rest of the site; if this is a "
            "fresh checkout, copy them from the Supabase dashboard.")

    g = bundle["game"]
    # Canonical JSON so the same bundle always hashes the same way. This is the
    # page's HTTP validator: an unchanged game costs a 304 instead of ~900 KB.
    canon = json.dumps(bundle, sort_keys=True, separators=(",", ":"))
    etag = hashlib.sha256(canon.encode()).hexdigest()

    row = {
        "game_id": g["id"],
        "season": g.get("season"),
        "week": g.get("week"),
        "phase": bundle["phase"],
        "away": g["away"]["abbr"],
        "home": g["home"]["abbr"],
        "kickoff": g.get("kickoff_raw"),
        "title": bundle.get("title"),
        "label": bundle.get("label"),
        "has": {
            "odds": bool(bundle["odds"]["current"] or bundle["odds"]["opening"]),
            "props": bool(bundle["player_props"]["current"]
                          or bundle["player_props"]["opening"]),
            "team_stats": any(bundle["team_stats"].values()),
            "player_stats": bool(sum(len(v) for v in bundle["player_stats"].values())),
            "plays": bool(bundle["plays"]["count"]),
        },
        "data": bundle,
        "etag": etag,
        "updated_at": "now()",
    }

    req = urllib.request.Request(
        f"{url}/rest/v1/game_odds?on_conflict=game_id",
        data=json.dumps([row]).encode(), method="POST")
    req.add_header("apikey", key)
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Prefer", "resolution=merge-duplicates,return=minimal")
    try:
        with urllib.request.urlopen(req) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        if "PGRST205" in detail or "game_odds" in detail and e.code in (400, 404):
            ref = url.split("//")[-1].split(".")[0]
            raise PublishError(
                "The game_odds table does not exist yet.\n\n"
                "  Run scripts/sql/game_odds.sql once, in the SQL editor at\n"
                f"  https://supabase.com/dashboard/project/{ref}/sql/new\n\n"
                "  Then re-run this command. Nothing else needs doing -- the\n"
                "  bundle is already in cache/, so the re-run costs no requests.")
        raise PublishError(f"Supabase write failed ({e.code}): {detail}")

    return [f"Published game {g['id']} to Supabase game_odds "
            f"({len(canon) / 1024:.0f} KB, etag {etag[:12]})",
            f"  /game-odds?game={g['id']}"]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--example", choices=sorted(EXAMPLES))
    ap.add_argument("--game-id", type=int)
    ap.add_argument("--label", help="output name; defaults to the example's label")
    ap.add_argument("--books", default=",".join(DEFAULT_BOOKS), metavar="LIST",
                    help="comma-separated sportsbooks to keep "
                         f"(default {','.join(DEFAULT_BOOKS)})")
    ap.add_argument("--all-books", action="store_true",
                    help="keep every book balldontlie quotes")
    ap.add_argument("--raw", action="store_true",
                    help="also write the unshaped rows alongside the bundle")
    ap.add_argument("--publish", action="store_true",
                    help="upsert the bundle into Supabase game_odds, which is "
                         "what /game-odds renders — this publishes it")
    bdl.add_mode_args(ap)
    args = ap.parse_args()

    if not args.example and not args.game_id:
        ap.error("give --example or --game-id")
    mode = bdl.resolve_mode(args)

    spec = dict(EXAMPLES.get(args.example, {}))
    label = args.label or spec.get("label") or f"game_{args.game_id}"
    print(f"balldontlie game bundle: {label} (mode={mode})\n")

    try:
        if args.game_id:
            g = fetch_game_by_id(args.game_id, mode)
        else:
            g = resolve_game(spec, mode)
        if not g:
            return 1
        books = () if args.all_books else tuple(
            b.strip().lower() for b in args.books.split(",") if b.strip())
        bundle = build_bundle(g, label, spec.get("title"), mode, books)
    except bdl.BdlError as e:
        print(f"\n{e}", file=sys.stderr)
        return 1

    ok, counts = verify(bundle, spec)
    if not ok:
        print("\nRefusing to overwrite good data.", file=sys.stderr)
        return 1

    cache_dir = repo_path("cache")
    os.makedirs(cache_dir, exist_ok=True)
    out_path = os.path.join(cache_dir, f"bdl_game_{label}.json")
    with open(out_path, "w") as f:
        json.dump(bundle, f, separators=(",", ":"))
    print(f"\nWrote {os.path.abspath(out_path)} "
          f"({os.path.getsize(out_path) / 1024:.0f} KB)")

    if args.raw:
        raw_path = os.path.join(cache_dir, f"bdl_game_{label}_raw.json")
        with open(raw_path, "w") as f:
            json.dump({"game": g}, f, indent=2)
        print(f"Wrote {os.path.abspath(raw_path)}")

    shapes = write_shapes(bundle, os.path.join(cache_dir, "bdl_shapes.json"))
    print(f"Wrote {os.path.abspath(shapes)}")

    if args.publish:
        try:
            for line in publish(bundle):
                print(line)
        except PublishError as e:
            print(f"\nNot published. {e}", file=sys.stderr)
            return 1

    meta_path = os.path.join(cache_dir, f"bdl_game_{label}_meta.json")
    with open(meta_path, "w") as f:
        json.dump({
            "source": "balldontlie",
            "url": f"{bdl.API_BASE}/games/{bundle['game']['id']}",
            "label": label,
            "title": spec.get("title"),
            "game_id": bundle["game"]["id"],
            "phase": bundle["phase"],
            "matchup": f"{bundle['game']['away']['abbr']}@{bundle['game']['home']['abbr']}",
            "kickoff_et": bundle["game"]["kickoff_et"],
            "counts": counts,
            "unavailable": bundle["unavailable"],
            "latency_ms": bundle["timing"],
            "size_bytes": os.path.getsize(out_path),
            "fetched_at": bundle["fetched_at"],
            "fetched_ts": bundle["fetched_ts"],
        }, f, indent=2)
    print(f"Wrote {os.path.abspath(meta_path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
