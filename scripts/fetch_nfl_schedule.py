#!/usr/bin/env python3
"""
Fetch a full NFL regular season and save to data/nfl_schedule_{season}.json.

Why this source
---------------
ESPN's public scoreboard endpoint is the simplest schedule feed that exists: no
key, no auth, no scraping of HTML, and one plain GET per week.

    https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard
        ?dates={season}&seasontype=2&week={week}

seasontype=2 is the regular season (1 = pre, 3 = post). Eighteen requests cover
it — 272 games. The alternative sources are all worse for this: nflverse ships
CSVs but lags the release, the NFL's own shield API needs a rotating token, and
anything HTML-based breaks on the next redesign.

One file per season, because the views show more than one: the team card on
/football/bakers-buns puts last season beside this one, and re-running with a
different --season used to clobber the file it had just written.

What is kept is who plays whom, when, where, and — for a game that has already
finished — the final score. Live status is deliberately dropped: this file is
committed and served from the CDN with an hour of cache, so anything in it has
to be a thing that does not change on a timescale of minutes. A schedule does
change (flex), but on a timescale of weeks; a final score never does. Re-run
this script when a week gets flexed, and once after a season ends to fill in the
last of its scores — after that its file is static forever.

Kickoff slots
-------------
Every game is bucketed into `regular` or `odd`, in US Eastern — the timezone the
league schedules in, and the only one where the windows land on round numbers:

    regular     Sunday, 12:00-17:59 ET     the 1:00 and 4:05/4:25 slates
    odd         everything else            every non-Sunday game, plus the
                                           Sunday 9:30am international kickoffs
                                           and Sunday night
    tbd         no kickoff time yet        flex-scheduled late-season games

`regular` is the default case and the overwhelming majority of the season (181
of 272 games), so it is the absence of a marker on the page — only `odd` is
worth printing.

Two rules, in order. A game not on a Sunday is odd, full stop: Thursday night,
Monday night and the Thanksgiving / Christmas / Saturday standalones are each a
window of their own whatever the clock says, which is why hour alone can't
decide it — the Thanksgiving games kick at 1:00 and 4:30pm ET and are anything
but routine. A Sunday game is regular only inside the two afternoon slates,
which leaves the 9:30am international window and the night game as odd.

Usage:
    python3 scripts/fetch_nfl_schedule.py              # current season
    python3 scripts/fetch_nfl_schedule.py --season 2026
    python3 scripts/fetch_nfl_schedule.py --season 2025   # last season, with scores
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"

# The league schedules in Eastern and always has. Every slot boundary below is
# an ET wall-clock time, so the classification has to happen in ET regardless of
# where this script runs or where the page is later read.
ET = ZoneInfo("America/New_York")

REGULAR_SEASON = 2
WEEKS = range(1, 19)

# datetime.weekday(): Monday is 0, so Sunday is 6.
SUNDAY = 6

# A modern regular season is 18 weeks x 16 games less the byes = 272, and 32
# teams play 17 apiece. Anything short of these means a week failed to parse and
# must not overwrite a good file.
EXPECTED_GAMES = 272
EXPECTED_TEAMS = 32
GAMES_PER_TEAM = 17


def curl_fetch(url):
    """DO NOT ADD A BROWSER User-Agent HERE.

    This is the exact opposite of fetch_nfl_weekly.py, which needs one: Sleeper
    403s curl's default UA, and ESPN 403s a Chrome UA (their bot filter reads a
    desktop-browser string hitting a JSON API as a scraper and serves an Akamai
    "Access Denied" page). Curl's own default sails through. Copying the UA line
    over from the sibling script turns all 18 requests into an HTML error page
    and the only symptom is a JSON parse failure on line 1."""
    result = subprocess.run(
        ["curl", "-s", "--max-time", "30", url],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"curl failed for {url}: {result.stderr.strip()}")
    body = result.stdout.strip()
    if not body:
        raise RuntimeError(f"empty response for {url}")
    try:
        return json.loads(body)
    except ValueError:
        raise RuntimeError(f"non-JSON response for {url}: {body[:200]}")


def repo_path(*parts):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", *parts)


def parse_kickoff(s):
    """ESPN dates are UTC, minute precision, e.g. "2026-09-10T00:20Z"."""
    return datetime.strptime(s, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)


def classify(kickoff_utc, time_valid):
    """-> "regular" | "odd" | "tbd". See the module docstring."""
    if not time_valid:
        return "tbd"
    et = kickoff_utc.astimezone(ET)
    if et.weekday() != SUNDAY:
        return "odd"
    return "regular" if 12 <= et.hour < 18 else "odd"


def final_score(comp, away_score, home_score):
    """-> [away, home] for a finished game, else None.

    ESPN sends the score as a string on every competitor from the moment the
    event exists — "0" for a game that has not kicked off. So the number alone
    says nothing; the gate is status.type.completed, which is only true once the
    game is final. Anything that fails to parse as an integer is treated as no
    score rather than as a zero.
    """
    status = (comp.get("status") or {}).get("type") or {}
    if not status.get("completed"):
        return None
    try:
        return [int(away_score), int(home_score)]
    except (TypeError, ValueError):
        return None


def parse_event(ev):
    comps = ev.get("competitions") or []
    if not comps:
        return None
    comp = comps[0]

    home = away = None
    home_score = away_score = None
    for c in comp.get("competitors") or []:
        team = c.get("team") or {}
        abbr = team.get("abbreviation")
        if not abbr:
            continue
        entry = (abbr, team.get("displayName") or abbr, team.get("shortDisplayName") or abbr)
        if c.get("homeAway") == "home":
            home, home_score = entry, c.get("score")
        elif c.get("homeAway") == "away":
            away, away_score = entry, c.get("score")
    if not home or not away:
        return None

    kickoff = parse_kickoff(ev["date"])
    # ESPN parks a not-yet-scheduled game at midnight ET and flags it with
    # timeValid: false. Trusting the timestamp would print "12:00 AM" for every
    # flex game in weeks 16-18 as though that were a real kickoff.
    time_valid = bool(comp.get("timeValid"))
    venue = comp.get("venue") or {}

    game = {
        "id": ev.get("id"),
        "kickoff": ev["date"],
        "slot": classify(kickoff, time_valid),
        "away": away[0],
        "home": home[0],
        "venue": venue.get("fullName"),
    }
    # Only carried when true, to keep the file small — it's the flag the view
    # uses to mark the six international games and the Melbourne opener.
    if comp.get("neutralSite"):
        game["neutral"] = True

    # Away first, then home — the order the row reads them in ("NE @ SEA",
    # "17-31"), so the view never has to reorder and can never silently invert
    # them. Only for a finished game: a game in progress has a score too, and
    # that one is a live number this file has no business carrying.
    final = final_score(comp, away_score, home_score)
    if final:
        game["score"] = final

    return game, {t[0]: {"abbr": t[0], "name": t[1], "short": t[2]} for t in (home, away)}


def week_bounds(games):
    """The window a week "is current" for, as absolute UTC instants.

    Anchored to ET calendar days rather than to the first and last kickoff:
    start is midnight ET on the day of the earliest game, end is midnight ET the
    day after the latest. That gives the conventional NFL week — it opens on the
    Thursday (or the Wednesday, in Thanksgiving week) and closes when Monday
    night ends, with the flip falling on Tuesday, the one day of the week that
    never has a game. Kickoff-to-kickoff bounds would instead flip the page mid
    Monday-night-game, and would be meaningless for the flex weeks where several
    kickoffs are still TBD.
    """
    days = [parse_kickoff(g["kickoff"]).astimezone(ET).date() for g in games]
    start = datetime.combine(min(days), datetime.min.time(), tzinfo=ET)
    end = datetime.combine(max(days) + timedelta(days=1), datetime.min.time(), tzinfo=ET)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%MZ")


def build(season):
    weeks = []
    teams = {}

    for wk in WEEKS:
        url = f"{SCOREBOARD}?dates={season}&seasontype={REGULAR_SEASON}&week={wk}"
        doc = curl_fetch(url)
        events = doc.get("events") or []

        games = []
        for ev in events:
            parsed = parse_event(ev)
            if parsed is None:
                print(f"  WARNING: week {wk} event {ev.get('id')} unparseable", file=sys.stderr)
                continue
            game, seen = parsed
            games.append(game)
            teams.update(seen)

        if not games:
            raise RuntimeError(f"week {wk} returned no usable games — feed shape moved")

        games.sort(key=lambda g: (g["kickoff"], g["away"]))
        start, end = week_bounds(games)
        weeks.append({"week": wk, "start": iso(start), "end": iso(end), "games": games})

        slots = {}
        for g in games:
            slots[g["slot"]] = slots.get(g["slot"], 0) + 1
        print(f"  week {wk:>2}: {len(games):>2} games  "
              f"({', '.join(f'{v} {k}' for k, v in sorted(slots.items()))})")
        time.sleep(0.2)   # 18 requests at a human pace; ESPN has no documented limit

    return weeks, teams


def verify(weeks, teams):
    ok = True
    total = sum(len(w["games"]) for w in weeks)

    print(f"\n{total} games across {len(weeks)} weeks, {len(teams)} teams")
    if total != EXPECTED_GAMES:
        print(f"ERROR: expected {EXPECTED_GAMES} games, got {total}.", file=sys.stderr)
        ok = False
    if len(teams) != EXPECTED_TEAMS:
        print(f"ERROR: expected {EXPECTED_TEAMS} teams, got {len(teams)}.", file=sys.stderr)
        ok = False

    # Each team plays 17 games and appears at most once a week. A team appearing
    # twice in one week is a duplicated event, which the view would render as two
    # games and no bye.
    counts = {}
    for w in weeks:
        seen = set()
        for g in w["games"]:
            for abbr in (g["away"], g["home"]):
                counts[abbr] = counts.get(abbr, 0) + 1
                if abbr in seen:
                    print(f"ERROR: {abbr} appears twice in week {w['week']}", file=sys.stderr)
                    ok = False
                seen.add(abbr)
    wrong = {t: n for t, n in counts.items() if n != GAMES_PER_TEAM}
    if wrong:
        print(f"ERROR: teams not playing {GAMES_PER_TEAM} games: {wrong}", file=sys.stderr)
        ok = False

    # The week windows drive the view's "which week is it now?" default. If two
    # overlapped, that default would be ambiguous.
    for a, b in zip(weeks, weeks[1:]):
        if a["end"] > b["start"]:
            print(f"ERROR: week {a['week']} ends after week {b['week']} starts "
                  f"({a['end']} > {b['start']})", file=sys.stderr)
            ok = False

    slots = {}
    for w in weeks:
        for g in w["games"]:
            slots[g["slot"]] = slots.get(g["slot"], 0) + 1
    print("Slots: " + ", ".join(f"{k} {v}" for k, v in sorted(slots.items())))
    if not slots.get("odd") or not slots.get("regular"):
        print("ERROR: one of the two slot buckets is empty — the ET classification "
              "is not doing anything.", file=sys.stderr)
        ok = False

    # The rule the page leans on hardest: no non-Sunday game may be `regular`,
    # because the page prints nothing at all for a regular game and a Thursday
    # nighter rendered bare would read as a 1:00 Sunday afternoon game.
    for w in weeks:
        for g in w["games"]:
            if g["slot"] != "regular":
                continue
            et = parse_kickoff(g["kickoff"]).astimezone(ET)
            if et.weekday() != SUNDAY:
                print(f"ERROR: non-Sunday game marked regular: week {w['week']} "
                      f"{g['away']}@{g['home']} {et:%a %H:%M} ET", file=sys.stderr)
                ok = False

    # Scores are not an error either way — a season that has not started has
    # none and a finished one has all of them, and both are files worth writing.
    # Only the in-between is worth saying out loud, because a season fetched
    # mid-way ships a file that is half results and half fixtures, and whoever
    # runs this in January should know they will want to run it again.
    scored = sum(1 for w in weeks for g in w["games"] if g.get("score"))
    if scored == 0:
        print("Scores: none — no game has finished yet")
    elif scored == total:
        print(f"Scores: all {total} games final")
    else:
        print(f"Scores: {scored} of {total} final — season in progress, "
              f"re-run once it ends", file=sys.stderr)

    return ok, total, slots, scored


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    # A season is named for the year it starts, and next season's schedule is
    # published each May — so from January through April the current season is
    # still last year's.
    now = datetime.now(timezone.utc)
    ap.add_argument("--season", type=int,
                    default=now.year if now.month >= 5 else now.year - 1)
    args = ap.parse_args()

    print(f"Fetching the {args.season} NFL regular-season schedule from ESPN\n")
    weeks, teams = build(args.season)

    ok, total, slots, scored = verify(weeks, teams)
    if not ok:
        print("\nRefusing to overwrite good data.", file=sys.stderr)
        return 1

    out = {
        "season": args.season,
        "timezone": "America/New_York",
        "teams": [teams[a] for a in sorted(teams)],
        "weeks": weeks,
    }

    data_dir = repo_path("data")
    os.makedirs(data_dir, exist_ok=True)

    # One file per season, named for it. The views know which seasons exist from
    # SCHED_SEASONS in scripts/components/nfl-schedule.js — add a season here and
    # it has to be added there too.
    out_path = os.path.join(data_dir, f"nfl_schedule_{args.season}.json")
    with open(out_path, "w") as f:
        # Compact: this ships to every schedule page load.
        json.dump(out, f, separators=(",", ":"))
    size_kb = os.path.getsize(out_path) / 1024
    print(f"\nWrote {total} games to {os.path.abspath(out_path)} ({size_kb:.0f} KB)")

    meta_path = os.path.join(data_dir, f"nfl_schedule_{args.season}_meta.json")
    with open(meta_path, "w") as f:
        json.dump({
            "source": "ESPN",
            "url": f"{SCOREBOARD}?dates={args.season}&seasontype={REGULAR_SEASON}&week={{week}}",
            "season": args.season,
            "weeks": len(weeks),
            "game_count": total,
            "team_count": len(teams),
            "scored_count": scored,
            "slots": slots,
            "size_bytes": os.path.getsize(out_path),
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "fetched_ts": int(time.time()),
        }, f, indent=2)
    print(f"Wrote metadata to {os.path.abspath(meta_path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
