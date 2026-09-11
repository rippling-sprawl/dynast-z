#!/usr/bin/env python3
"""
Fetch the last three completed seasons' half-PPR POSITIONAL FINISHES and save to
data/nfl_pos_ranks.json.

Why this exists
---------------
The board's Δ column says where the market has a player this year, and the
weekly chip says how many weeks he was startable last year. Neither says the
plainest fact about him: where he finished. "RB4 in 2025, RB19 in 2024" is the
one line that separates a back who has been elite three years running from one
coming off a career year — and it's the number people already carry in their heads, because
it's what Sleeper's own player card prints.

So this ships exactly what that card shows: `pos_rank_half_ppr` from the season
stats endpoint, verbatim, for Y-1 through Y-3. Not recomputed, not re-scored.

Deliberately NOT league-scored, unlike the weekly counts
--------------------------------------------------------
fetch_nfl_weekly.py ships raw component stats so the browser can score them by
YOUR league's settings. This file does the opposite and ships Sleeper's finished
number. That is the point: a positional finish is a shared reference everyone
quotes the same way ("he was the WR7"), and half-PPR is the format it's quoted
in. A league-scored finish nobody else uses would be a different, more private
number wearing the same name. The weekly counts already answer the
under-my-rules question, and answering it twice in two different grammars on the
same row would make neither readable.

Sibling of fetch_nfl_weekly.py — same UA requirement, same player keys, same
verify-before-write discipline.

Usage:
    python3 scripts/fetch_pos_ranks.py                    # last three seasons
    python3 scripts/fetch_pos_ranks.py --seasons 2025,2024,2023
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

# Three seasons. Two showed whether last year was real; three shows the shape —
# a back who has been top-12 three straight years reads differently from one who
# spiked once, and that distinction is invisible at two. Affordable now that the
# line is opt-in: the History chip is off by default, so the third number costs
# nothing on a board nobody asked to annotate.
SEASON_COUNT = 3

# Sanity floor per season. A finished season has ~700 fantasy-relevant players
# who took a snap; far below that means the API shape changed or the season
# wasn't played.
MIN_EXPECTED_RANKED = 400

FANTASY_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")

RANK_KEY = "pos_rank_half_ppr"

# Reuse the server's cached players dump when it's fresh — it's ~16 MB, and
# fetch_nfl_weekly.py already treats it this way.
PLAYERS_CACHE_MAX_AGE = 86400


def curl_fetch(url):
    """Sleeper 403s urllib's default User-Agent but serves curl with a browser
    UA. Any client here needs an explicit UA or every request fails."""
    result = subprocess.run(
        ["curl", "-s", "-A", UA, "--max-time", "60", url],
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
# in scripts/primary/oven-board.js — and to the identical pair in
# fetch_nfl_weekly.py. The board joins by this key rather than by player_id,
# because player_id is null on every FantasyPros-seeded row. If these drift, the
# join silently returns nothing and every row renders a dash.
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
    """player_id -> (fantasy_pos, primary_pos, team, name)."""
    cache = repo_path("cache", "sleeper_players.json")
    if os.path.exists(cache) and (time.time() - os.path.getmtime(cache)) < PLAYERS_CACHE_MAX_AGE:
        print(f"Using cached players dump ({cache})")
        with open(cache) as f:
            raw = json.load(f)
    else:
        print(f"Fetching {SLEEPER_API}/players/nfl (~16 MB) ...")
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
        meta[pid] = (pos, (p.get("position") or "").upper(),
                     (p.get("team") or "").upper(), name)
    print(f"  {len(meta):,} fantasy-relevant players of {len(raw):,} total")
    return meta


def build_season(season, players):
    """{playerKey: rank} for one season, plus a count of what was skipped."""
    url = f"{SLEEPER_API}/stats/nfl/regular/{season}"
    data = curl_fetch(url)
    if not isinstance(data, dict):
        raise RuntimeError(f"unexpected shape for {season}: {type(data)}")

    ranks, skipped_pos, collisions = {}, 0, []

    for pid, stats in data.items():
        if not isinstance(stats, dict):
            continue
        entry = players.get(pid)
        if not entry:
            # Drops IDP, practice-squad noise, and the TEAM_* aggregate rows
            # that ride alongside real players carrying pos_rank_* = 999.
            continue
        fan_pos, primary_pos, team, name = entry
        rank = stats.get(RANK_KEY)
        if not isinstance(rank, (int, float)) or rank <= 0:
            continue

        # Sleeper ranks EVERY player in its database for every season, played or
        # not: a rookie who wasn't in the league in 2024 still carries a 2024
        # `pos_rank_half_ppr` in the 500s, because the zero-point block gets
        # ordered arbitrarily and has to be ordered somehow. Printed on a row,
        # "WR582" for a man who was in college would be a fabricated finish. So
        # the gate is games played: he has a finish for a season he played in,
        # and a dash for one he didn't. Zero-point seasons survive the gate —
        # playing and scoring nothing is a real, if grim, finish.
        if not stats.get("gp"):
            continue

        # Sleeper ranks within its own `position`, not within fantasy_positions.
        # Kyle Juszczyk is fantasy_positions ["RB"] and position "FB", and his
        # pos_rank_half_ppr of 1 means FB1 — 45 points on the season. Printed as
        # "RB1" on a board row that is otherwise about Christian McCaffrey, that
        # is not a small error. Any player whose two positions disagree is
        # dropped: the number he has is a true fact about a pool the board can't
        # name, which makes it unusable rather than merely imprecise.
        if primary_pos != fan_pos:
            skipped_pos += 1
            continue

        key = player_key(name, fan_pos, team)
        prev = ranks.get(key)
        if prev is not None:
            # Two player_ids normalizing to one key. The board can't tell them
            # apart either, so keep the better finish — in every real case
            # (a retired namesake, a practice-squad twin) that's the one the
            # board means. Reported, never silent.
            collisions.append((key, prev, int(rank)))
            if int(rank) >= prev:
                continue
        ranks[key] = int(rank)

    print(f"  {season}: {len(data):>5} stat rows -> {len(ranks):>4} ranked "
          f"({skipped_pos} dropped for position mismatch)")
    for key, a, b in collisions:
        print(f"    collision {key}: kept {min(a, b)}, dropped {max(a, b)}")
    return ranks


def verify(by_season, seasons):
    """Fail loudly rather than overwrite good data with a bad parse."""
    ok = True

    for season in seasons:
        ranks = by_season[season]
        if len(ranks) < MIN_EXPECTED_RANKED:
            print(f"ERROR: only {len(ranks)} ranked players for {season}, expected "
                  f"at least {MIN_EXPECTED_RANKED}. Refusing to overwrite good data.",
                  file=sys.stderr)
            return False

        by_pos = {}
        for key in ranks:
            pos = key.split("|", 1)[0]
            by_pos[pos] = by_pos.get(pos, 0) + 1
        missing = [p for p in FANTASY_POSITIONS if p not in by_pos]
        if missing:
            print(f"ERROR: {season} has no players at position(s): "
                  f"{', '.join(missing)}", file=sys.stderr)
            ok = False

        # Every position must have exactly one #1 and a contiguous-ish top. A
        # rank pool that starts at 3, or has two #1s, means the position
        # grouping is wrong — which is the failure mode the mismatch drop above
        # exists to prevent, so it gets checked rather than assumed.
        firsts = {}
        for key, rank in ranks.items():
            pos = key.split("|", 1)[0]
            firsts.setdefault(pos, []).append(rank)
        print(f"\n  {season} positional pools:")
        for pos in FANTASY_POSITIONS:
            vals = sorted(firsts.get(pos, []))
            if not vals:
                continue
            dupes = len(vals) - len(set(vals))
            print(f"    {pos}: {len(vals):>4} ranked, best {vals[0]}, worst {vals[-1]}"
                  + (f", {dupes} duplicate rank(s)" if dupes else ""))
            if vals[0] != 1:
                print(f"ERROR: {season} {pos} has no #1 finisher (best is {vals[0]})",
                      file=sys.stderr)
                ok = False

    # A player the board will actually show, spot-checked end to end. If the key
    # normalization drifts from oven-board.js this is what catches it, since a
    # drifted key produces a perfectly valid-looking file that joins to nothing.
    probe = "RB|" + norm_name("Christian McCaffrey")
    for season in seasons:
        if probe not in by_season[season]:
            print(f"WARNING: probe key {probe!r} missing from {season} — check "
                  f"norm_name() against oven-board.js")

    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    # An NFL season is named for the year it starts, so through the summer the
    # most recent COMPLETED season is last year's.
    default_last = datetime.now(timezone.utc).year - 1
    ap.add_argument("--seasons", default=None,
                    help=f"comma-separated, newest first "
                         f"(default {default_last},{default_last - 1},{default_last - 2})")
    args = ap.parse_args()

    if args.seasons:
        seasons = [int(x) for x in args.seasons.split(",")]
    else:
        seasons = [default_last - i for i in range(SEASON_COUNT)]

    print(f"Building half-PPR positional finishes for "
          f"{', '.join(str(s) for s in seasons)}\n")

    players = load_players()
    print("\nFetching season stats ...")
    by_season = {s: build_season(s, players) for s in seasons}

    if not verify(by_season, seasons):
        return 1

    # Key-major, one array per player in `seasons` order: the row renderer wants
    # every year for one player at once, and this way each key string is stored
    # once instead of per season. `null` — not 0, not a missing slot — for a year
    # he didn't finish, so the array is always the same length as `seasons` and
    # the reader never has to ask which year a lone number belongs to.
    keys = set()
    for s in seasons:
        keys.update(by_season[s])
    ranks = {}
    for key in sorted(keys):
        ranks[key] = [by_season[s].get(key) for s in seasons]

    out = {"seasons": seasons, "ranks": ranks}

    data_dir = repo_path("data")
    os.makedirs(data_dir, exist_ok=True)
    out_path = os.path.join(data_dir, "nfl_pos_ranks.json")
    with open(out_path, "w") as f:
        # Compact: this ships to every board load.
        json.dump(out, f, separators=(",", ":"))
    size_kb = os.path.getsize(out_path) / 1024
    print(f"\nWrote {len(ranks)} players to {os.path.abspath(out_path)} "
          f"({size_kb:.0f} KB)")

    meta = {
        "source": "Sleeper",
        "stat": RANK_KEY,
        "seasons": seasons,
        "player_count": len(ranks),
        "per_season": {str(s): len(by_season[s]) for s in seasons},
        "size_bytes": os.path.getsize(out_path),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fetched_ts": int(time.time()),
        "url": f"{SLEEPER_API}/stats/nfl/regular/{{season}}",
    }
    meta_path = os.path.join(data_dir, "nfl_pos_ranks_meta.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Wrote metadata to {os.path.abspath(meta_path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
