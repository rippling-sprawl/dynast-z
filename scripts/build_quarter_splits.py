#!/usr/bin/env python3
"""
Build /football/team-stats/quarter-splits: every team's points by quarter,
scored and allowed, one line per completed game.

Why this exists
---------------
Every final game_odds bundle already carries its quarter line --
fetch_bdl_game.py stores `game.score.away_line` / `home_line` as
[q1, q2, q3, q4, ot], and verify() refuses to publish one that does not add up
to the final. What no page answers is how a team's games tend to run: fast
starters, second-half teams, fourth-quarter collapses. That is those lines read
team by team, stacked.

So for each of the 32 teams this reads both sides of every final game it played
this season and writes them to `quarter_splits`, one row per (season, team).
The page reads one team's row (and its next opponent's) and draws it.

When
----
Weekly, Tuesday 5:00am ET (.github/workflows/quarter-splits.yml), on the same
schedule as build_defense_vs_players.py. Every run is a full rebuild of the
season, so a late, skipped or repeated run is harmless.

Only `final` bundles count. Unlike the defense table there is no whole-weeks
rule: a final score never changes, so a team a game ahead of another is simply
a team that has played one more game.

Usage:
    python3 scripts/build_quarter_splits.py --dry-run --team DAL
    python3 scripts/build_quarter_splits.py                  # publish
    python3 scripts/build_quarter_splits.py --season 2025
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
import bdl_common  # noqa: E402,F401  -- loads .env

TABLE = "quarter_splits"

# Only the score, projected in Postgres: a bundle is mostly odds and props.
SELECT = ("game_id,week,away,home,kickoff,"
          "score:data->game->score,postseason:data->game->postseason,"
          "neutral:data->game->neutral")


class BuildError(RuntimeError):
    """Message is written to be shown verbatim."""


def season_for(now):
    """March onward is that calendar year's season. Same rule as bdl_refresh."""
    return now.year if now.month >= 3 else now.year - 1


def iso(stamp):
    return stamp.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z")


# ---------------------------------------------------------------------------
# Supabase
# ---------------------------------------------------------------------------

def supabase(path, method="GET", body=None, headers=None):
    url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_KEY") or ""
    if not url or not key:
        raise BuildError("SUPABASE_URL and SUPABASE_KEY are needed. Add them to .env.")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{url}/rest/v1/{path}", data=data, method=method)
    req.add_header("apikey", key)
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        if "PGRST205" in detail:
            ref = url.split("//")[-1].split(".")[0]
            raise BuildError(
                f"The {TABLE} table does not exist yet.\n\n"
                f"  Run scripts/sql/{TABLE}.sql once, in the SQL editor at\n"
                f"  https://supabase.com/dashboard/project/{ref}/sql/new\n\n"
                "  Then re-run this command.")
        raise BuildError(f"Supabase {method} failed ({e.code}): {detail}")


def final_games(season):
    return supabase(f"game_odds?select={SELECT}&season=eq.{season}"
                    "&phase=eq.final&order=kickoff.asc") or []


# ---------------------------------------------------------------------------
# The aggregation
# ---------------------------------------------------------------------------

def line(score, side):
    """-> [q1, q2, q3, q4, ot] for one side, or None when the bundle has no
    usable line. A null quarter is a scoreless one (see fetch_bdl_game.q)."""
    raw = (score or {}).get(f"{side}_line")
    if not isinstance(raw, list) or len(raw) != 5:
        return None
    return [int(v or 0) for v in raw]


def build(season, games, now):
    """-> {team: payload} for every team that appears in a final game.

    Each game is read twice, once from each side: `pf` is what that team
    scored by quarter, `pa` what it allowed."""
    by_team = {}
    skipped = 0
    for g in games:
        score = g.get("score") or {}
        away, home = line(score, "away"), line(score, "home")
        if away is None or home is None:
            skipped += 1
            continue
        for team, opp, is_home, pf, pa in ((g["away"], g["home"], False, away, home),
                                           (g["home"], g["away"], True, home, away)):
            by_team.setdefault(team, []).append({
                "game_id": g["game_id"],
                "week": g.get("week"),
                "postseason": bool(g.get("postseason")),
                "kickoff": g.get("kickoff"),
                "opp": opp,
                "home": is_home,
                "neutral": bool(g.get("neutral")),
                "pf": pf,
                "pa": pa,
            })
    if skipped:
        print(f"  {skipped} final game(s) had no quarter line -- left out")

    out = {}
    for team, rows in by_team.items():
        # Kickoff order puts a postseason game after week 18 whatever number
        # the feed gives it.
        rows.sort(key=lambda r: r["kickoff"] or "")
        out[team] = {"season": season, "team": team, "games": rows,
                     "built_at": iso(now)}
    return out


def publish(season, payloads, now):
    body = [{"season": season, "team": team, "games": len(p["games"]),
             "data": p, "updated_at": iso(now)} for team, p in sorted(payloads.items())]
    supabase(f"{TABLE}?on_conflict=season,team", method="POST", body=body,
             headers={"Prefer": "resolution=merge-duplicates,return=minimal"})


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", type=int, help="default: the season we are in")
    ap.add_argument("--team", help="with --dry-run, print this team's lines")
    ap.add_argument("--dry-run", action="store_true", help="read only, write nothing")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    season = args.season or season_for(now)

    try:
        games = final_games(season)
        payloads = build(season, games, now)
        print(f"season {season}: {len(games)} final games, {len(payloads)} teams")
        if args.dry_run:
            team = (args.team or "").upper()
            for r in (payloads.get(team) or {}).get("games", []):
                print(f"  wk {r['week']!s:>2} {'vs' if r['home'] else ' @'} {r['opp']:<3}"
                      f"  for {r['pf']} = {sum(r['pf']):>2}"
                      f"  against {r['pa']} = {sum(r['pa']):>2}")
            return 0
        publish(season, payloads, now)
        print(f"published {len(payloads)} rows to {TABLE}")
    except BuildError as e:
        print(f"\n{e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
