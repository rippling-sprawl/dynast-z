#!/usr/bin/env python3
"""
Keep the published NFL game bundles current, unattended.

Why this exists
---------------
scripts/fetch_bdl_game.py captures one game, and it captures it because a human
typed its name. That is the right shape for the two worked examples, and the
wrong shape for a season: /football/schedule links 272 games a year, and every
one of them showed "no bundle has been published for this game yet" until
somebody ran the fetcher at it by hand.

This is the sweeper. It reads the committed schedule, asks Supabase what is
already stored and how old it is, and re-captures whatever is due -- where "due"
comes from fetch_bdl_game.refresh_plan(), the same table that stamps every
bundle with when it will next change. One policy, so the cadence the page
promises is the cadence a sweep actually runs.

Two ways to run it
------------------
  --once   one sweep and exit. This is the cron shape, and what
           .github/workflows/bdl-refresh.yml runs every 15 minutes.
  --loop   sweep, sleep until the next game is due, sweep again. This is the
           game-day shape: GitHub's scheduled runners are best-effort and drift
           five to fifteen minutes under load, which is fine for a Tuesday and
           useless for a live game on a two-minute cadence. Run this in a
           terminal from an hour before kickoff and the live games actually keep
           up.

Both write to Supabase and nothing else. No commit, no deploy -- the page is
current on the next request, the same split the Action Network book uses.

Cost
----
A bundle is ~15 requests. A full slate of 16 live games at the two-minute live
cadence is ~120 req/min against GOAT's 600, and bdl_common's limiter defaults to
half of that anyway. Everything is cassetted, so a sweep is also an archive.

Usage:
    python3 scripts/bdl_refresh.py --once --dry-run        # what is due, no calls
    python3 scripts/bdl_refresh.py --once --publish
    python3 scripts/bdl_refresh.py --loop --publish
    python3 scripts/bdl_refresh.py --once --publish --season 2026 --week 1
    python3 scripts/bdl_refresh.py --game-id 1392216 --publish
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bdl_common as bdl                     # noqa: E402
import fetch_bdl_game as game                # noqa: E402

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def repo_path(*parts):
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        *parts)


def iso(ts):
    return datetime.fromtimestamp(int(ts), timezone.utc).strftime("%H:%M:%SZ")


def since(ts, now):
    """Human gap, for the log. '4m' reads faster than a timestamp in a sweep."""
    d = int(now - ts)
    if d < 90:
        return f"{d}s"
    if d < 5400:
        return f"{d // 60}m"
    if d < 172800:
        return f"{d // 3600}h"
    return f"{d // 86400}d"


# --------------------------------------------------------------------------
# What exists
# --------------------------------------------------------------------------

def load_schedule(season):
    """-> [{"id", "kickoff_ts", "away", "home", "week", "season"}] or []."""
    path = repo_path("data", f"nfl_schedule_{season}.json")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        doc = json.load(f)
    out = []
    for wk in doc.get("weeks", []):
        for g in wk.get("games", []):
            # kickoff is "%Y-%m-%dT%H:%MZ" and always UTC -- see the schedule
            # fetcher. A game with no parseable kickoff cannot be scheduled
            # against, so it is skipped rather than guessed at.
            try:
                ts = datetime.strptime(g["kickoff"], "%Y-%m-%dT%H:%MZ").replace(
                    tzinfo=timezone.utc).timestamp()
            except (KeyError, ValueError):
                continue
            out.append({"id": str(g["id"]), "kickoff_ts": ts, "week": wk.get("week"),
                        "away": g.get("away"), "home": g.get("home"),
                        "season": doc.get("season", season)})
    return out


def load_stored():
    """-> {game_id: {"phase", "updated_ts", "has"}} from Supabase.

    Only the summary columns: the point of duplicating them out of `data` is
    that deciding what to refresh must not pull a megabyte per game."""
    url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_KEY") or ""
    if not url or not key:
        raise SystemExit(
            "SUPABASE_URL and SUPABASE_KEY are needed to know what is already\n"
            "published. Both are already in .env for the rest of the site.")
    req = urllib.request.Request(
        f"{url}/rest/v1/game_odds?select=game_id,phase,updated_at,has")
    req.add_header("apikey", key)
    req.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            rows = json.loads(resp.read() or b"[]")
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        if "PGRST205" in detail:
            raise SystemExit(
                "The game_odds table does not exist yet -- run\n"
                "  scripts/sql/game_odds.sql\n"
                "once in the Supabase SQL editor, then re-run this.")
        raise SystemExit(f"Supabase read failed ({e.code}): {detail}")

    out = {}
    for r in rows:
        ts = None
        stamp = r.get("updated_at")
        if stamp:
            # PostgREST hands back microseconds and a +00:00 offset; both are
            # fine for fromisoformat, a trailing Z is not.
            try:
                ts = datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
            except ValueError:
                ts = None
        out[str(r["game_id"])] = {"phase": r.get("phase"), "updated_ts": ts,
                                  "has": r.get("has") or {}}
    return out


# --------------------------------------------------------------------------
# What is due
# --------------------------------------------------------------------------

def plan_sweep(schedule, stored, now, backfill=False, always=()):
    """-> (due, waiting, backlog). Each is [(game, plan, stored_or_None)].

    A game with no stored bundle is due as soon as its policy is not `distant`:
    that is the whole answer to "why is this page empty" -- nothing was ever
    fetched for it, and now something will be.

    `backlog` is the exception: games that finished long ago and were never
    captured. Their plan is frozen, because a settled game genuinely never
    changes again, so a sweep must not treat "frozen" as "done" and quietly skip
    them forever -- nor discover 272 of them on a 15-minute cron and spend four
    thousand requests backfilling a season nobody asked for. They are listed,
    and only captured under --backfill."""
    due, waiting, backlog = [], [], []
    for g in schedule:
        st = stored.get(g["id"])
        # An unfetched game has no observed phase, so kickoff has to stand in
        # for one. Well past kickoff it is over; near or before it, the game
        # layer is what decides, and refresh_plan's own to_kick <= 0 branch
        # treats the just-started window as live.
        stale = (g["kickoff_ts"] is not None
                 and now - g["kickoff_ts"] > game.SETTLING_WINDOW)
        phase = (st or {}).get("phase") or ("final" if stale else "pregame")
        last = (st or {}).get("updated_ts")
        plan = game.refresh_plan(g["kickoff_ts"], phase, last, now=now)
        row = (g, plan, st)
        if g["id"] in always:
            due.append(row)
            continue
        if plan["frozen"]:
            if st is None and plan["policy"] == "settled":
                backlog.append(row)
                if backfill:
                    due.append(row)
            continue
        if st is None and plan["policy"] == "distant":
            continue
        if last is None or now >= plan["next_ts"]:
            due.append(row)
        else:
            waiting.append(row)
    # Soonest kickoff first: a live game matters more than a Sunday one, and a
    # capped sweep should spend its budget on the games whose lines are moving.
    due.sort(key=lambda r: r[0]["kickoff_ts"] or 0)
    waiting.sort(key=lambda r: r[1]["next_ts"])
    backlog.sort(key=lambda r: r[0]["kickoff_ts"] or 0, reverse=True)
    return due, waiting, backlog


def describe(g, plan, st, now):
    tag = f"{g['away']}@{g['home']}"
    age = f"{since(st['updated_ts'], now)} old" if st and st.get("updated_ts") else "never captured"
    every = f"every {plan['interval_s'] // 60:>3}m" if plan["interval_s"] else "one-off   "
    return (f"  {g['id']:>9}  {tag:<9} wk{str(g['week'] or '-'):<3} "
            f"{plan['policy']:<9} {every}  {age}")


# --------------------------------------------------------------------------
# Sweep
# --------------------------------------------------------------------------

def capture(g, mode, books, force, publish):
    """Fetch and publish one game. -> True on success.

    Per-game failures are contained: a sweep that dies on one 404 leaves the
    rest of the slate stale. An AuthError is the exception and is re-raised --
    a bad or expired key fails every remaining game identically, and hammering
    the API 200 more times to find that out is worse than stopping."""
    try:
        raw = game.fetch_game_by_id(int(g["id"]), mode)
        if not raw:
            print(f"    game {g['id']} not found upstream", file=sys.stderr)
            return False
        label = f"{g['away']}_{g['home']}_{g['season']}".lower()
        title = (f"Week {g['week']}, {g['season']} — {g['away']} at {g['home']}"
                 if g.get("week") else None)
        bundle = game.build_bundle(raw, label, title, mode, books)
    except bdl.AuthError:
        raise
    except bdl.BdlError as e:
        print(f"    {g['away']}@{g['home']}: {e}", file=sys.stderr)
        return False

    ok, _ = game.verify(bundle, {})
    if not ok:
        print(f"    {g['away']}@{g['home']}: failed verify, not published",
              file=sys.stderr)
        return False

    if not publish:
        print(f"    {g['away']}@{g['home']}: built, --publish not given")
        return True

    try:
        for line in game.publish(bundle, force=force):
            print(f"    {line}")
    except game.PublishError as e:
        print(f"    Not published. {e}", file=sys.stderr)
        return False
    return True


def sweep(args, mode, books):
    now = time.time()
    schedule = []
    for season in args.seasons:
        rows = load_schedule(season)
        if not rows:
            print(f"no data/nfl_schedule_{season}.json -- skipping that season",
                  file=sys.stderr)
        schedule.extend(rows)
    if args.week:
        schedule = [g for g in schedule if g["week"] == args.week]
    if args.game_id:
        schedule = [g for g in schedule if g["id"] == str(args.game_id)]
        if not schedule:
            # Not on the committed schedule -- a postseason game, say. Still
            # refreshable; there is just no kickoff to schedule against, so it
            # is always due.
            schedule = [{"id": str(args.game_id), "kickoff_ts": None, "week": None,
                         "away": "?", "home": "?", "season": args.seasons[0]}]

    stored = load_stored()
    always = {str(args.game_id)} if args.game_id else set()
    due, waiting, backlog = plan_sweep(schedule, stored, now, args.backfill,
                                       always)

    print(f"\n{datetime.fromtimestamp(now, timezone.utc).strftime('%Y-%m-%d %H:%M:%SZ')}"
          f"  {len(schedule)} scheduled · {len(stored)} published · "
          f"{len(due)} due · {len(waiting)} waiting"
          + (f" · {len(backlog)} never captured" if backlog and not args.backfill else ""))
    if backlog and not args.backfill:
        print(f"  {len(backlog)} finished game(s) were never captured and will "
              f"not be, on their own — they are settled, so nothing about them\n"
              f"  changes. Fill them in deliberately: --backfill --limit N")

    capped = due[:args.limit] if args.limit else due
    if len(capped) < len(due):
        # Never truncate silently: a capped sweep that says nothing reads as a
        # sweep that covered everything.
        print(f"  limit {args.limit} — {len(due) - len(capped)} due game(s) "
              f"deferred to the next sweep")

    for g, plan, st in capped:
        print(describe(g, plan, st, now))
    if args.dry_run:
        for g, plan, st in waiting[:5]:
            print(f"  next: {g['away']}@{g['home']} at {iso(plan['next_ts'])}")
        return 0, waiting

    done = 0
    for g, plan, st in capped:
        if capture(g, mode, books, args.force, args.publish):
            done += 1
    print(f"  {done}/{len(capped)} captured")

    if capped:
        # Recompute so a --loop sleep is based on what this sweep just wrote,
        # not on what was stored before it ran.
        _, waiting, _ = plan_sweep(schedule, load_stored(), time.time())
    return done, waiting


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", type=int, action="append", dest="seasons",
                    help="repeatable; defaults to the current and previous season")
    ap.add_argument("--week", type=int, help="restrict to one week")
    ap.add_argument("--game-id", type=int, help="refresh exactly one game")
    ap.add_argument("--limit", type=int, default=12,
                    help="most games to capture in one sweep (0 = no cap)")
    ap.add_argument("--once", action="store_true", help="one sweep and exit")
    ap.add_argument("--loop", action="store_true",
                    help="sweep, sleep until the next game is due, repeat")
    ap.add_argument("--backfill", action="store_true",
                    help="also capture finished games that were never captured "
                         "— a season of these is thousands of requests, so it "
                         "is opt-in and worth pairing with --limit")
    ap.add_argument("--dry-run", action="store_true",
                    help="print what is due and make no requests")
    ap.add_argument("--publish", action="store_true",
                    help="upsert each bundle into Supabase -- without this the "
                         "sweep fetches and verifies but publishes nothing")
    ap.add_argument("--force", action="store_true",
                    help="publish even when a capture is thinner than what is "
                         "stored (see fetch_bdl_game.publish)")
    ap.add_argument("--books", default=",".join(game.DEFAULT_BOOKS), metavar="LIST")
    ap.add_argument("--all-books", action="store_true")
    ap.add_argument("--max-sleep", type=int, default=600,
                    help="longest --loop sleep, seconds (default 600)")
    bdl.add_mode_args(ap)
    args = ap.parse_args()

    if not args.once and not args.loop:
        args.once = True
    if args.once and args.loop:
        ap.error("--once and --loop are mutually exclusive")
    if not args.seasons:
        # The NFL season is named for the year it starts in, and runs into
        # February. Both seasons stay in scope through the winter.
        y = datetime.now(timezone.utc).year
        m = datetime.now(timezone.utc).month
        cur = y if m >= 3 else y - 1
        args.seasons = [cur, cur - 1]

    # A refresher's job is to find out what changed, so a cassette hit is the
    # wrong answer by definition: default to fetching live and recording, and
    # let --replay or --mode override that for a rehearsal.
    mode = bdl.resolve_mode(args)
    if mode == "auto" and "--mode" not in sys.argv:
        mode = "record"
    books = () if args.all_books else tuple(
        b.strip().lower() for b in args.books.split(",") if b.strip())

    print(f"bdl refresh (mode={mode}, seasons={args.seasons}"
          f"{', dry run' if args.dry_run else ''}"
          f"{'' if args.publish or args.dry_run else ', NOT publishing'})")

    if args.once:
        try:
            sweep(args, mode, books)
        except bdl.AuthError as e:
            print(f"\n{e}", file=sys.stderr)
            return 1
        return 0

    while True:
        try:
            _, waiting = sweep(args, mode, books)
        except bdl.AuthError as e:
            print(f"\n{e}", file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            print("\nstopped")
            return 0
        nxt = waiting[0][1]["next_ts"] if waiting else time.time() + args.max_sleep
        # Floored at 30s so a clock skew or an off-by-one cannot spin.
        nap = max(30, min(args.max_sleep, nxt - time.time()))
        print(f"  sleeping {int(nap)}s")
        try:
            time.sleep(nap)
        except KeyboardInterrupt:
            print("\nstopped")
            return 0


if __name__ == "__main__":
    sys.exit(main())
