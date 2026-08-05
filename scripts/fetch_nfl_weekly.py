#!/usr/bin/env python3
"""
Fetch a completed NFL season's WEEKLY stat lines and save to
data/nfl_weekly_{season}.json.

Why this exists
---------------
The Oven board ranks by FantasyPros half-PPR consensus — a projection of this
season under someone else's scoring. This file answers the backward-looking
question instead: under MY league's scoring, how many weeks last season did a
player actually finish top 12 at his position?

Sleeper has no endpoint for that. It serves only three fixed rank formats
(pos_rank_ppr / pos_rank_half_ppr / pos_rank_std), and their GraphQL schema —
which is open and introspectable — has no stats field that accepts a league_id.
The weekly rank on Sleeper's own player card is computed client-side by their
app. So we compute it too: the stats endpoint returns RAW component stats, and
a league's scoring_settings keys map 1:1 onto those stat keys, which makes
fantasy points a plain dot product.

This script ships the raw components. scripts/primary/oven-weekly.js does the
dot product in the browser, where scoring_settings is already in memory. That
split is deliberate: the stats for a finished season never change (commit them,
serve from the CDN), while the scoring is per-league and can't be precomputed.

Sibling of fetch_fp_redraft.py — same shape, same conventions. Re-run only when
adding a new season; a completed season's output is stable forever.

Usage:
    python3 scripts/fetch_nfl_weekly.py                 # previous season, wks 1-17
    python3 scripts/fetch_nfl_weekly.py --season 2024
    python3 scripts/fetch_nfl_weekly.py --weeks 1-18
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from datetime import datetime, timezone

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

SLEEPER_API = "https://api.sleeper.app/v1"

# Week 18 is excluded by default: starters rest, and a resting stud's zero would
# read as a failed week rather than a week he was never asked to play.
DEFAULT_WEEKS = "1-17"

# Sanity floors. A finished season has ~2,300 stat lines a week across ~700
# fantasy-relevant players. Anything far below means the API shape changed or we
# fetched a season that hasn't been played.
MIN_EXPECTED_PLAYERS = 400
MIN_EXPECTED_WEEK_ROWS = 1000

FANTASY_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")

# Keys to strip. This list is deliberately literal and MUST NOT become a prefix
# match: `^pts_` looks equivalent and silently destroys pts_allow / pts_allow_0
# ... pts_allow_35p, which are real DST stats that leagues score. Every key not
# named here is kept, because any of them may appear in some league's
# scoring_settings and a dropped key is points that silently go missing.
#
# What's here is only the derived stuff — Sleeper's own precomputed points and
# ranks (which are exactly what we're recomputing) plus game-count bookkeeping.
DENY_KEYS = {
    "pts_ppr", "pts_half_ppr", "pts_std",
    "rank_ppr", "rank_half_ppr", "rank_std",
    "pos_rank_ppr", "pos_rank_half_ppr", "pos_rank_std",
    "gp", "gs", "gms_active",
    "tm_def_snp", "tm_off_snp", "tm_st_snp",
}

# Reuse the server's cached players dump when it's fresh — it's 14.6 MB, and
# this script is the only other consumer.
PLAYERS_CACHE_MAX_AGE = 86400


def curl_fetch(url):
    """Sleeper 403s urllib's default User-Agent but serves curl with a browser
    UA. Any client here needs an explicit UA or every request fails."""
    result = subprocess.run(
        ["curl", "-s", "-A", UA, "--max-time", "30", url],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"curl failed for {url}: {result.stderr.strip()}")
    if not result.stdout.strip():
        raise RuntimeError(f"empty response for {url}")
    return json.loads(result.stdout)


def repo_path(*parts):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", *parts)


# ---------------------------------------------------------------------------
# Player keys
#
# These MUST stay byte-for-byte equivalent to playerKey()/normName()/normPos()
# in scripts/primary/oven-board.js. The board joins this file by that key rather
# than by player_id, because player_id is null on every FantasyPros-seeded row —
# only CSV-imported rows carry one. If these two normalizations ever drift, the
# join silently returns nothing and every row renders as a dash.
# ---------------------------------------------------------------------------

_SUFFIXES = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b")


def norm_name(s):
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.lower().replace(".", "")
    s = re.sub(r"['‘’`]", "", s)
    s = re.sub(r"[-–—]", " ", s)
    s = _SUFFIXES.sub("", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def player_key(name, pos, team):
    # Defenses key on team code, never name — the sources spell them three
    # different ways ("Denver Broncos" / "Broncos D/ST" / first+last name).
    if pos == "DEF":
        return "DEF|" + (team or "").upper()
    return pos + "|" + norm_name(name)


def load_players():
    """player_id -> (position, team, name) for fantasy-relevant players."""
    cache = repo_path("cache", "sleeper_players.json")
    raw = None
    if os.path.exists(cache) and (time.time() - os.path.getmtime(cache)) < PLAYERS_CACHE_MAX_AGE:
        print(f"Using cached players dump ({cache})")
        with open(cache) as f:
            raw = json.load(f)
    else:
        print(f"Fetching {SLEEPER_API}/players/nfl (~15 MB) ...")
        raw = curl_fetch(f"{SLEEPER_API}/players/nfl")

    meta = {}
    for pid, p in raw.items():
        positions = p.get("fantasy_positions") or []
        pos = next((x for x in positions if x in FANTASY_POSITIONS), None)
        if not pos:
            continue
        name = p.get("full_name") or " ".join(
            filter(None, [p.get("first_name"), p.get("last_name")])
        )
        meta[pid] = (pos, (p.get("team") or "").upper(), name)
    print(f"  {len(meta):,} fantasy-relevant players of {len(raw):,} total")
    return meta


def parse_weeks(spec):
    m = re.fullmatch(r"(\d+)-(\d+)", spec.strip())
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if lo < 1 or hi < lo:
            raise ValueError(f"bad week range: {spec}")
        return list(range(lo, hi + 1))
    return [int(x) for x in spec.split(",")]


def build(season, weeks, players):
    """{playerKey: {"pid": id, "w": {week: {stat: value}}}}"""
    out = {}
    total_rows = 0

    for week in weeks:
        url = f"{SLEEPER_API}/stats/nfl/regular/{season}/{week}"
        data = curl_fetch(url)
        if not isinstance(data, dict):
            raise RuntimeError(f"unexpected shape for week {week}: {type(data)}")

        kept = 0
        for pid, stats in data.items():
            if not isinstance(stats, dict):
                continue
            entry = players.get(pid)
            if not entry:
                # Drops IDP, practice-squad noise, and the TEAM_* aggregate rows
                # that ride alongside real players. Those aggregates carry an
                # inflated pts_ppr and pos_rank_* = 999; left in, they would sit
                # atop every weekly ranking and push real players out of the
                # top 12. Team DEFs survive because the players dump lists them
                # with fantasy_positions ["DEF"].
                continue
            pos, team, name = entry
            row = {k: v for k, v in stats.items() if k not in DENY_KEYS and v}
            if not row:
                continue
            key = player_key(name, pos, team)
            rec = out.setdefault(key, {"pid": pid, "w": {}})
            rec["w"][str(week)] = row
            kept += 1

        total_rows += kept
        print(f"  week {week:>2}: {len(data):>4} rows -> {kept:>4} kept")
        if kept < MIN_EXPECTED_WEEK_ROWS // len(weeks):
            print(f"    WARNING: week {week} kept unusually few rows")

    return out, total_rows


def verify(out, season):
    """Fail loudly rather than overwrite good data with a bad parse."""
    ok = True

    if len(out) < MIN_EXPECTED_PLAYERS:
        print(f"ERROR: only {len(out)} players parsed, expected at least "
              f"{MIN_EXPECTED_PLAYERS}. Refusing to overwrite good data.",
              file=sys.stderr)
        return False

    by_pos = {}
    for key in out:
        pos = key.split("|", 1)[0]
        by_pos[pos] = by_pos.get(pos, 0) + 1
    print("\nPosition counts:")
    for pos in sorted(by_pos, key=lambda k: -by_pos[k]):
        print(f"  {pos}: {by_pos[pos]}")

    missing = [p for p in FANTASY_POSITIONS if p not in by_pos]
    if missing:
        print(f"ERROR: no players for position(s): {', '.join(missing)}", file=sys.stderr)
        ok = False

    stray = sorted(set(by_pos) - set(FANTASY_POSITIONS))
    if stray:
        print(f"WARNING: unexpected position code(s) {stray}")

    # The scoring keys most likely to be lost to an over-eager filter. A league
    # that scores DST points-allowed or return yardage would silently grade
    # those players at zero, and nothing downstream would flag it.
    canaries = ("pts_allow", "kr_yd", "pr_yd", "fgm_yds", "rec", "rush_yd", "pass_yd")
    seen = set()
    for rec in out.values():
        for wk in rec["w"].values():
            seen.update(wk)
    for key in canaries:
        if key not in seen:
            print(f"ERROR: scoring-relevant key '{key}' survived nowhere in the "
                  f"output — check DENY_KEYS.", file=sys.stderr)
            ok = False
    print(f"\n{len(seen)} distinct stat keys retained")

    # Any TEAM_* aggregate that slipped through would outrank real players.
    strays = [k for k in out if "team_" in k.lower()]
    if strays:
        print(f"ERROR: TEAM_* aggregate rows leaked into the output: {strays[:5]}",
              file=sys.stderr)
        ok = False

    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    # An NFL season is named for the year it starts, so through the summer the
    # most recent COMPLETED season is last year's.
    ap.add_argument("--season", type=int, default=datetime.now(timezone.utc).year - 1)
    ap.add_argument("--weeks", default=DEFAULT_WEEKS,
                    help=f"week range or list (default {DEFAULT_WEEKS})")
    args = ap.parse_args()

    weeks = parse_weeks(args.weeks)
    print(f"Building weekly stats for {args.season}, weeks "
          f"{weeks[0]}-{weeks[-1]} ({len(weeks)} weeks)\n")

    players = load_players()
    print(f"\nFetching weekly stats ...")
    out, total_rows = build(args.season, weeks, players)
    print(f"\n{len(out)} players, {total_rows:,} player-weeks")

    if not verify(out, args.season):
        return 1

    data_dir = repo_path("data")
    os.makedirs(data_dir, exist_ok=True)

    out_path = os.path.join(data_dir, f"nfl_weekly_{args.season}.json")
    with open(out_path, "w") as f:
        # Compact: this ships to every board load. It gzips ~6x on the wire.
        json.dump(out, f, separators=(",", ":"))
    size_mb = os.path.getsize(out_path) / 1e6
    print(f"\nWrote {len(out)} players to {os.path.abspath(out_path)} ({size_mb:.2f} MB)")

    meta = {
        "source": "Sleeper",
        "season": args.season,
        "weeks": weeks,
        "player_count": len(out),
        "player_weeks": total_rows,
        "size_bytes": os.path.getsize(out_path),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fetched_ts": int(time.time()),
        "url": f"{SLEEPER_API}/stats/nfl/regular/{args.season}/{{week}}",
    }
    meta_path = os.path.join(data_dir, f"nfl_weekly_{args.season}_meta.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Wrote metadata to {os.path.abspath(meta_path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
