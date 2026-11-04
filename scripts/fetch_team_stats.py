#!/usr/bin/env python3
"""
Fetch every team's season totals and save to data/nfl_team_stats_{season}.json,
for /football/team-stats.

Source
------
balldontlie, one request for the whole league:

    https://api.balldontlie.io/nfl/v1/team_season_stats
        ?season={season}&team_ids[]=1&...&team_ids[]=32

Each row carries a team's own offense and, under an `opp_` prefix, what its
opponents did against it -- so points for and against, and yards gained and
allowed, all come off the same row with no box scores to add up. `team_ids[]`
is required (a bare ?season= is a 400), which is why the 32 ids are read from
/teams first rather than hard-coded.

What is kept
------------
Totals and games played, not per-game rates. The page divides, because the
point of the board is that teams have not all played the same number of games
-- a bye week leaves a team a game behind for a week -- and a file of
pre-divided rates would hide the denominator the reader may want to check.

Yards are the `net_` figures: passing net of sack yardage, plus rushing. That is
the conventional "total yards" (3,639 net passing + 1,812 rushing = 5,451 for
KC 2025); the plain `total_offensive_yards` field is a larger gross number.

When
----
Tuesdays from 5:00am ET, after a week's games are final, by
.github/workflows/team-season-stats.yml -- the same schedule as the other
weekly boards. With --publish the league goes to Supabase `team_season_stats`
(scripts/sql/team_season_stats.sql), which api/team-season-stats.py serves, so
the page is current on the next request with no commit or deploy. The JSON file
is still written every run; the page falls back to it when the endpoint has
nothing. The default mode is `record` rather than the family's usual `auto`,
because `auto` would replay last week's cassette.

Usage:
    python3 scripts/fetch_team_stats.py                 # current season, file only
    python3 scripts/fetch_team_stats.py --publish       # ... and to Supabase
    python3 scripts/fetch_team_stats.py --season 2025
    python3 scripts/fetch_team_stats.py --dry-run
    python3 scripts/fetch_team_stats.py --replay        # offline, from cache/bdl
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import bdl_common  # noqa: E402  -- also loads .env


def repo_path(*parts):
    return os.path.join(ROOT, *parts)


def season_for(now):
    """March onward is that calendar year's season. Same rule as bdl_refresh."""
    return now.year if now.month >= 3 else now.year - 1


def fetch(season, mode):
    by_abbr, by_id = bdl_common.team_index(mode=mode)
    payload, _ = bdl_common.bdl_get("/team_season_stats", {
        "season": season,
        "team_ids[]": sorted(by_id),
        "per_page": 100,
    }, mode=mode)
    # Regular season only. The endpoint answers with season_type 2 today, but a
    # postseason row for the same team would double it on the chart.
    rows = [r for r in payload.get("data") or [] if r.get("season_type") == 2]
    return rows


def shape(rows):
    teams = []
    for r in rows:
        t = r["team"]
        gp, opp_gp = r.get("games_played"), r.get("opp_games_played")
        # The two halves of a row should describe the same games. If they ever
        # disagree, per-game rates built from one denominator are wrong for the
        # other half, so refuse rather than plot it.
        if gp != opp_gp:
            raise SystemExit(f"{t['abbreviation']}: games_played {gp} != opp_games_played {opp_gp}")
        if not gp:
            continue
        teams.append({
            "abbr": t["abbreviation"],
            "team": t["full_name"],
            "conf": t["conference"],
            "div": t["division"],
            "gp": gp,
            "pf": r["total_points"],
            "pa": r["opp_total_points"],
            "yf": r["net_total_offensive_yards"],
            "ya": r["opp_net_total_offensive_yards"],
        })
    teams.sort(key=lambda d: d["abbr"])
    return teams


def verify(teams):
    """League-wide, every point scored is a point allowed and every yard gained
    is a yard given up. A row that dropped a game, or an `opp_` field that means
    something other than what it says, breaks one of the two sums."""
    if len(teams) != 32:
        raise SystemExit(f"expected 32 teams with games played, got {len(teams)}")
    for a, b, label in (("pf", "pa", "points"), ("yf", "ya", "yards")):
        sa = sum(t[a] for t in teams)
        sb = sum(t[b] for t in teams)
        if sa != sb:
            raise SystemExit(f"league {label} for ({sa}) != against ({sb})")


def publish(out):
    """Upsert the league as one row keyed on season."""
    url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_KEY") or ""
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_KEY are needed for --publish. Add them to .env.")
    body = json.dumps([{"season": out["season"], "data": out,
                        "updated_at": out["fetched_at"]}]).encode()
    req = urllib.request.Request(f"{url}/rest/v1/team_season_stats?on_conflict=season",
                                 data=body, method="POST")
    req.add_header("apikey", key)
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Prefer", "resolution=merge-duplicates,return=minimal")
    try:
        with urllib.request.urlopen(req, timeout=60):
            pass
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        if "PGRST205" in detail:
            raise SystemExit("The team_season_stats table does not exist yet -- run "
                             "scripts/sql/team_season_stats.sql once in the Supabase SQL editor.")
        raise SystemExit(f"Supabase POST failed ({e.code}): {detail}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--season", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true", help="print, write nothing")
    ap.add_argument("--publish", action="store_true", help="also upsert to Supabase team_season_stats")
    bdl_common.add_mode_args(ap)
    ap.set_defaults(mode="record")
    args = ap.parse_args()

    season = args.season or season_for(datetime.now())
    rows = fetch(season, bdl_common.resolve_mode(args))
    teams = shape(rows)
    verify(teams)

    out = {
        "season": season,
        "source": "balldontlie /team_season_stats",
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "teams": teams,
    }

    if args.dry_run:
        for t in sorted(teams, key=lambda d: (d["pa"] - d["pf"]) / d["gp"]):
            print(f"  {t['abbr']:<4} gp {t['gp']:>2}  pts {(t['pf'] - t['pa']) / t['gp']:+6.1f}/g"
                  f"  yds {(t['yf'] - t['ya']) / t['gp']:+7.1f}/g")
        return

    path = repo_path("data", f"nfl_team_stats_{season}.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=1)
        f.write("\n")
    print(f"wrote {os.path.relpath(path, ROOT)} ({len(teams)} teams, "
          f"games played {min(t['gp'] for t in teams)}-{max(t['gp'] for t in teams)})")
    if args.publish:
        publish(out)
        print(f"published season {season} to team_season_stats")


if __name__ == "__main__":
    main()
