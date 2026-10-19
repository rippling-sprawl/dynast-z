#!/usr/bin/env python3
"""
Build /football/defense-vs-players: every opposing passer, rusher and receiver each
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
import statistics
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
          "game:data->game,stats:data->player_stats,plays:data->plays->all")


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


# A completion is a pass-reception play, or the passing touchdown that ends one.
COMPLETION_SLUGS = ("pass-reception", "passing-touchdown")


def long_completions(plays):
    """-> {passer player_id: longest completion in yards}. The box score has no
    such field, so it is read off the play-by-play."""
    out = {}
    for pl in plays or []:
        if pl.get("type_slug") not in COMPLETION_SLUGS:
            continue
        for q in pl.get("participants") or []:
            if q.get("type") == "passer":
                yds = pl.get("stat_yardage") or 0
                out[q.get("player_id")] = max(out.get(q.get("player_id"), yds), yds)
    return out


def player_row(p, long_pass=None):
    """-> one player's passing, rushing and receiving line, or None if he had
    none of them."""
    pa = p.get("passing") or {}
    ru = p.get("rushing") or {}
    rc = p.get("receiving") or {}
    if not pa and not ru and not rc:
        return None
    who = p.get("player") or {}
    row = {
        "player_id": who.get("id"),
        "player": " ".join(x for x in (who.get("first_name"), who.get("last_name")) if x),
        "pos": who.get("position_abbreviation") or "",
        "pass_cmp": n(pa.get("passing_completions")),
        "pass_att": n(pa.get("passing_attempts")),
        "pass_yds": n(pa.get("passing_yards")),
        "pass_td": n(pa.get("passing_touchdowns")),
        "pass_int": n(pa.get("passing_interceptions")),
        "pass_lng": (long_pass or {}).get(who.get("id"), 0) if pa else 0,
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
    # Scrimmage yards: passing is left out, or a quarterback's throws would be
    # counted twice -- once as his and again as his receivers'.
    row["tot_yds"] = row["rush_yds"] + row["rec_yds"]
    row["tot_td"] = row["rush_td"] + row["rec_td"]
    return row


# ---------------------------------------------------------------------------
# The matchup summary -- what the page shows before a team is picked
# ---------------------------------------------------------------------------

# Per position: which line of the box score it is judged on, who counts, and
# which fields are its yards, touchdowns and long. Players under the bar are
# left out so a backup's one carry or a decoy's lone target does not count as
# the group: rushers need 3+ carries, receivers 2+ targets, passers 10+
# attempts (which keeps a trick-play throw out of the QB line).
#
# `extra` is volume shown beside the three ranked stats, each with its own bar
# -- a back's catches are a receiving number, so they count backs with 2+
# targets, not 3+ carries.
PASSER, RUSHER, RECEIVER = ("pass_att", 10), ("rush_att", 3), ("targets", 2)
SUMMARY_POS = {
    "QB": {"min": PASSER, "yds": "pass_yds", "lng": "pass_lng",
           "extra": {"att": ("pass_att", PASSER), "ptd": ("pass_td", PASSER)}},
    "RB": {"min": RUSHER, "yds": "rush_yds", "lng": "rush_lng",
           "extra": {"att": ("rush_att", RUSHER), "rec": ("rec", RECEIVER)}},
    "WR": {"min": RECEIVER, "yds": "rec_yds", "lng": "rec_lng",
           "extra": {"rec": ("rec", RECEIVER)}},
    "TE": {"min": RECEIVER, "yds": "rec_yds", "lng": "rec_lng",
           "extra": {"rec": ("rec", RECEIVER)}},
}


def qualifies(r, bar):
    return r[bar[0]] >= bar[1]


def summarize(rows, games):
    """-> {pos: {stat: {"med", "avg", "n"}}}: per game, what one defense allowed
    each position group, regular season only. Every position has "yds",
    "lng" and "rrtd"; "att", "rec" and the QB's "ptd" only where they apply.

    A game's value is the group's total from its qualifying players. A game in
    which nobody at the position qualified counts as zero: the defense held
    that group to nothing.

    The long is the exception: it is read per PLAYER, not per game -- every
    qualifying player's long in every game, one value each, and the median of
    those. It answers a single player's longest-reception (or rush, or
    completion) prop; the group's longest each game would only ever be the
    ceiling, and drop every other player's long on the floor. Its `n` is
    player-games, not games.

    Touchdowns are kept apart: "ptd" is passing TDs thrown, "rrtd" rushing plus
    receiving TDs scored. RRTD counts every player at the position who clears
    any bar -- carries, targets, or (for a QB) attempts -- so a quarterback's
    sneak or a receiver's end-around is in it. The page reads TDs by their
    mean, the other stats by their median."""
    game_ids = [g["game_id"] for g in games if not g["postseason"]]
    out = {}
    for pos, spec in SUMMARY_POS.items():
        stats = ("yds", "rrtd") + tuple(spec["extra"])
        per_game = {gid: dict.fromkeys(stats, 0) for gid in game_ids}
        longs = []
        for r in rows:
            g = per_game.get(r["game_id"])
            if g is None or r["pos"] != pos:
                continue
            for stat, (src, bar) in spec["extra"].items():
                if qualifies(r, bar):
                    g[stat] += r[src]
            if any(qualifies(r, bar) for bar in (spec["min"], RUSHER, RECEIVER)):
                g["rrtd"] += r["tot_td"]
            if qualifies(r, spec["min"]):
                g["yds"] += r[spec["yds"]]
                longs.append(r[spec["lng"]])
        out[pos] = {}
        series = {stat: [g[stat] for g in per_game.values()] for stat in stats}
        series["lng"] = longs
        for stat, vals in series.items():
            out[pos][stat] = {
                "med": statistics.median(vals) if vals else 0,
                "avg": round(statistics.mean(vals), 2) if vals else 0,
                "n": len(vals),
            }
    return out


def offense_leaders(by_team):
    """-> {offense: {pos: [up to 2 players]}}: each team's season leaders, as an
    OFFENSE, in the yards its position is judged on.

    Every row's `opp` is the team whose player it is, so this is the defense
    rows regrouped. Only players who appeared in that offense's latest game
    count, which drops the injured, the traded and the benched without an
    injury feed."""
    seasons = {}
    latest = {}
    for entry in by_team.values():
        for r in entry["rows"]:
            off = r["opp"]
            if (r["kickoff"] or "") > latest.get(off, ("", None))[0]:
                latest[off] = (r["kickoff"] or "", r["game_id"])
            spec = SUMMARY_POS.get(r["pos"])
            if not spec:
                continue
            p = seasons.setdefault(off, {}).setdefault(r["pos"], {}).setdefault(
                r["player_id"], {"player_id": r["player_id"], "player": r["player"],
                                 "yds": 0, "games": 0, "last": None})
            p["yds"] += r[spec["yds"]]
            p["games"] += 1
            if (r["kickoff"] or "") >= (p["last"] or ("",))[0]:
                p["last"] = (r["kickoff"] or "", r["game_id"])

    out = {}
    for off, by_pos in seasons.items():
        last_game = latest.get(off, ("", None))[1]
        out[off] = {}
        for pos, players in by_pos.items():
            active = [p for p in players.values() if p["last"][1] == last_game]
            active.sort(key=lambda p: (-p["yds"], p["player"]))
            out[off][pos] = [{k: p[k] for k in ("player_id", "player", "yds", "games")}
                             for p in active[:2]]
    return out


def build(season, games, now):
    """-> {team: payload} for every team that appears in a final game.

    Each game is read twice, once from each defense's side: the away team's
    defense faced the home side's players and vice versa."""
    by_team = {}
    for g in games:
        game = g.get("game") or {}
        stats = g.get("stats") or {}
        long_pass = long_completions(g.get("plays"))
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
                row = player_row(p, long_pass)
                if row:
                    row.update(game_id=g["game_id"], week=g.get("week"),
                               kickoff=g.get("kickoff"), opp=opp)
                    entry["rows"].append(row)

    leaders = offense_leaders(by_team)
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
            # What this team's defense allows each position, per game.
            "summary": summarize(entry["rows"], entry["games"]),
            # This team as an OFFENSE: its leaders by position, named beside
            # the matchups where it faces a soft or stingy defense.
            "leaders": leaders.get(team, {}),
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
                p = payloads.get(team) or {}
                for pos, stats in (p.get("summary") or {}).items():
                    print(f"  allowed {pos}: " + "  ".join(
                        f"{s} med {v['med']} avg {v['avg']}" for s, v in stats.items())
                        + f"  (n={stats['yds']['n']})")
                for pos, players in (p.get("leaders") or {}).items():
                    print(f"  offense {pos}: " + ", ".join(
                        f"{x['player']} {x['yds']}" for x in players))
            return 0
        publish(season, payloads, now)
        print(f"published {len(payloads)} rows to {TABLE}")
    except BuildError as e:
        print(f"\n{e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
