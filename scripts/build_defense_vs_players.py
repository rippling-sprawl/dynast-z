#!/usr/bin/env python3
"""
Build /football/defense-vs-players: every opposing rusher and receiver each
defense has faced, one row per player per completed game.

Why this exists
---------------
The box score of every game is already captured -- scripts/bdl_refresh.py keeps
a bundle per game in Supabase `game_odds`, and its `player_stats` section is the
box score /football/schedule/game/<id> renders. What no page answers is the
question a prop bettor asks of a matchup: what has *this defense* given up, and
to whom? That is the box scores of a team's games read from the other side,
stacked.

So for each of the 32 teams this reads the opponent's side of every final game
that team played this season and writes the rows to `defense_vs_players`, one
row per (season, team). The page reads one team's row and draws it; nothing is
added up in the browser.

When
----
Weekly, Tuesday 5:00am ET (.github/workflows/defense-vs-players.yml), after
Monday night is final and its stat corrections have landed. Every run is a full
rebuild of the season, so a late, skipped or repeated run is harmless -- the
next one simply writes the right answer.

Only `final` bundles count. A game captured mid-play would put a half-game in
the table that the next run silently changes.

Usage:
    python3 scripts/build_defense_vs_players.py --dry-run --team DAL
    python3 scripts/build_defense_vs_players.py                  # publish
    python3 scripts/build_defense_vs_players.py --season 2025
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

TABLE = "defense_vs_players"

# Only the box-score columns, projected in Postgres: `data->player_stats` is a
# few KB of a bundle whose bulk is player props, and a season is ~270 bundles.
SELECT = ("game_id,week,away,home,kickoff,"
          "game:data->game,stats:data->player_stats")


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

def n(v):
    return v or 0


def player_row(p):
    """-> one player's rushing and receiving line, or None if he had neither."""
    ru = p.get("rushing") or {}
    rc = p.get("receiving") or {}
    if not ru and not rc:
        return None
    who = p.get("player") or {}
    row = {
        "player_id": who.get("id"),
        "player": " ".join(x for x in (who.get("first_name"), who.get("last_name")) if x),
        "pos": who.get("position_abbreviation") or "",
        "rush_att": n(ru.get("rushing_attempts")),
        "rush_yds": n(ru.get("rushing_yards")),
        "rush_td": n(ru.get("rushing_touchdowns")),
        "rush_lng": n(ru.get("long_rushing")),
        "targets": n(rc.get("receiving_targets")),
        "rec": n(rc.get("receptions")),
        "rec_yds": n(rc.get("receiving_yards")),
        "rec_td": n(rc.get("receiving_touchdowns")),
        "rec_lng": n(rc.get("long_reception")),
    }
    row["tot_yds"] = row["rush_yds"] + row["rec_yds"]
    row["tot_td"] = row["rush_td"] + row["rec_td"]
    return row


def build(season, games, now):
    """-> {team: payload} for every team that appears in a final game.

    Each game is read twice, once from each defense's side: the away team's
    defense faced the home side's players and vice versa."""
    by_team = {}
    for g in games:
        game = g.get("game") or {}
        stats = g.get("stats") or {}
        score = game.get("score") or {}
        for defense, side, opp, home in ((g["away"], "home", g["home"], False),
                                         (g["home"], "away", g["away"], True)):
            entry = by_team.setdefault(defense, {"games": [], "rows": []})
            entry["games"].append({
                "game_id": g["game_id"],
                "week": g.get("week"),
                "postseason": bool(game.get("postseason")),
                "kickoff": g.get("kickoff"),
                "opp": opp,
                "home": home,
                "pts_for": score.get("home" if home else "away"),
                "pts_against": score.get(side),
            })
            for p in stats.get(side) or []:
                row = player_row(p)
                if row:
                    row.update(game_id=g["game_id"], week=g.get("week"),
                               kickoff=g.get("kickoff"), opp=opp)
                    entry["rows"].append(row)

    out = {}
    for team, entry in by_team.items():
        # Week ascending, then total yards descending. Ordered by kickoff rather
        # than week number so a postseason game lands after week 18 whatever
        # number the feed gives it; within a game the name breaks ties so the
        # order is stable run to run.
        entry["rows"].sort(key=lambda r: (r["kickoff"] or "", -r["tot_yds"], r["player"]))
        out[team] = {
            "season": season,
            "team": team,
            "games": entry["games"],
            "rows": entry["rows"],
            "built_at": iso(now),
        }
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
    ap.add_argument("--team", help="with --dry-run, print this defense's table")
    ap.add_argument("--dry-run", action="store_true", help="read only, write nothing")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    season = args.season or season_for(now)

    try:
        games = final_games(season)
        payloads = build(season, games, now)
        print(f"season {season}: {len(games)} final games, {len(payloads)} defenses")
        if args.dry_run:
            team = (args.team or "").upper()
            if team:
                for r in (payloads.get(team) or {}).get("rows", []):
                    print(f"  wk {r['week']:>2} {r['opp']:<3} {r['player']:<26} {r['pos']:<3}"
                          f" rush {r['rush_att']:>2}-{r['rush_yds']:>4}-{r['rush_td']}"
                          f"  rec {r['rec']:>2}/{r['targets']:>2}-{r['rec_yds']:>4}-{r['rec_td']}"
                          f"  tot {r['tot_yds']:>4}")
            return 0
        publish(season, payloads, now)
        print(f"published {len(payloads)} rows to {TABLE}")
    except BuildError as e:
        print(f"\n{e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
