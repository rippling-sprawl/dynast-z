#!/usr/bin/env python3
"""
Freeze the Pick 'Em lines, and grade the games that have finished.

Why this exists
---------------
/football/pickem grades every pick against the spread, and the whole point of
the spread is that it is the *same* number for everybody all week. Lines move
constantly -- scripts/bdl_refresh.py re-captures them as often as every two
minutes during a live game -- so a pick'em that read the current line would be
grading Sunday's picks against a number that had moved four times since anyone
made them.

So the line is frozen once, at Tuesday 3:00am ET, before that week's board
opens, and stored in `pickem_games` where nothing overwrites it. That table is
also where a finished game's score and its ATS verdict land, so the standings
are current on the next request with no deploy -- the same push-not-deploy split
game_odds and action_pages use (ARCHITECTURE.md).

Two phases, both idempotent, both run on every invocation
---------------------------------------------------------
  freeze  Has the most recent Tuesday-3am deadline passed, and is the week it
          opens still unfrozen? Then capture /odds for that week's games and
          write the consensus. Otherwise do nothing.
  grade   Any game on the board that is final and has no verdict yet? Write its
          score and its ATS result. Otherwise do nothing.

Neither phase asks what time the job was *started*, which matters because it is
run from a GitHub schedule and those drift five to fifteen minutes and sometimes
skip a slot entirely. The deadline is computed from the clock, the work is
whatever is outstanding against it, and a run that fires late still does exactly
the right thing. `frozen_at` is what makes a re-run free: a week that already
has it is skipped in Python before a single balldontlie request is made.

DST is handled by asking zoneinfo rather than by arithmetic: 3:00am ET is 07:00Z
for half the year and 08:00Z for the other half, and 3:00am is never itself
inside a transition (those happen at 02:00 on a Sunday), so there is no
ambiguous or non-existent local time to disambiguate.

The line itself
---------------
balldontlie returns one row per sportsbook. The consensus is the *modal* value
across a fixed allowlist of real books, ties broken by book priority -- never
the mean, because an even -7.5/-8 split averages to -7.75, a quarter line no
book posted, and quietly makes a push impossible. The mode always yields a
number somebody actually hung. Every book's row is kept in `data.books` so any
disagreement is re-derivable, and `data.consensus.rule` versions the rule.

Usage:
    python3 scripts/pickem_capture.py --dry-run
    python3 scripts/pickem_capture.py                      # freeze + grade
    python3 scripts/pickem_capture.py --week 3 --force     # re-freeze one week
    python3 scripts/pickem_capture.py --grade-only --season 2025
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "api"))
import bdl_common as bdl                     # noqa: E402
from _pickem import scoring                  # noqa: E402

ET = ZoneInfo("America/New_York")

# Tuesday, 03:00 local. Monday=0 in weekday(), so Tuesday is 1.
FREEZE_WEEKDAY = 1
FREEZE_HOUR = 3

# Real sportsbooks, in the order that breaks a tie. kalshi and polymarket are
# deliberately absent: they are prediction markets, and the "spread" they report
# is a construct derived from their contract prices rather than a line anyone
# posted. Grading somebody's week against a synthesised number is not defensible
# even on the weeks it happens to agree with the books.
BOOKS = ("draftkings", "fanduel", "betmgm", "caesars", "fanatics", "betrivers")

CONSENSUS_RULE = "mode-priority-v1"


class CaptureError(RuntimeError):
    """Message is written to be shown verbatim."""


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------

def freeze_deadline(now):
    """The most recent Tuesday 03:00 America/New_York at or before `now`, in UTC.

    Computed in local time and converted, not the other way round, so the answer
    is 07:00Z through the summer and 08:00Z through the winter without this
    function ever naming either number.
    """
    local = now.astimezone(ET)
    candidate = (local.replace(hour=FREEZE_HOUR, minute=0, second=0, microsecond=0)
                 - timedelta(days=(local.weekday() - FREEZE_WEEKDAY) % 7))
    if candidate > local:
        candidate -= timedelta(days=7)
    return candidate.astimezone(timezone.utc)


def season_for(now):
    """March onward is that calendar year's season. Same rule as bdl_refresh."""
    return now.year if now.month >= 3 else now.year - 1


def parse_ts(value):
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    stamp = datetime.fromisoformat(text)
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def iso(stamp):
    return stamp.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z") if stamp else None


# ---------------------------------------------------------------------------
# Supabase
# ---------------------------------------------------------------------------

def creds():
    url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_KEY") or ""
    if not url or not key:
        raise CaptureError(
            "SUPABASE_URL and SUPABASE_KEY are needed to read or write the\n"
            "  Pick 'Em board. Add them to .env, or run with --dry-run.")
    return url, key


def supabase(path, method="GET", body=None, headers=None):
    url, key = creds()
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{url}/rest/v1/{path}", data=data, method=method)
    req.add_header("apikey", key)
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        if "PGRST205" in detail or ("pickem_" in detail and e.code in (400, 404)):
            ref = url.split("//")[-1].split(".")[0]
            raise CaptureError(
                "The pickem_games / pickem_picks tables do not exist yet.\n\n"
                "  Run scripts/sql/pickem_games.sql and scripts/sql/pickem_picks.sql\n"
                "  once each, in the SQL editor at\n"
                f"  https://supabase.com/dashboard/project/{ref}/sql/new\n\n"
                "  Then re-run this command.")
        raise CaptureError(f"Supabase {method} failed ({e.code}): {detail}")


# ---------------------------------------------------------------------------
# balldontlie
# ---------------------------------------------------------------------------

def season_games(season, mode="auto"):
    """Every regular-season game, from the API rather than the committed
    schedule file. That is the point: a flexed game or a schedule correction
    lands here without anybody having to run fetch_nfl_schedule.py, commit and
    deploy first, which is the dependency the whole feature is built to avoid."""
    rows = list(bdl.paginate("/games", {"seasons[]": [season],
                                        "season_types[]": [2]}, mode=mode))
    return [g for g in rows if not g.get("postseason")]


def week_odds(game_ids, mode="auto"):
    """-> {game_id: [odds row, ...]} for a whole slate.

    One request for the week where the per-game fetcher makes sixteen: /odds
    takes game_ids[] as a list (scripts/fetch_bdl_game.py builds the same
    parameter). Falls back to per-game requests if the batch comes back short,
    because the endpoint's parameter handling is documented wrongly upstream and
    the running API is the only authority on it -- see the note at
    fetch_bdl_game.py's own /odds call.
    """
    wanted = [int(g) for g in game_ids]
    found = {}
    for row in bdl.paginate("/odds", {"game_ids[]": wanted}, mode=mode):
        found.setdefault(int(row["game_id"]), []).append(row)

    missing = [g for g in wanted if g not in found]
    if missing and len(missing) < len(wanted):
        # A partial answer means the batch worked and those games genuinely have
        # no line yet. Nothing to retry.
        return found
    for game_id in missing:
        for row in bdl.paginate("/odds", {"game_ids[]": [game_id]}, mode=mode):
            found.setdefault(int(row["game_id"]), []).append(row)
    return found


def opening_odds(game_id, mode="auto"):
    try:
        return list(bdl.paginate("/odds/opening", {"game_ids[]": [game_id]}, mode=mode))
    except bdl.BdlError:
        return []


def consensus(rows):
    """-> (spread_home, workings). spread_home is None when no allowlisted book
    posted a spread, which takes the game off the board rather than grading it
    by a different rule than the fifteen beside it."""
    values = []
    for book in BOOKS:
        for row in rows:
            if row.get("vendor") != book:
                continue
            raw = row.get("spread_home_value")
            if raw is None or raw == "":
                continue
            try:
                values.append((book, float(raw)))
            except (TypeError, ValueError):
                continue
    if not values:
        return None, {"rule": CONSENSUS_RULE, "books_seen": 0, "mode_count": 0}

    counts = Counter(v for _, v in values)
    top = max(counts.values())
    # Ties broken by book priority: BOOKS order is the order `values` was built
    # in, so the first candidate still standing is the highest-priority book's.
    winner = next(v for _, v in values if counts[v] == top)
    return winner, {
        "rule": CONSENSUS_RULE,
        "value": winner,
        "mode_count": top,
        "books_seen": len(values),
        "spread_by_book": {book: value for book, value in values},
    }


# ---------------------------------------------------------------------------
# Freeze
# ---------------------------------------------------------------------------

def week_to_freeze(games, deadline):
    """The week whose board that deadline opens: the earliest week whose first
    kickoff is still ahead of it.

    This leans on a property the schedule has and the fetch script documents --
    week windows never overlap and the only day no week covers is Tuesday -- so
    a Tuesday 3am instant sits unambiguously between two weeks and there is no
    week it could be said to fall inside.
    """
    first = {}
    for g in games:
        kickoff = parse_ts(g.get("date"))
        week = g.get("week")
        if kickoff is None or week is None:
            continue
        if week not in first or kickoff < first[week]:
            first[week] = kickoff
    candidates = [w for w, k in first.items() if k > deadline]
    return min(candidates) if candidates else None


def freeze(season, week, games, deadline, now, force=False, mode="auto", dry=False):
    """-> list of log lines."""
    slate = [g for g in games if g.get("week") == week]
    if not slate:
        return [f"week {week} of {season} has no games"]

    # Read before write, always -- including on a dry run, where "would freeze
    # 16" when fifteen are already frozen is exactly the wrong answer to give.
    # A dry run with no credentials still works; it just cannot know that.
    try:
        stored = {int(r["game_id"]): r for r in
                  (supabase(f"pickem_games?season=eq.{season}&week=eq.{week}"
                            f"&select=game_id,frozen_at") or [])}
    except CaptureError:
        if not dry:
            raise
        stored = {}

    todo = [g for g in slate
            if force or not (stored.get(int(g["id"])) or {}).get("frozen_at")]
    already = len(slate) - len(todo)
    if not todo:
        stamp = (stored.get(int(slate[0]["id"])) or {}).get("frozen_at")
        return [f"week {week} already frozen at {stamp} — nothing to do"]

    # A game that has already started cannot have its line frozen honestly, so
    # it is left alone rather than stamped with whatever the book shows now.
    late = [g for g in todo if (parse_ts(g.get("date")) or now) <= now]
    todo = [g for g in todo if g not in late]
    if not todo:
        return [f"week {week}: every unfrozen game has already kicked off"]

    if dry:
        lines = [f"would freeze {len(todo)} game(s) in week {week} of {season}"]
        if already:
            lines.append(f"  ({already} already frozen)")
        for g in todo:
            lines.append(f"  {g['visitor_team']['abbreviation']:>3} @ "
                         f"{g['home_team']['abbreviation']:<3} "
                         f"{iso(parse_ts(g['date']))}")
        return lines

    odds = week_odds([g["id"] for g in todo], mode=mode)

    rows, missing = [], []
    for g in todo:
        game_id = int(g["id"])
        quotes = odds.get(game_id) or []
        if not quotes:
            quotes = opening_odds(game_id, mode=mode)
        spread, workings = consensus(quotes)
        if spread is None:
            missing.append(f"{g['visitor_team']['abbreviation']}@"
                           f"{g['home_team']['abbreviation']}")
        rows.append({
            "game_id": game_id,
            "season": season,
            "week": week,
            "away": g["visitor_team"]["abbreviation"],
            "home": g["home_team"]["abbreviation"],
            "kickoff": iso(parse_ts(g["date"])),
            "spread_home": spread,
            "deadline_at": iso(deadline),
            "frozen_at": iso(now),
            "status": "scheduled",
            "data": {
                "line_status": "ok" if spread is not None else "unavailable",
                "consensus": workings,
                "books": [{k: q.get(k) for k in
                           ("vendor", "spread_home_value", "spread_away_value",
                            "spread_home_odds", "spread_away_odds", "updated_at")}
                          for q in quotes],
                "venue": g.get("venue"),
            },
            "updated_at": "now()",
        })

    supabase("pickem_games?on_conflict=game_id", method="POST", body=rows,
             headers={"Prefer": "resolution=merge-duplicates,return=minimal"})

    lines = [f"froze {len(rows)} game(s) in week {week} of {season} "
             f"(deadline {iso(deadline)}, captured {iso(now)})"]
    if already:
        lines.append(f"  {already} were already frozen and were left alone")
    if late:
        lines.append(f"  {len(late)} had already kicked off and were skipped")
    if missing:
        lines.append(f"  no line available, off the board: {', '.join(missing)}")
    return lines


# ---------------------------------------------------------------------------
# Grade
# ---------------------------------------------------------------------------

def grade_season(season, games, now, dry=False, mode="auto"):
    """Write the score and the ATS verdict for every game on the board that has
    finished and has no verdict yet. -> list of log lines."""
    board = supabase(f"pickem_games?season=eq.{season}"
                     f"&select=game_id,week,away,home,spread_home,result") or []
    ungraded = {int(r["game_id"]): r for r in board if r.get("result") is None}
    if not ungraded:
        return ["nothing to grade"]

    by_id = {int(g["id"]): g for g in games}
    rows, lines = [], []
    for game_id, stored in sorted(ungraded.items()):
        live = by_id.get(game_id)
        if not live or live.get("status_state") != "final":
            continue
        away_score = live.get("visitor_team_score")
        home_score = live.get("home_team_score")
        spread = stored.get("spread_home")
        spread = None if spread is None else float(spread)
        result = scoring.grade(spread, away_score, home_score)
        if result is None:
            # Final but ungradeable: the line never froze. Record the score so
            # the page can show it, and leave `result` null so it scores nothing
            # for everybody rather than silently scoring straight-up.
            rows.append({"game_id": game_id, "away_score": away_score,
                         "home_score": home_score, "status": "final",
                         "updated_at": "now()"})
            lines.append(f"  {stored['away']}@{stored['home']} final "
                         f"{away_score}-{home_score}, no line — left ungraded")
            continue
        rows.append({"game_id": game_id, "away_score": away_score,
                     "home_score": home_score, "status": "final",
                     "result": result, "graded_at": iso(now),
                     "updated_at": "now()"})
        cover = stored["home"] if result == "home" else (
            stored["away"] if result == "away" else "push")
        lines.append(f"  wk{stored['week']:>2} {stored['away']}@{stored['home']} "
                     f"{away_score}-{home_score} ({spread:+g}) → {cover}")

    if not rows:
        return ["nothing to grade"]
    if dry:
        return [f"would grade {len(rows)} game(s)"] + lines

    # PATCH per row rather than one upsert: an upsert would need every not-null
    # column in the payload and would rewrite the frozen line on its way past.
    for row in rows:
        game_id = row.pop("game_id")
        supabase(f"pickem_games?game_id=eq.{game_id}", method="PATCH", body=row,
                 headers={"Prefer": "return=minimal"})
    return [f"graded {len(rows)} game(s)"] + lines


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", type=int, help="default: the season we are in")
    ap.add_argument("--week", type=int, help="freeze this week instead of the "
                                             "one the deadline opens")
    ap.add_argument("--force", action="store_true",
                    help="re-freeze a week that already has frozen_at")
    ap.add_argument("--freeze-only", action="store_true")
    ap.add_argument("--grade-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="no writes, no key needed")
    ap.add_argument("--replay", action="store_true",
                    help="work from recorded cassettes only")
    ap.add_argument("--now", help="ISO instant to treat as the clock, for testing "
                                  "the DST boundary")
    args = ap.parse_args()

    now = parse_ts(args.now) if args.now else datetime.now(timezone.utc)
    season = args.season or season_for(now)
    deadline = freeze_deadline(now)
    mode = "replay" if args.replay else "auto"

    print(f"now      {iso(now)}  ({now.astimezone(ET):%Y-%m-%d %H:%M %Z})")
    print(f"deadline {iso(deadline)}  ({deadline.astimezone(ET):%Y-%m-%d %H:%M %Z})")
    print(f"season   {season}")

    try:
        games = season_games(season, mode=mode)
    except bdl.TierError as e:
        print(f"\n{e}", file=sys.stderr)
        return 1
    except bdl.BdlError as e:
        print(f"\n{e}", file=sys.stderr)
        return 1
    print(f"games    {len(games)} regular-season games from balldontlie\n")

    status = 0
    if not args.grade_only:
        week = args.week or week_to_freeze(games, deadline)
        if week is None:
            print("freeze: no week opens after that deadline — season over")
        elif now < deadline:
            print("freeze: the deadline is in the future; nothing to freeze yet")
        else:
            try:
                for line in freeze(season, week, games, deadline, now,
                                   force=args.force, mode=mode, dry=args.dry_run):
                    print(f"freeze: {line}")
            except bdl.TierError as e:
                # /odds is GOAT-only. Writing a week of null lines would open a
                # board nobody can be graded on, so this fails loudly and leaves
                # the week unfrozen for a later run or a human.
                print(f"\nfreeze: refusing to write a week with no lines.\n{e}",
                      file=sys.stderr)
                status = 1
            except CaptureError as e:
                print(f"\nfreeze: {e}", file=sys.stderr)
                status = 1

    if not args.freeze_only:
        try:
            for line in grade_season(season, games, now, dry=args.dry_run, mode=mode):
                print(f"grade:  {line}")
        except CaptureError as e:
            # A dry run is allowed to be run without credentials; a real one is
            # not, and a missing table is the thing worth exiting non-zero over.
            print(f"\ngrade: {e}", file=sys.stderr)
            status = status if args.dry_run else 1

    return status


if __name__ == "__main__":
    sys.exit(main())
