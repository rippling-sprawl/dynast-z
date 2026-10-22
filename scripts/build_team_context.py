#!/usr/bin/env python3
"""
Build the team context /football/player-projections adjusts a projection by:
every offense's games this season, with each skill player's snaps, carries
and targets in each one.

Why this exists
---------------
A projection read off one player's own game log cannot see his teammates.
When the starting back is ruled out, his backup's log still says "backup";
when the starter comes back, the games the backup spent as the starter still
count as his. What the page needs to know is the team around him: how many
carries and targets the offense has to hand out, what share of them went to
whom in each game, and who was on the field. That is this table.

For each team, each final game holds:

  plays, dropbacks, rush     the offense's snaps by kind (dropbacks count
                             sacks); `opp_plays` the same for the opponent,
                             so a defense's plays faced can be read off it
  spread, total              the game's opening line from the bundle (the
                             "current" one on a final game is the last in-
                             game number, not the pregame one)
  players {bdl id: {...}}    snap share (nflverse snap counts, joined by
                             name), pass attempts, carries, rush yards,
                             targets, catches, receiving yards
  ol {name: snap share}      the offensive line's snaps, by name only:
                             balldontlie's box score has no linemen in it

The page does the arithmetic -- shares, who is missing, what the lineup this
week looks like -- because it is the page that knows this week's injury
report and the manual adjustments.

Sources: Supabase `game_odds` (the box scores and plays, as
build_defense_vs_players reads them) and nflverse's snap_counts CSV.

When
----
.github/workflows/team-context.yml: Tuesday 5:00am ET after the week is final,
and daily, because nflverse's snap counts land a day or two after the games.
A full rebuild every run; whole weeks only, as build_defense_vs_players.

Usage:
    python3 scripts/build_team_context.py --dry-run --team CHI
    python3 scripts/build_team_context.py                  # publish
    python3 scripts/build_team_context.py --season 2025
"""

import argparse
import csv
import io
import re
import subprocess
import sys
from datetime import datetime, timezone

from build_defense_vs_players import (BuildError, final_games, iso, n, open_weeks,
                                      season_for, supabase)

TABLE = "team_context"
SNAPS_URL = ("https://github.com/nflverse/nflverse-data/releases/download/"
             "snap_counts/snap_counts_{season}.csv")
# nflverse's abbreviations, where they are not this site's.
NFLVERSE_ABBR = {"LA": "LAR", "WAS": "WSH"}
SKILL = ("QB", "RB", "FB", "WR", "TE")
LINE = ("OL", "T", "G", "C")
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def norm(name):
    """'D.J. Moore' and 'DJ Moore' -> 'dj moore'; suffixes dropped, as
    api/player-projections.py's norm."""
    words = re.sub(r"[^a-z0-9 ]", "", str(name or "").lower().replace("-", "")).split()
    return " ".join(w for w in words if w not in SUFFIXES)


def load_snaps(season):
    """-> {(team, week): [row]} of nflverse snap counts, or {} if the season's
    file is not up yet (it is a day or two behind the games)."""
    result = subprocess.run(["curl", "-sL", "--max-time", "120", "-f",
                             SNAPS_URL.format(season=season)], capture_output=True)
    if result.returncode != 0 or not result.stdout:
        print(f"  no nflverse snap counts for {season} yet -- snap shares left out")
        return {}
    out = {}
    for r in csv.DictReader(io.StringIO(result.stdout.decode("utf-8", "replace"))):
        if r.get("game_type") not in ("REG", "WC", "DIV", "CON", "SB"):
            continue
        team = NFLVERSE_ABBR.get(r["team"], r["team"])
        try:
            week, snaps, pct = int(r["week"]), int(r["offense_snaps"] or 0), float(r["offense_pct"] or 0)
        except ValueError:
            continue
        if snaps <= 0:
            continue
        out.setdefault((team, week), []).append(
            {"name": r["player"], "pos": r["position"], "snaps": snaps, "pct": pct})
    return out


def side_totals(stats):
    """-> (dropbacks, rush attempts) from one side's box score. Dropbacks are
    pass attempts plus sacks; rushes include the quarterback's."""
    drop = rush = 0
    for p in stats or []:
        pa = p.get("passing") or {}
        drop += n(pa.get("passing_attempts")) + n(pa.get("sacks"))
        rush += n((p.get("rushing") or {}).get("rushing_attempts"))
    return drop, rush


def opening_line(opening, home):
    """-> (this side's spread, total) from the first opening line, or
    (None, None). A spread is the side's own: -3 is favored by three."""
    for o in opening or []:
        try:
            spread = float(o["spread_home_value" if home else "spread_away_value"])
            total = float(o["total_value"])
        except (KeyError, TypeError, ValueError):
            continue
        return spread, total
    return None, None


def player_line(p):
    pa, ru, rc = p.get("passing") or {}, p.get("rushing") or {}, p.get("receiving") or {}
    return {
        "pass_att": n(pa.get("passing_attempts")),
        "rush_att": n(ru.get("rushing_attempts")),
        "rush_yds": n(ru.get("rushing_yards")),
        "targets": n(rc.get("receiving_targets")),
        "rec": n(rc.get("receptions")),
        "rec_yds": n(rc.get("receiving_yards")),
        "td": n(ru.get("rushing_touchdowns")) + n(rc.get("receiving_touchdowns")),
    }


def build(season, games, snaps, now):
    """-> {team: payload} for every team with a final game."""
    by_team = {}
    for g in games:
        game = g.get("game") or {}
        stats = g.get("stats") or {}
        score = game.get("score") or {}
        sides = {"away": (g["away"], g["home"], False), "home": (g["home"], g["away"], True)}
        totals = {side: side_totals(stats.get(side)) for side in sides}
        for side, (team, opp, home) in sides.items():
            other = "home" if side == "away" else "away"
            drop, rush = totals[side]
            spread, total = opening_line(g.get("odds"), home)
            entry = by_team.setdefault(team, {"games": [], "players": {}})
            # Snap counts are joined by name: balldontlie and nflverse share no
            # id, but within one team's week a name is unique.
            snap_rows = snaps.get((team, g.get("week"))) or []
            by_name = {norm(r["name"]): r for r in snap_rows}
            # The offense's snaps, read off whoever played the most of them: a
            # one-snap row's 0.01 would round its way to a hundred.
            top = max(snap_rows, key=lambda r: r["snaps"], default=None)
            team_snaps = round(top["snaps"] / top["pct"]) if top and top["pct"] > 0 else None
            row = {
                "game_id": g["game_id"],
                "week": g.get("week"),
                "postseason": bool(game.get("postseason")),
                "kickoff": g.get("kickoff"),
                "opp": opp,
                "home": home,
                "pts_for": score.get(side),
                "pts_against": score.get(other),
                "spread": spread,
                "total": total,
                "dropbacks": drop,
                "rush": rush,
                "plays": drop + rush,
                "opp_plays": sum(totals[other]),
                "snaps": team_snaps,
                "players": {},
                "ol": {r["name"]: round(r["pct"], 2) for r in snap_rows if r["pos"] in LINE},
            }
            for p in stats.get(side) or []:
                who = p.get("player") or {}
                pos = who.get("position_abbreviation") or ""
                if pos not in SKILL or who.get("id") is None:
                    continue
                name = " ".join(x for x in (who.get("first_name"), who.get("last_name")) if x)
                line = player_line(p)
                snap = by_name.get(norm(name))
                line["snap"] = round(snap["pct"], 2) if snap else None
                row["players"][str(who["id"])] = line
                entry["players"][str(who["id"])] = {"name": name, "pos": pos}
            # A skill player on the field with no carry, target or throw has no
            # box-score line; his snaps still say he played.
            seen = {norm(entry["players"][pid]["name"]) for pid in row["players"]}
            for key, r in by_name.items():
                if r["pos"] in SKILL and key not in seen:
                    pid = next((pid for pid, p in entry["players"].items() if norm(p["name"]) == key), None)
                    if pid:
                        row["players"][pid] = {"pass_att": 0, "rush_att": 0, "rush_yds": 0, "targets": 0,
                                               "rec": 0, "rec_yds": 0, "td": 0, "snap": round(r["pct"], 2)}
            entry["games"].append(row)

    # League per-team-game averages, the baseline tempo and script are read
    # against. The same numbers go in every team's row.
    reg = [r for e in by_team.values() for r in e["games"] if not r["postseason"]]
    league = {
        "plays": round(sum(r["plays"] for r in reg) / len(reg), 1) if reg else 62.0,
        "rush_rate": round(sum(r["rush"] for r in reg) / max(1, sum(r["plays"] for r in reg)), 3) if reg else 0.42,
        "total": round(sum(r["total"] for r in reg if r["total"]) / max(1, sum(1 for r in reg if r["total"])), 1)
        if reg else 44.0,
    }
    out = {}
    for team, entry in by_team.items():
        entry["games"].sort(key=lambda r: r["kickoff"] or "", reverse=True)
        out[team] = {"season": season, "team": team, "games": entry["games"],
                     "players": entry["players"], "league": league, "built_at": iso(now)}
    return out


def publish(season, payloads, now):
    body = [{"season": season, "team": team, "games": len(p["games"]),
             "data": p, "updated_at": iso(now)} for team, p in sorted(payloads.items())]
    supabase(f"{TABLE}?on_conflict=season,team", method="POST", body=body,
             headers={"Prefer": "resolution=merge-duplicates,return=minimal"})


def show(p):
    """Print one team's skill players game by game, newest first."""
    names = p["players"]
    print(f"  league: {p['league']}")
    for g in p["games"]:
        print(f"  wk {g['week']:>2} {'vs' if g['home'] else '@ '} {g['opp']:<3} plays {g['plays']:>3}"
              f" (rush {g['rush']}, db {g['dropbacks']})  opp {g['opp_plays']}  spread {g['spread']}"
              f" total {g['total']}  snaps {g['snaps']}  OL {len(g['ol'])}")
        rows = sorted(g["players"].items(), key=lambda kv: -(kv[1]["rush_att"] + kv[1]["targets"]))
        for pid, r in rows:
            if r["rush_att"] + r["targets"] + r["pass_att"] == 0 and not r["snap"]:
                continue
            print(f"      {names[pid]['name']:<24} {names[pid]['pos']:<2} snap {r['snap']!s:<5}"
                  f" att {r['pass_att']:>2}  car {r['rush_att']:>2}  tgt {r['targets']:>2}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", type=int, help="default: the season we are in")
    ap.add_argument("--team", help="with --dry-run, print this team's games")
    ap.add_argument("--dry-run", action="store_true", help="read only, write nothing")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    season = args.season or season_for(now)
    try:
        held = open_weeks(season, now)
        games = [g for g in final_games(season, odds=True, plays=False)
                 if (bool((g.get("game") or {}).get("postseason")), g.get("week")) not in held]
        snaps = load_snaps(season)
        payloads = build(season, games, snaps, now)
        print(f"season {season}: {len(games)} final games, {len(payloads)} teams, "
              f"snap counts for {len(snaps)} team-weeks")
        if args.dry_run:
            if args.team and args.team.upper() in payloads:
                show(payloads[args.team.upper()])
            return 0
        publish(season, payloads, now)
        print(f"published {len(payloads)} rows to {TABLE}")
    except BuildError as e:
        print(f"\n{e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
