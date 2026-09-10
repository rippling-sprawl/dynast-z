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
    python3 scripts/fetch_bdl_game.py --season 2026 --week 1 --away SF --home LAR
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
import unicodedata
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


# --------------------------------------------------------------------------
# Refresh policy
# --------------------------------------------------------------------------
#
# How often a game is worth re-fetching, as a function of how far it is from
# kickoff. Two consumers, one answer: scripts/bdl_refresh.py sweeps on this to
# decide what is due, and build_bundle stamps the result into every bundle so
# /football/schedule/game/<id> can say when the page will next change instead of
# leaving the reader to guess.
#
# The shape of it follows the market. Books have not posted a line eight days
# out; it drifts through the week, moves through the day, and moves on every
# snap. At the whistle it stops -- but the box score does not, because stat
# corrections keep landing for a few hours, which is why a final game is not
# frozen the moment it goes final.

HOUR = 3600
# 30s, not the 2 minutes this used to be. Affordable because a live capture no
# longer re-fetches the static sections: measured on NE@SEA week 1 2026 a
# capture fell from 36 requests to 10, so a 16-game live slate at 30s costs
# ~320 req/min against GOAT's 600 -- about what the old 2-minute cadence cost
# before the carry-forward existed. See reusable_static().
LIVE_INTERVAL = 30
IMMINENT_INTERVAL = 10 * 60
GAMEDAY_INTERVAL = HOUR
UPCOMING_INTERVAL = 6 * HOUR
SETTLING_INTERVAL = 30 * 60

# How long after kickoff a final game keeps being re-fetched for stat
# corrections. Six hours covers a 3.5-hour game plus the window in which the
# league revises a fumble recovery or a target.
SETTLING_WINDOW = 6 * HOUR

# Beyond this, nothing is fetched at all: there is no market to record.
DISTANT_HORIZON = 8 * 24 * HOUR

# Rendered verbatim by the page, so the reason a game is on the cadence it is on
# lives next to the cadence rather than being reinvented in JavaScript.
REFRESH_NOTE = {
    "settled": "final and past stat corrections \u2014 this will not change again",
    "settling": "final; stat corrections still land for a few hours",
    "live": "in progress",
    "imminent": "kickoff is close, lines move fastest now",
    "gameday": "game day",
    "upcoming": "more than a day out",
    "distant": "too far out for the books to have posted",
}


def refresh_plan(kickoff_ts, phase, last_ts=None, now=None):
    """When this game is next worth re-fetching.

    -> {"policy", "interval_s", "frozen", "note"[, "next_ts", "next_at"]}

    `last_ts` is when it was last captured; without one the answer is "now".
    A frozen plan carries no next_* keys at all rather than a null one, so the
    page renders the absence rather than having to test for it."""
    now = float(now if now is not None else time.time())
    to_kick = (kickoff_ts - now) if kickoff_ts else None

    if phase == "final":
        since = (now - kickoff_ts) if kickoff_ts else SETTLING_WINDOW + 1
        if since > SETTLING_WINDOW:
            policy, interval = "settled", None
        else:
            policy, interval = "settling", SETTLING_INTERVAL
    elif phase == "live":
        policy, interval = "live", LIVE_INTERVAL
    elif to_kick is None:
        # No kickoff to reason from. Hourly is the safe middle.
        policy, interval = "gameday", GAMEDAY_INTERVAL
    elif to_kick <= 0:
        # Kickoff has passed but status_state has not caught up. This is exactly
        # the window in which it is about to, so poll at the live cadence.
        policy, interval = "live", LIVE_INTERVAL
    elif to_kick <= 3 * HOUR:
        policy, interval = "imminent", IMMINENT_INTERVAL
    elif to_kick <= 36 * HOUR:
        policy, interval = "gameday", GAMEDAY_INTERVAL
    elif to_kick <= DISTANT_HORIZON:
        policy, interval = "upcoming", UPCOMING_INTERVAL
    else:
        policy, interval = "distant", None

    plan = {"policy": policy, "interval_s": interval,
            "frozen": interval is None, "note": REFRESH_NOTE[policy]}
    if interval is not None:
        # An overdue capture is due now, not in the past.
        nxt = max((last_ts if last_ts is not None else now) + interval, now)
        plan["next_ts"] = int(nxt)
        plan["next_at"] = datetime.fromtimestamp(
            plan["next_ts"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return plan


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
    try:
        payload, _ = bdl.bdl_get(f"/games/{game_id}", mode=mode)
    except bdl.BdlError as e:
        if "404" not in str(e):
            raise
        # Almost always the same mistake, and worth naming rather than leaving
        # as a bare 404: ESPN event ids are nine digits beginning with 4
        # (401872657), balldontlie's are seven (1392217). data/nfl_schedule_*.json
        # carried ESPN's until the schedule moved to balldontlie as its source,
        # and ESPN's own URLs still carry them -- so an id copied from either
        # place, or from an older checkout, lands here.
        hint = ""
        if len(str(game_id)) >= 9 and str(game_id).startswith("4"):
            hint = ("\n\nThat looks like an ESPN event id, not a balldontlie one. "
                    "ESPN's are\nnine digits starting with 4; balldontlie's are seven.")
        raise bdl.BdlError(
            f"No balldontlie game {game_id}.{hint}\n\n"
            "Either look the id up in data/nfl_schedule_<season>.json, which "
            "carries\nballdontlie ids now, or skip the id and name the "
            "matchup instead:\n\n"
            "  python3 scripts/fetch_bdl_game.py --season 2026 --week 1 "
            "--away SF --home LAR") from None
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


def norm_venue(name):
    """Casefold, strip accents, drop non-alphanumerics. Same normalization
    scripts/fetch_nfl_schedule.py uses, and for the same reason: without the
    accent strip "Maracanã" and "Bernabéu" compare unequal to themselves across
    feeds and every game at one reads as a venue change."""
    if not name:
        return ""
    name = unicodedata.normalize("NFD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    return "".join(c for c in name.lower() if c.isalnum())


def is_neutral(g, mode):
    """Is this game at neither team's home ground?

    balldontlie ships no neutral-site flag, so it is derived the way the
    schedule fetcher derives it: a team's modal home venue over a full regular
    season is its stadium, and a home game anywhere else is neutral. One extra
    request per bundle, cassetted like the rest.

    The regular season establishes the ground even when the game itself is a
    playoff game -- which is the only way the Super Bowl, always at a neutral
    site, comes out right.
    """
    venue = norm_venue(g.get("venue"))
    home = g.get("home_team") or {}
    if not venue or not home.get("id") or not g.get("season"):
        return False
    try:
        rows = list(bdl.paginate("/games",
                                 {"seasons[]": [g["season"]],
                                  "season_types[]": [REGULAR_SEASON],
                                  "team_ids[]": [home["id"]]},
                                 mode=mode, quiet=True))
    except bdl.BdlError:
        return False
    counts = {}
    for r in rows:
        if (r.get("home_team") or {}).get("id") != home["id"]:
            continue
        v = norm_venue(r.get("venue"))
        if v:
            counts[v] = counts.get(v, 0) + 1
    if not counts:
        return False
    modal = max(counts, key=counts.get)
    return venue != modal


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


# Sections that cannot change once a game has kicked off, and are therefore
# worth carrying forward from the stored bundle instead of re-fetching on every
# sweep. This is not a micro-optimisation: /odds/player_props/opening and
# /player_designations return ~2,800 and ~2,500 rows, and bdl_common.paginate
# walks them 100 at a time, so between them they are ~54 of the ~70 requests a
# capture makes -- roughly 80% of the API budget spent re-reading numbers that
# were fixed before kickoff.
#
# Only ever reused once the game is under way. A pregame sweep must keep
# fetching them: opening lines are still being posted, designations still being
# filed, and a game whose first capture happened after kickoff would otherwise
# carry an emptiness forward for ever.
#
# Two guards on reuse, both of which fall back to fetching rather than to
# writing something wrong:
#   - an empty stored section is never reused, so a game first captured live
#     keeps trying until the rows actually exist;
#   - a stored section captured under a different --books filter is not reused,
#     because it was already narrowed by keep_books and cannot be widened after
#     the fact.
def reusable_static(carry, phase, books):
    """-> dict of the static sections safe to reuse this capture, possibly {}."""
    if not carry or phase == "pregame":
        return {}
    want = sorted(books) if books else None
    if (carry.get("books") or None) != want:
        return {}
    out = {}
    for key in ("odds_opening", "props_opening", "designations"):
        v = carry.get(key)
        if v:                                    # non-empty list or dict only
            out[key] = v
    return out


def build_bundle(g, label, title, mode, books=DEFAULT_BOOKS, carry=None):
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
            "neutral": is_neutral(g, mode),
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
    reuse = reusable_static(carry, phase, books)

    def carried(path, key):
        """Log a reused section the same way try_rows logs a fetched one, so a
        sweep's output still accounts for every section of the bundle."""
        rows = reuse[key]
        n = sum(len(v) for v in rows.values()) if isinstance(rows, dict) else len(rows)
        print(f"  {path:<26} {n:>4} rows  (carried, static once live)")
        return rows

    odds_cur, _ = try_rows("/odds", gp, mode, notes=notes)
    odds_open = (carried("/odds/opening", "odds_opening") if "odds_opening" in reuse
                 else try_rows("/odds/opening", gp, mode, notes=notes)[0])
    props_cur, _ = try_rows("/odds/player_props", props_params, mode, notes=notes)
    props_open = (carried("/odds/player_props/opening", "props_opening")
                  if "props_opening" in reuse
                  else try_rows("/odds/player_props/opening", props_params, mode,
                                notes=notes)[0])
    injuries, _ = try_rows("/player_injuries", tp, mode, notes=notes)

    # /player_designations has no team filter -- season, week and season_types
    # are all it takes -- so the whole slate comes back and the two teams are
    # picked out here.
    designations_split = None
    if "designations" in reuse:
        # Stored already split by side, so it bypasses split() below.
        designations_split = carried("/player_designations", "designations")
        designations = []
    else:
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
    bundle["designations"] = (designations_split if designations_split is not None
                              else split(designations))
    bundle["unavailable"] = notes
    bundle["timing"] = bdl.latency_summary()
    # Stamped last, off the phase this fetch actually observed -- a game that
    # went final during the fetch gets the settling cadence, not the live one.
    bundle["refresh"] = refresh_plan(kickoff.timestamp(), phase,
                                     bundle["fetched_ts"])
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
    elif phase == "live":
        # A game in flight cannot be held to a finished one's arithmetic, and
        # holding it to that is not a cosmetic complaint: bdl_refresh.py gates
        # publishing on this function, so a live bundle that fails here is
        # never written and the page serves its last pregame capture for the
        # whole game.
        #
        # What actually fails mid-game, measured on NE@SEA week 1 2026 rather
        # than assumed: the two count thresholds, and only those. At 7-0 in
        # the second quarter the game had 51 plays against the >=100 the final
        # branch demands, which is the check that blocks publication for most
        # of a game. The >=30 player-stat threshold fails too, but only in the
        # opening minutes -- 4 lines at kickoff, 45 by the second quarter.
        #
        # The other two final-branch checks were verified to hold live and are
        # therefore NOT the reason this branch exists. balldontlie populates
        # the quarter columns as the game runs (q1=0, q2=7 the moment the
        # first touchdown landed), so the quarter-line sum tracks the score
        # mid-game; and the play log's running max matched the reported score
        # on every sample. Kept here anyway, because both are cheap and a live
        # feed that contradicts itself is worth refusing -- but the play-log
        # comparison is relaxed to "never ahead of the score" rather than
        # equality, since /games and /plays are read moments apart and the log
        # may legitimately trail by a possession.
        sc = g["score"]
        if sc is None or sc["away"] is None or sc["home"] is None:
            print("ERROR: a live game has a null score", file=sys.stderr)
            ok = False
        elif bundle["plays"]["count"]:
            rows = bundle["plays"]["all"]
            got = [max((r.get("away_score") or 0) for r in rows),
                   max((r.get("home_score") or 0) for r in rows)]
            # /games and /plays are read moments apart, so the log may trail
            # the score by a possession. Leading it means one of the two is
            # wrong about the same instant, which is worth refusing.
            if got[0] > sc["away"] or got[1] > sc["home"]:
                print(f"ERROR: the play log tops out at {got}, ahead of the "
                      f"{[sc['away'], sc['home']]} the game reports",
                      file=sys.stderr)
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
            # The running score has to reach the final -- but the last row is
            # not where it lands. /plays comes back ordered by play id, and
            # administrative rows sort out of sequence: KC@LAC in week 1 2025
            # ends on a period-1 timeout reading 0-0, three rows after "END
            # GAME" at 21-27. Taking the max over every row is the same
            # assertion with the ordering assumption removed. It held for Super
            # Bowl LX by luck, which is why it was written the other way.
            rows = bundle["plays"]["all"]
            got = [max((r.get("away_score") or 0) for r in rows),
                   max((r.get("home_score") or 0) for r in rows)]
            if got != [sc["away"], sc["home"]]:
                print(f"ERROR: the play log tops out at {got}, game says "
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


def _supabase_creds():
    """-> (url, key), either of which may be empty."""
    return ((os.environ.get("SUPABASE_URL") or "").rstrip("/"),
            os.environ.get("SUPABASE_KEY") or "")


def _stored_injuries(url, key, game_id):
    """-> the stored bundle's injury rows for this game, flat. [] if new.

    `select=data->injuries` rather than `select=data`: the bundle is ~900 KB
    and all but a few of those are player props, and this needs one small
    object out of the middle of it. PostgREST evaluates the arrow server-side,
    so the read costs a few kilobytes.

    A read failure returns [] for the same reason _sections_lost does -- this
    exists to preserve a timestamp, not to stop a publish when Supabase is
    having a bad minute."""
    q = f"{url}/rest/v1/game_odds?game_id=eq.{game_id}&select=data->injuries"
    req = urllib.request.Request(q)
    req.add_header("apikey", key)
    req.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            rows = json.loads(resp.read() or b"[]")
    except Exception:                                        # noqa: BLE001
        return []
    if not rows:
        return []
    stored = rows[0].get("injuries") or {}
    if not isinstance(stored, dict):
        return []
    return [r for v in stored.values() if isinstance(v, list) for r in v]


def carry_injury_dates(bundle):
    """Refill injury dates the feed has stopped sending. -> lines logged.

    /player_injuries answers with two shapes of row and only one of them is
    timestamped. A player first turns up as a wire report -- a written note
    with the hour it was filed -- and is later replaced, in place, by the
    club's own designation: comment "Knee - PCL", date null. Ricky Pearsall
    made that move between two captures four hours apart, and the second one
    overwrote the first, so a report time the bundle already held was gone.

    Nothing recovers it from the API: the endpoint has no as-of parameter and
    no history, and answers only who is hurt right now. The prior capture is
    the only copy, which makes preserving it a job for the writer rather than
    something the page can work around.

    Matched on player and designation together. A date describes the report
    that produced a status, so it survives a comment being rewritten under the
    same designation -- that is the whole case -- and does not survive the
    designation itself changing. A man moved from Questionable to IR has a new
    fact about him and last week's practice report is not its date.

    Read failures and first publishes both no-op: an empty stored list carries
    nothing, and every row keeps the null the feed sent."""
    url, key = _supabase_creds()
    if not url or not key:
        return []
    rows = [r for v in (bundle.get("injuries") or {}).values()
            if isinstance(v, list) for r in v]
    missing = [r for r in rows if not r.get("date")]
    if not missing:
        return []

    prior = {}
    for r in _stored_injuries(url, key, bundle["game"]["id"]):
        pid = (r.get("player") or {}).get("id")
        if pid is None or not r.get("date"):
            continue
        prior[(pid, str(r.get("status") or "").strip().lower())] = r["date"]
    if not prior:
        return []

    carried = []
    for r in missing:
        pid = (r.get("player") or {}).get("id")
        was = prior.get((pid, str(r.get("status") or "").strip().lower()))
        if not was:
            continue
        r["date"] = was
        pl = r.get("player") or {}
        carried.append(f"{pl.get('first_name', '')} {pl.get('last_name', '')}"
                       f" ({r.get('status')}) {was[:10]}".strip())
    if not carried:
        return []
    return [f"Carried {len(carried)} injury date(s) forward from the stored "
            f"bundle: " + ", ".join(carried)]


def _sections_lost(url, key, game_id, has):
    """-> sections the stored row has that this capture does not. [] if new.

    A read failure returns [] rather than raising: the guard exists to stop a
    regression, not to stop a publish when Supabase is having a bad minute --
    the write itself will surface that."""
    q = (f"{url}/rest/v1/game_odds?game_id=eq.{game_id}&select=has")
    req = urllib.request.Request(q)
    req.add_header("apikey", key)
    req.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            rows = json.loads(resp.read() or b"[]")
    except Exception:                                        # noqa: BLE001
        return []
    if not rows:
        return []
    prior = rows[0].get("has") or {}
    return sorted(k for k, v in prior.items() if v and not has.get(k))


def publish(bundle, force=False):
    """Upsert the bundle into Supabase `game_odds`. -> list of log lines.

    Writes straight to PostgREST with the service key from .env rather than
    through an ingest endpoint, which is what build_action.py --seed does and is
    enough here: this script already needs a keyed .env to have fetched anything,
    and there is no second machine pushing game bundles. If that changes, the
    endpoint to add is the api/action-ingest.py shape — an admin-gated PUT.

    The summary columns are duplicated out of the bundle on purpose so the
    listing at /api/game-odds can render without pulling a megabyte per row."""
    url, key = _supabase_creds()
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

    # Read before write. Publishing is an upsert, so a thin capture silently
    # replaces a rich one -- and the way that happens is mundane: the GOAT trial
    # lapses, the key drops to free, /odds and /plays start answering 401, and
    # an unattended refresh sweep overwrites a full bundle with a game-layer
    # shell. `has` is exactly the right comparison because it is what the row
    # already carries and what the listing renders. Same rule the file writers
    # follow, applied to a table.
    if not force:
        lost = _sections_lost(url, key, g["id"], row["has"])
        if lost:
            raise PublishError(
                f"this capture is thinner than what is already published for "
                f"game {g['id']}.\n\n"
                f"  Would lose: {', '.join(lost)}\n\n"
                "  Almost always this means the key that fetched it is below\n"
                "  the tier the stored bundle was fetched on -- an expired GOAT\n"
                "  trial drops /odds, /plays and /player_props to 401, and the\n"
                "  bundle is still valid, just emptier. Refusing to overwrite\n"
                "  good data. Re-run on a key with the tier, or --force if the\n"
                "  thinner bundle really is the one you want.")

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
            f"  /football/schedule/game/{g['id']}"]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--example", choices=sorted(EXAMPLES))
    ap.add_argument("--game-id", type=int,
                    help="balldontlie game id (7 digits) — NOT an ESPN event id")
    # Naming the matchup beats looking an id up, and is the only form that
    # works without already having the schedule file to hand.
    ap.add_argument("--season", type=int)
    ap.add_argument("--week", type=int)
    ap.add_argument("--away", help="team abbreviation, e.g. SF")
    ap.add_argument("--home", help="team abbreviation, e.g. LAR")
    ap.add_argument("--season-type", choices=["pre", "reg", "post"], default="reg")
    ap.add_argument("--label", help="output name; defaults to the example's label")
    ap.add_argument("--books", default=",".join(DEFAULT_BOOKS), metavar="LIST",
                    help="comma-separated sportsbooks to keep "
                         f"(default {','.join(DEFAULT_BOOKS)})")
    ap.add_argument("--all-books", action="store_true",
                    help="keep every book balldontlie quotes")
    ap.add_argument("--raw", action="store_true",
                    help="also write the unshaped rows alongside the bundle")
    ap.add_argument("--force", action="store_true",
                    help="publish even if it would drop sections the stored "
                         "bundle has (see the guard in publish())")
    ap.add_argument("--publish", action="store_true",
                    help="upsert the bundle into Supabase game_odds, which is "
                         "what /game-odds renders — this publishes it")
    bdl.add_mode_args(ap)
    args = ap.parse_args()

    by_matchup = bool(args.season and args.away and args.home)
    if not args.example and not args.game_id and not by_matchup:
        ap.error("give --example, --game-id, or --season with --away and --home")
    mode = bdl.resolve_mode(args)

    spec = dict(EXAMPLES.get(args.example, {}))
    if by_matchup:
        spec.update({
            "season": args.season,
            "season_type": {"pre": 1, "reg": REGULAR_SEASON, "post": POSTSEASON}[
                args.season_type],
            "away": args.away.upper(),
            "home": args.home.upper(),
        })
        if args.week:
            spec["week"] = args.week
        spec.setdefault("label", f"{spec['away']}_{spec['home']}_{args.season}"
                                 + (f"w{args.week}" if args.week else ""))
    label = (args.label or spec.get("label") or f"game_{args.game_id}").lower()
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

    # Before the cache write rather than inside publish(), so the file under
    # cache/ and the row in Supabase are the same bundle byte for byte -- the
    # etag is a hash of it, and a local copy that hashes differently to the
    # published one is a debugging trap. Only when publishing: there is nothing
    # to carry forward from unless a stored bundle exists.
    if args.publish:
        for line in carry_injury_dates(bundle):
            print(f"\n{line}")

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
            for line in publish(bundle, force=args.force):
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
