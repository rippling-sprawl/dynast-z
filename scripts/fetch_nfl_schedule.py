#!/usr/bin/env python3
"""
Fetch a full NFL regular season and save to data/nfl_schedule_{season}.json.

Why this source
---------------
balldontlie, since 2026-09-06. One paginated crawl replaces ESPN's eighteen
weekly GETs:

    https://api.balldontlie.io/nfl/v1/games
        ?seasons[]={season}&season_types[]=2&per_page=100      (3 pages, 272 games)

The switch is not about the schedule, which ESPN served fine. It is that
everything downstream of a schedule — live score, box score, plays, odds, props
— is on this one key, under a ToS (§6) that expressly permits caching, storing
and building derivative databases for "lawful sportsbook and wagering products".
ESPN's equivalent data is free and complete but the Disney Terms of Use ban
automated access, database building, and business use outright; the same
objection that disqualified Pro Football Reference. See
docs/research/nfl-live-data-apis.md for the full survey.

The two feeds were compared game-for-game across the 2026 season before the
switch: 272 games, keys matched on (week, away, home), zero differences in
kickoff, slot or neutral-site classification. The only divergence was `venue`,
where balldontlie carries stale stadium names — see VENUE_ALIAS.

The ESPN parser is kept behind --source espn. It is the oracle --compare
validates against, and it is the fallback if the key ever lapses.

Two fields ESPN gave us directly have to be derived here:

  neutral   balldontlie ships no neutral-site flag. A team's modal home venue
            across its 8-9 home games is its stadium; a home game anywhere else
            is neutral. Cross-checked against KNOWN_NEUTRAL_VENUES, and a
            disagreement between the two refuses to write.
  tbd       ESPN flagged flex games with timeValid: false. balldontlie is more
            explicit — status reads literally "TBD" — and parks them at midnight
            ET exactly as ESPN did, so either signal alone would do.

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

    # validate against the file already on disk; writes nothing
    python3 scripts/fetch_nfl_schedule.py --season 2026 --compare
    python3 scripts/fetch_nfl_schedule.py --season 2026 --dry-run
    python3 scripts/fetch_nfl_schedule.py --season 2026 --source espn
    python3 scripts/fetch_nfl_schedule.py --season 2026 --replay   # from cassettes
"""

import argparse
import collections
import json
import os
import subprocess
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bdl_common as bdl  # noqa: E402

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

# Two stadiums whose names both feeds get wrong. This is not a balldontlie
# correction: ESPN returned the good names when this file was first generated on
# 2026-08-19 and returns the stale ones now, so the alias is applied to either
# source. Houston's ground has been NRG Stadium since 2014, and GEHA Field is
# Kansas City's current sponsored name. Nothing renders these — the view only
# prints a venue for a neutral-site game — but the file should still be right.
VENUE_ALIAS = {
    "Reliant Stadium": "NRG Stadium",                                # renamed 2014
    "Arrowhead Stadium": "GEHA Field at Arrowhead Stadium",          # sponsor, 2021
}

# Buffalo opened a new Highmark Stadium in 2026 and both feeds call it
# "Highmark Stadium". ESPN disambiguates the old one retroactively, balldontlie
# does not — so this correction only applies to seasons played in the old
# ground, and applying it globally would rename the new stadium.
VENUE_ALIAS_BY_SEASON = {
    2025: {"Highmark Stadium": "Highmark Stadium (Old)"},
}

# The backstop for the modal-venue rule below. Substrings, matched against the
# normalized venue, covering every ground the league has used for an
# international or neutral-site game. This does not decide anything on its own:
# it only has to agree with the modal rule, and a disagreement is a hard error.
KNOWN_NEUTRAL_VENUES = (
    "wembley", "tottenham", "twickenham",           # London
    "allianz", "bayern", "munich", "deutschebank",  # Munich, Frankfurt
    "olympiastadion", "olympicstadium",             # Berlin, spelled both ways
    "bernabeu", "estadiobanorte", "azteca",         # Madrid, Mexico City
    "maracana", "corinthians",                      # Brazil
    "stadedefrance",                                # Paris
    "melbournecricket",                             # Australia
    "crokepark", "aviva",                           # Dublin
)


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


def norm_venue(name):
    """Casefold, strip accents, drop everything that is not alphanumeric.

    Without the accent strip, "Maracanã" and "Estadio Bernabéu" compare unequal
    to themselves across feeds, and every game at one would be misread as a
    venue change — i.e. as a neutral site."""
    if not name:
        return ""
    name = unicodedata.normalize("NFD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    return "".join(c for c in name.lower() if c.isalnum())


def parse_bdl_date(s):
    """balldontlie sends a full UTC instant: "2026-09-10T00:20:00.000Z".

    Minute precision is load-bearing — classify() buckets on the ET wall clock,
    so a date-only value would silently make every game a midnight game and
    therefore `tbd`. Refuse rather than guess."""
    t = (s or "").strip()
    if "T" not in t:
        raise RuntimeError(f"balldontlie date {s!r} has no time component; "
                           f"slot classification needs minutes")
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise RuntimeError(f"unparseable balldontlie date {s!r}")
    if dt.tzinfo is None:
        raise RuntimeError(f"balldontlie date {s!r} carries no timezone")
    return dt.astimezone(timezone.utc)


def build_bdl(season, mode="auto"):
    """-> (weeks, teams, conflicts). One crawl, then a second pass for neutral
    sites, which can only be decided once every game of the season is in hand."""
    venue_alias = dict(VENUE_ALIAS)
    venue_alias.update(VENUE_ALIAS_BY_SEASON.get(season, {}))
    by_abbr, _ = bdl.team_index(mode=mode)
    teams = {t["abbreviation"]: {"abbr": t["abbreviation"],
                                 "name": t["full_name"],
                                 "short": t["name"]}
             for t in by_abbr.values()}

    rows = list(bdl.paginate("/games",
                             {"seasons[]": [season], "season_types[]": [REGULAR_SEASON]},
                             mode=mode, quiet=True))
    print(f"  {len(rows)} games returned")

    missing_week = [g["id"] for g in rows if not g.get("week")]
    if missing_week:
        raise RuntimeError(f"{len(missing_week)} games have no week "
                           f"(e.g. id {missing_week[0]}); week is the file's structure")

    # A team is home 8 or 9 times a season, so the mode of its home venues is
    # its stadium by a wide margin. Shared grounds are safe — MetLife is the mode
    # for both NYG and NYJ, SoFi for both LAR and LAC — and a club playing a
    # whole season somewhere temporary gets that ground as its mode, which is the
    # right answer: those games are a relocation, not a neutral site.
    home_venues = collections.defaultdict(collections.Counter)
    for g in rows:
        home_venues[g["home_team"]["abbreviation"]][norm_venue(g.get("venue"))] += 1
    modal = {t: c.most_common(1)[0][0] for t, c in home_venues.items()}

    by_week = collections.defaultdict(list)
    conflicts = []
    for g in rows:
        away = g["visitor_team"]["abbreviation"]
        home = g["home_team"]["abbreviation"]
        kickoff = parse_bdl_date(g["date"])

        # Two independent signals, either of which is sufficient. ESPN only had
        # the midnight-ET placeholder; balldontlie says so in words as well.
        status = (g.get("status") or "").strip().upper()
        placeholder = kickoff.astimezone(ET).strftime("%H:%M") == "00:00"
        time_valid = not (status == "TBD" or placeholder)

        venue = g.get("venue")
        vkey = norm_venue(venue)
        by_modal = vkey != modal.get(home, vkey)
        by_name = any(tok in vkey for tok in KNOWN_NEUTRAL_VENUES)
        if by_modal != by_name:
            conflicts.append((g.get("week"), away, home, venue, by_modal, by_name))

        game = {
            "id": str(g["id"]),
            "kickoff": iso(kickoff),
            "slot": classify(kickoff, time_valid),
            "away": away,
            "home": home,
            "venue": venue_alias.get(venue, venue),
        }
        if by_modal:
            game["neutral"] = True

        # status_state is the gate, not the presence of a number: a scheduled
        # game already carries null scores and a live one carries real ones that
        # are not final. Away first, then home — the order the row reads them in.
        if (g.get("status_state") or "").lower() == "final":
            av, hv = g.get("visitor_team_score"), g.get("home_team_score")
            if av is not None and hv is not None:
                game["score"] = [int(av), int(hv)]

        by_week[g["week"]].append(game)

    weeks = []
    for wk in sorted(by_week):
        games = sorted(by_week[wk], key=lambda g: (g["kickoff"], g["away"]))
        start, end = week_bounds(games)
        weeks.append({"week": wk, "start": iso(start), "end": iso(end), "games": games})
        slots = collections.Counter(g["slot"] for g in games)
        print(f"  week {wk:>2}: {len(games):>2} games  "
              f"({', '.join(f'{v} {k}' for k, v in sorted(slots.items()))})")

    return weeks, teams, conflicts


def build_espn(season):
    venue_alias = dict(VENUE_ALIAS)
    venue_alias.update(VENUE_ALIAS_BY_SEASON.get(season, {}))
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
            if game.get("venue") in venue_alias:
                game["venue"] = venue_alias[game["venue"]]
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


def verify(weeks, teams, conflicts=()):
    ok = True
    total = sum(len(w["games"]) for w in weeks)

    # The modal-venue rule and the named-venue list have to agree. Either one
    # alone would be a guess; together they are a check, and a mismatch means a
    # game is about to be written with the wrong home team or the wrong "@".
    if conflicts:
        print(f"ERROR: {len(conflicts)} games where the modal-venue rule and "
              f"KNOWN_NEUTRAL_VENUES disagree:", file=sys.stderr)
        for wk, away, home, venue, by_modal, by_name in conflicts[:10]:
            print(f"  week {wk} {away}@{home} at {venue!r}: "
                  f"modal says {by_modal}, name list says {by_name}", file=sys.stderr)
        ok = False

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


DIFF_FIELDS = ("kickoff", "slot", "venue", "neutral", "score")


def flatten(doc):
    """-> {(week, away, home): {field: value}}.

    Keyed on the matchup, never on `id`: the whole point of --compare is to run
    across a source change, and the ids are the one field guaranteed to differ."""
    out = {}
    for w in doc["weeks"]:
        for g in w["games"]:
            out[(w["week"], g["away"], g["home"])] = {
                "kickoff": g.get("kickoff"), "slot": g.get("slot"),
                "venue": g.get("venue"), "neutral": bool(g.get("neutral")),
                "score": g.get("score"),
            }
    return out


def compare(new_doc, ref_path):
    """-> True when the two agree everywhere that matters. Writes nothing."""
    if not os.path.exists(ref_path):
        print(f"ERROR: no reference file at {ref_path}", file=sys.stderr)
        return False
    with open(ref_path) as f:
        ref_doc = json.load(f)

    new, ref = flatten(new_doc), flatten(ref_doc)
    print(f"\nComparing against {os.path.relpath(ref_path, repo_path())}")
    print(f"  reference {len(ref)} games, generated {len(new)} games")

    ok = True
    only_ref = sorted(set(ref) - set(new))
    only_new = sorted(set(new) - set(ref))
    for label, missing in (("missing from generated", only_ref), ("not in reference", only_new)):
        if missing:
            ok = False
            print(f"  ERROR: {len(missing)} games {label}:", file=sys.stderr)
            for k in missing[:8]:
                print(f"    week {k[0]} {k[1]}@{k[2]}", file=sys.stderr)

    diffs = collections.defaultdict(list)
    for k in sorted(set(ref) & set(new)):
        for field in DIFF_FIELDS:
            if ref[k][field] != new[k][field]:
                diffs[field].append((k, ref[k][field], new[k][field]))

    if not diffs:
        print("  no differences in " + ", ".join(DIFF_FIELDS))
    for field, rows in sorted(diffs.items()):
        print(f"  {field}: {len(rows)} differences", file=sys.stderr)
        for k, was, now_ in rows[:10]:
            print(f"    week {k[0]} {k[1]}@{k[2]}: {was!r} -> {now_!r}", file=sys.stderr)
        if len(rows) > 10:
            print(f"    ... and {len(rows) - 10} more", file=sys.stderr)
        ok = False

    # The strong form of the check. Substitute the reference ids into the
    # generated document — they are the only field expected to differ — and the
    # two should then serialize to the same string. That proves the contract is
    # preserved down to key order and value types, which a field-by-field diff
    # of the five fields above does not.
    ref_ids = {}
    for w in ref_doc["weeks"]:
        for g in w["games"]:
            ref_ids[(w["week"], g["away"], g["home"])] = g["id"]
    swapped = json.loads(json.dumps(new_doc))
    for w in swapped["weeks"]:
        for g in w["games"]:
            g["id"] = ref_ids.get((w["week"], g["away"], g["home"]), g["id"])
    a = json.dumps(swapped, sort_keys=True)
    b = json.dumps(ref_doc, sort_keys=True)
    if a == b:
        print("  identical to the reference once ids are substituted")
    else:
        print(f"  NOTE: documents still differ after id substitution "
              f"({len(a)} vs {len(b)} bytes serialized) — check teams[] and week windows")

    print("\nCOMPARE PASSED" if ok else "\nCOMPARE FAILED", file=sys.stderr if not ok else sys.stdout)
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    # A season is named for the year it starts, and next season's schedule is
    # published each May — so from January through April the current season is
    # still last year's.
    now = datetime.now(timezone.utc)
    ap.add_argument("--season", type=int,
                    default=now.year if now.month >= 5 else now.year - 1)
    ap.add_argument("--source", choices=["bdl", "espn"], default="bdl",
                    help="bdl (default) or the legacy ESPN scoreboard")
    ap.add_argument("--compare", nargs="?", const=True, default=None,
                    metavar="PATH",
                    help="diff against an existing schedule file (default: the one "
                         "for this season) and write nothing")
    ap.add_argument("--dry-run", action="store_true",
                    help="verify and report, but do not write")
    bdl.add_mode_args(ap)
    args = ap.parse_args()

    conflicts = ()
    if args.source == "espn":
        print(f"Fetching the {args.season} NFL regular-season schedule from ESPN\n")
        weeks, teams = build_espn(args.season)
        source, source_url = "ESPN", (
            f"{SCOREBOARD}?dates={args.season}&seasontype={REGULAR_SEASON}&week={{week}}")
    else:
        mode = bdl.resolve_mode(args)
        print(f"Fetching the {args.season} NFL regular-season schedule from "
              f"balldontlie (mode={mode})\n")
        try:
            weeks, teams, conflicts = build_bdl(args.season, mode=mode)
        except bdl.BdlError as e:
            print(f"\n{e}", file=sys.stderr)
            return 1
        source, source_url = "balldontlie", (
            f"{bdl.API_BASE}/games?seasons[]={args.season}"
            f"&season_types[]={REGULAR_SEASON}&per_page=100")

    ok, total, slots, scored = verify(weeks, teams, conflicts)
    if not ok:
        print("\nRefusing to overwrite good data.", file=sys.stderr)
        return 1

    out = {
        "season": args.season,
        "timezone": "America/New_York",
        "teams": [teams[a] for a in sorted(teams)],
        "weeks": weeks,
    }

    if args.compare is not None:
        ref = (args.compare if isinstance(args.compare, str)
               else repo_path("data", f"nfl_schedule_{args.season}.json"))
        return 0 if compare(out, ref) else 1

    if args.dry_run:
        print("\n--dry-run: verified, nothing written")
        return 0

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
            "source": source,
            "url": source_url,
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
