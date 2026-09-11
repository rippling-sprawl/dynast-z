#!/usr/bin/env python3
"""
Project 2026 NFL red-zone rushing usage per player and per team.

Why this exists
---------------
The question is how many red-zone carries each team and each player will get in
2026. Nothing in this repo answered it: `rush_rz_att` sits unused in
data/nfl_weekly_2025.json, and it is inside-20 only, for one season. The input
is instead a hand-maintained sheet of Inside-10 / Inside-5 Att, TD and %Rush for
2022-2025, snapshotted here as data/rz_input_2022_2025.csv.

The modelling problem is that usage is two separate things that decay at
different rates and, in an offseason, move independently:

  * TEAM volume  - how many carries a team takes inside the 10 / inside the 5.
    This is a property of the scheme and stays with the team.
  * PLAYER share - what fraction of those the player takes. This is a property
    of the player and travels with him when he signs elsewhere.

So the projection is the product of the two, each decayed separately:

    Att_2026 = TeamVolume_2026(his 2026 team) x PlayerShare_2026

That product is the whole point. Kenneth Walker's Seattle share applied to
Kansas City's volume is a different number than either input alone, and the
same holds for Travis Etienne (-> NO), David Montgomery (-> HOU) and Chris
Rodriguez (-> JAX). 2026 teams come from the Sleeper players dump this repo
already caches.

The sheet never states team volume. It is recovered from the identity the
%Rush column implies -- Att / %Rush == the team total -- which reproduces
consistently across every player on a roster (see derive_team_volume).

Sibling of fetch_nfl_weekly.py: same conventions, same hard-fail-rather-than-
overwrite posture. Re-run whenever the sheet or the Sleeper dump changes.

Usage:
    python3 scripts/fetch_rz_projections.py
    python3 scripts/fetch_rz_projections.py --offline     # use the snapshot
    python3 scripts/fetch_rz_projections.py --k-i10 12
"""

import argparse
import csv
import json
import os
import re
import statistics
import subprocess
import sys
import time
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

SHEET_ID = "1l_yqv1_uK8yi3udtdBZipiSl2_kRM-u_zPocYim47S8"
SHEET_GID = "676902847"
SHEET_URL = (f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
             f"/export?format=csv&gid={SHEET_GID}")

TARGET_SEASON = 2026

# Decay weights. Renormalized over whatever seasons an entity actually has, so
# a player who debuted in 2024 is weighted .50/.30 -> .625/.375 rather than
# being penalized for seasons he could not have played.
DECAY = {"2025": 0.50, "2024": 0.30, "2023": 0.15, "2022": 0.05}
SEASONS = tuple(sorted(DECAY, reverse=True))

# Shrinkage strength, in units of "team red-zone opportunities". See
# project_share() for why the sample size is team opportunities and not the
# player's own attempts.
#
# Deliberately weak. The usual reason to shrink a rate -- a tiny denominator
# throwing an extreme value -- does not arise here, because %Rush is measured
# against the team's whole season, so a 4-carry backup mathematically cannot
# show a 90% share (no such row exists in 2022-2025). What shrinkage does do at
# any real strength is drag documented zeros upward, which is worse than useless:
# a back who took 0 of his team's 20 red-zone carries has told us something
# precise. These values leave a full-season player within a point of his
# observed rate and only move players seen for a single thin season.
DEFAULT_K_I10 = 2.0
DEFAULT_K_I5 = 1.0

# Shares are estimated per player, so nothing makes a roster's shares sum to 1.
# In practice they overshoot badly: a 2026 roster collects players who each held
# a big share on different teams in different years, and those shares were never
# simultaneous (Philadelphia rosters Barkley at 50% of PHI, Bigsby at 52% of JAX
# and Hurts at 37% of PHI -- 186% between them). No 2022-2025 team-season sums
# past 100%, so this is a hard constraint, not a tendency. Teams that break it
# are scaled back proportionally; teams under it are left alone, since their
# slack is real -- it belongs to rookies and others the sheet never listed.
MAX_TEAM_SHARE = 1.0

# The sheet lists every player with at least one red-zone carry, so a 1-for-1
# season yields a raw TD rate of 1.00. Ratio-of-weighted-sums damps that for
# players with real history but cannot fix a player whose entire record is one
# attempt. Cap at the best rate anyone has managed on a starter's workload
# (att >= 15): 0.591 inside the 10, 0.735 inside the 5. This is a guardrail on
# nonsense, not a model term -- it can only bind above anything ever observed at
# volume, and every player it binds on is reported.
MAX_TD_RATE_I10 = 0.591
MAX_TD_RATE_I5 = 0.735

# Sanity floors. Observed 2022-2025 ranges are i10 15-72 and i5 2-41 per team;
# these bound an order of magnitude wider, so tripping one means the parse or
# the sheet's share definition broke, not that a team had an odd year.
MIN_TEAM_I10, MAX_TEAM_I10 = 10.0, 100.0
MIN_TEAM_I5, MAX_TEAM_I5 = 1.0, 60.0
MIN_PLAYER_ROWS, MAX_PLAYER_ROWS = 260, 340
EXPECTED_TEAMS = 32

# The sheet writes Pro-Football-Reference abbreviations; Sleeper writes its own.
# Neither existing map in this repo covers the crossing on its own --
# outright_common._ABBR_ALIAS lacks GNB/LVR, server._TEAM_ALIASES lacks the PFR
# three-letter forms -- so the merged map lives here.
PFR_TO_SLEEPER = {
    "GNB": "GB", "KAN": "KC", "LVR": "LV", "NOR": "NO", "NWE": "NE",
    "NWN": "NE", "SFO": "SF", "TAM": "TB", "JAC": "JAX", "WSH": "WAS",
    "LA": "LAR", "GBP": "GB", "KCC": "KC", "NOS": "NO", "NEP": "NE",
    "TBB": "TB", "OAK": "LV", "SD": "LAC", "STL": "LAR",
}
SLEEPER_TO_PFR = {"GB": "GNB", "KC": "KAN", "LV": "LVR", "NO": "NOR",
                  "NE": "NWE", "SF": "SFO", "TB": "TAM"}

# Players whose sheet name does not normalize onto exactly one Sleeper record.
# Kept literal and short on purpose: a fuzzy matcher here would silently attach
# a player's history to the wrong 2026 team, which is the one error this whole
# script exists to avoid.
PLAYER_ID_OVERRIDES = {
    "Kenneth Walker": "8151",    # collides with a teamless WR of the same name
    "Josh Johnson": "260",       # the QB; collides with a teamless RB and WR
    # The rest are all unsigned, so they get dropped either way -- the override
    # only pins the position that feeds the shrinkage baselines.
    "Tony Jones": "6984",        # the Notre Dame RB, not the Northwestern WR
    "David Johnson": "2391",     # the Northern Iowa RB, not the Ark. State TE
    "Ronald Jones": "4955",      # Sleeper carries two records for the USC RB
}
NAME_ALIASES = {
    "Kenneth Gainwell": "Kenny Gainwell",
    "Nyheim Hines": "Nyheim Miller-Hines",
}
# Positions searched in the Sleeper dump. OL is included for Robert Hunt, a
# guard who took a goal-line carry and is therefore in the sheet.
MATCH_POSITIONS = ("RB", "QB", "WR", "TE", "FB", "OL")

# Column layout of the input sheet, both header rows and every data row.
C_SEASON, C_PLAYER, C_TEAM = 0, 1, 2
C_I10_ATT, C_I10_TD, C_I10_PCT = 3, 4, 5
C_I5_ATT, C_I5_TD, C_I5_PCT = 6, 7, 8

MULTI_TEAM = "2TM"

_SUFFIXES = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b")


def repo_path(*parts):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", *parts)


def norm_name(s):
    """Matches norm_name() in fetch_nfl_weekly.py / oven-board.js."""
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.lower().replace(".", "")
    s = re.sub(r"['‘’`]", "", s)
    s = re.sub(r"[-–—]", " ", s)
    s = _SUFFIXES.sub("", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def pct(cell):
    """'80.40%' -> 0.804. Blank -> None (only the 2TM rows are blank)."""
    cell = (cell or "").strip().rstrip("%")
    if not cell:
        return None
    return float(cell) / 100.0


def num(cell):
    cell = (cell or "").strip()
    return float(cell) if cell else 0.0


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

def fetch_sheet(offline):
    """Return (header_row_1, header_row_2, data_rows). Snapshots to data/."""
    snapshot = repo_path("data", "rz_input_2022_2025.csv")

    if offline:
        if not os.path.exists(snapshot):
            raise RuntimeError(f"--offline but no snapshot at {snapshot}")
        print(f"Reading snapshot {snapshot}")
        with open(snapshot, newline="") as f:
            text = f.read()
    else:
        print(f"Fetching {SHEET_URL}")
        result = subprocess.run(
            ["curl", "-sL", "-A", UA, "--max-time", "60", SHEET_URL],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"curl failed: {result.stderr.strip()}")
        text = result.stdout
        if text.lstrip().startswith("<"):
            raise RuntimeError(
                "sheet returned HTML, not CSV -- it is probably no longer "
                "link-viewable. Re-share it, or re-run with --offline.")
        os.makedirs(os.path.dirname(snapshot), exist_ok=True)
        with open(snapshot, "w", newline="") as f:
            f.write(text)
        print(f"  snapshotted to {snapshot} ({len(text):,} bytes)")

    rows = list(csv.reader(text.splitlines()))
    if len(rows) < 2:
        raise RuntimeError("sheet has no header rows")

    # Four season blocks are stacked vertically, each led by its own header row.
    # Every data row repeats its season in column A, so the season is read off
    # the row itself rather than tracked as parser state.
    data = [r for r in rows
            if len(r) > C_I5_PCT
            and r[C_SEASON] in DECAY
            and r[C_PLAYER].strip()
            and r[C_PLAYER].strip() != "Player"]

    print(f"  {len(rows)} rows -> {len(data)} data rows, "
          f"{len({r[C_PLAYER] for r in data})} distinct players")
    return rows[0], rows[1], data


def load_sleeper_players():
    """normalized name -> [player record], plus player_id -> record."""
    cache = repo_path("cache", "sleeper_players.json")
    if not os.path.exists(cache):
        raise RuntimeError(
            f"{cache} not found. Run the server once, or "
            f"python3 scripts/fetch_nfl_weekly.py, to populate it.")
    with open(cache) as f:
        raw = json.load(f)

    by_name = defaultdict(list)
    by_id = {}
    for pid, p in raw.items():
        if p.get("position") not in MATCH_POSITIONS:
            continue
        name = p.get("full_name") or " ".join(
            filter(None, [p.get("first_name"), p.get("last_name")]))
        rec = {
            "pid": pid,
            "name": name,
            "position": p.get("position"),
            "team": (p.get("team") or "").upper() or None,
        }
        by_name[norm_name(name)].append(rec)
        by_id[pid] = rec

    age_days = (time.time() - os.path.getmtime(cache)) / 86400
    print(f"Sleeper dump: {len(by_id):,} candidates, {age_days:.1f} days old")
    if age_days > 30:
        print("  WARNING: dump is over a month stale; 2026 teams may be wrong")
    return by_name, by_id


# ---------------------------------------------------------------------------
# Team volume
# ---------------------------------------------------------------------------

def derive_team_volume(data):
    """(season, sleeper_team) -> {"i10": total, "i5": total}.

    The sheet never states team totals, but %Rush is the player's share of them,
    so Att / %Rush recovers the total from any single player. Every player on a
    roster should imply the same number; they differ only because %Rush is
    rounded to one decimal. Take the median to reject that rounding, and fail if
    the spread is wide enough to mean %Rush is not what we think it is.
    """
    implied = defaultdict(lambda: {"i10": [], "i5": []})
    for r in data:
        if r[C_TEAM] == MULTI_TEAM:
            continue  # split season: %Rush is blank, no single team to credit
        team = PFR_TO_SLEEPER.get(r[C_TEAM], r[C_TEAM])
        for depth, c_att, c_pct in (("i10", C_I10_ATT, C_I10_PCT),
                                    ("i5", C_I5_ATT, C_I5_PCT)):
            share, att = pct(r[c_pct]), num(r[c_att])
            if share and att:
                implied[(r[C_SEASON], team)][depth].append(att / share)

    volume, spreads, bad = {}, {}, []
    for key, depths in sorted(implied.items()):
        volume[key] = {}
        for depth, vals in depths.items():
            if not vals:
                continue
            volume[key][depth] = statistics.median(vals)
            spread = max(vals) - min(vals)
            spreads[f"{key[0]}|{key[1]}|{depth}"] = round(spread, 2)
            if spread > 3.0:
                bad.append((key, depth, round(spread, 1), len(vals)))

    if bad:
        print("ERROR: implied team totals disagree by more than 3 carries. The "
              "%Rush column is not a share of the team total as assumed:",
              file=sys.stderr)
        for key, depth, spread, n in bad[:10]:
            print(f"  {key[0]} {key[1]} {depth}: spread {spread} over {n} players",
                  file=sys.stderr)
        raise RuntimeError("team volume derivation failed")

    seasons = {k[0] for k in volume}
    teams = {k[1] for k in volume}
    worst = max(spreads.values()) if spreads else 0.0
    print(f"Team volume: {len(volume)} team-seasons across {len(seasons)} "
          f"seasons, {len(teams)} teams (worst spread {worst:.2f} carries)")
    return volume, spreads


def weighted(pairs):
    """[(season, value)] -> decay-weighted mean, renormalized. None if empty."""
    num_, den = 0.0, 0.0
    for season, value in pairs:
        w = DECAY[season]
        num_ += w * value
        den += w
    return (num_ / den) if den else None


def project_team_volume(volume):
    """sleeper_team -> {"i10": att, "i5": att} for TARGET_SEASON."""
    by_team = defaultdict(lambda: defaultdict(list))
    for (season, team), depths in volume.items():
        for depth, total in depths.items():
            by_team[team][depth].append((season, total))

    out = {}
    for team, depths in by_team.items():
        out[team] = {d: weighted(v) for d, v in depths.items() if v}
    return out


# ---------------------------------------------------------------------------
# Player projection
# ---------------------------------------------------------------------------

def build_player_history(data, by_name, by_id):
    """Sheet name -> {"rows": [...], "sleeper": rec or None}."""
    players = defaultdict(lambda: {"rows": [], "sleeper": None})
    for r in data:
        players[r[C_PLAYER].strip()]["rows"].append(r)

    unmatched = []
    for name, entry in players.items():
        pid = PLAYER_ID_OVERRIDES.get(name)
        if pid:
            entry["sleeper"] = by_id.get(pid)
            if not entry["sleeper"]:
                raise RuntimeError(f"override player_id {pid} for {name} not in dump")
            continue

        candidates = by_name.get(norm_name(NAME_ALIASES.get(name, name)), [])
        if not candidates:
            unmatched.append(name)
            continue
        # Prefer a rostered candidate; the duplicates in the dump are retired
        # namesakes carrying no team.
        rostered = [c for c in candidates if c["team"]]
        if len(rostered) > 1 or (not rostered and len(candidates) > 1):
            raise RuntimeError(
                f"ambiguous match for {name!r}: "
                f"{[(c['pid'], c['position'], c['team']) for c in candidates]} "
                f"-- add a PLAYER_ID_OVERRIDES entry")
        entry["sleeper"] = rostered[0] if rostered else candidates[0]

    if unmatched:
        raise RuntimeError(
            f"{len(unmatched)} sheet players have no Sleeper record: "
            f"{sorted(unmatched)} -- add NAME_ALIASES entries")

    print(f"Matched all {len(players)} sheet players to Sleeper records")
    return players


def positional_baselines(players, depth_cols):
    """position -> decay-weighted mean share, the shrinkage prior.

    Per position because the sheet's share distribution is long-tailed (median
    5.7%, mean 14.1%) and dominated by receivers with a single carry: one global
    prior would drag every running back toward a wideout's usage.
    """
    samples = defaultdict(lambda: defaultdict(list))
    for entry in players.values():
        pos = entry["sleeper"]["position"]
        for r in entry["rows"]:
            if r[C_TEAM] == MULTI_TEAM:
                continue
            for depth, (_c_att, _c_td, c_pct) in depth_cols.items():
                share = pct(r[c_pct])
                if share is not None:
                    samples[depth][pos].append((r[C_SEASON], share))

    out = {d: {p: weighted(v) for p, v in per_pos.items()}
           for d, per_pos in samples.items()}
    for depth in sorted(out):
        shown = ", ".join(f"{p} {out[depth][p]*100:.1f}%"
                          for p in sorted(out[depth], key=lambda k: -out[depth][k]))
        print(f"  baseline share {depth}: {shown}")
    return out


def project_share(entry, depth, c_att, c_pct, volume, baselines, k):
    """Decayed player share, regressed toward the positional baseline.

    The sample size backing a share estimate is the number of team red-zone
    opportunities the player was around for -- the denominator of the
    proportion -- not the number he took himself. Using his own attempts would
    shrink exactly the low-usage players hardest and bias every backup upward
    toward a starter's rate, which is the opposite of what shrinkage is for.
    """
    obs, n_eff = [], 0.0
    for r in entry["rows"]:
        if r[C_TEAM] == MULTI_TEAM:
            continue
        share = pct(r[c_pct])
        if share is None:
            continue
        team = PFR_TO_SLEEPER.get(r[C_TEAM], r[C_TEAM])
        team_total = volume.get((r[C_SEASON], team), {}).get(depth)
        if not team_total:
            continue
        obs.append((r[C_SEASON], share))
        n_eff += DECAY[r[C_SEASON]] * team_total

    raw = weighted(obs)
    if raw is None:
        return None, 0.0, None

    prior = baselines[depth].get(entry["sleeper"]["position"], 0.0)
    return (n_eff * raw + k * prior) / (n_eff + k), n_eff, raw


def td_rate(entry, c_att, c_td, cap):
    """Ratio of decay-weighted sums, which self-weights by sample size.

    2TM seasons count here: TD-per-attempt needs no team attribution, so a
    split season is still evidence about the player.
    """
    num_, den = 0.0, 0.0
    for r in entry["rows"]:
        w = DECAY[r[C_SEASON]]
        num_ += w * num(r[c_td])
        den += w * num(r[c_att])
    if not den:
        return 0.0, False
    rate = num_ / den
    return (cap, True) if rate > cap else (rate, False)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def fmt_pct(x):
    return f"{x * 100:.2f}%"


def write_players(path, header1, header2, rows):
    out2 = list(header2)
    out2[C_SEASON] = str(TARGET_SEASON)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header1)
        w.writerow(out2)
        for r in rows:
            w.writerow([
                TARGET_SEASON, r["name"], r["pfr_team"],
                f"{r['i10_att']:.1f}", f"{r['i10_td']:.1f}", fmt_pct(r["i10_share"]),
                f"{r['i5_att']:.1f}", f"{r['i5_td']:.1f}", fmt_pct(r["i5_share"]),
            ])


def write_teams(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["", "", "Inside 10", "Inside 10", "Inside 5", "Inside 5"])
        w.writerow([str(TARGET_SEASON), "Tm", "Att", "TD", "Att", "TD"])
        for r in rows:
            w.writerow([TARGET_SEASON, r["pfr_team"],
                        f"{r['i10_att']:.1f}", f"{r['i10_td']:.1f}",
                        f"{r['i5_att']:.1f}", f"{r['i5_td']:.1f}"])


def verify(player_rows, team_rows, team_proj):
    """Fail loudly rather than ship a bad projection."""
    ok = True

    if not MIN_PLAYER_ROWS <= len(player_rows) <= MAX_PLAYER_ROWS:
        print(f"ERROR: {len(player_rows)} player rows, expected "
              f"{MIN_PLAYER_ROWS}-{MAX_PLAYER_ROWS}", file=sys.stderr)
        ok = False

    if len(team_rows) != EXPECTED_TEAMS:
        print(f"ERROR: {len(team_rows)} teams, expected {EXPECTED_TEAMS}",
              file=sys.stderr)
        ok = False

    for r in player_rows:
        for depth in ("i10", "i5"):
            share = r[f"{depth}_share"]
            if not 0.0 <= share <= 1.0:
                print(f"ERROR: {r['name']} {depth} share {share:.3f} out of range",
                      file=sys.stderr)
                ok = False
            if r[f"{depth}_td"] > r[f"{depth}_att"] + 1e-9:
                print(f"ERROR: {r['name']} {depth} TD exceeds Att", file=sys.stderr)
                ok = False

    for r in team_rows:
        if not MIN_TEAM_I10 <= r["i10_att"] <= MAX_TEAM_I10:
            print(f"ERROR: {r['team']} i10 volume {r['i10_att']:.1f} outside "
                  f"{MIN_TEAM_I10}-{MAX_TEAM_I10}", file=sys.stderr)
            ok = False
        if not MIN_TEAM_I5 <= r["i5_att"] <= MAX_TEAM_I5:
            print(f"ERROR: {r['team']} i5 volume {r['i5_att']:.1f} outside "
                  f"{MIN_TEAM_I5}-{MAX_TEAM_I5}", file=sys.stderr)
            ok = False

    # A team's projected players must not out-carry the team. The roster cap
    # guarantees this, so anything over 100% here means the cap did not apply.
    # Undershoot is expected and fine: the slack belongs to rookies and anyone
    # else the sheet never listed.
    print("\nTeam reconciliation (player sum vs team projection, inside 10):")
    summed = defaultdict(float)
    for r in player_rows:
        summed[r["team"]] += r["i10_att"]
    coverage = []
    for team in sorted(team_proj):
        total = team_proj[team]["i10"]
        got = summed.get(team, 0.0)
        share = got / total if total else 0.0
        coverage.append((share, team, got, total))
        if share > 1.02:
            print(f"ERROR: {team} players sum to {got:.1f} of {total:.1f} "
                  f"({share:.0%}) -- share blend is over-allocating",
                  file=sys.stderr)
            ok = False
    coverage.sort()
    lo = ", ".join(f"{t} {s:.0%}" for s, t, _g, _v in coverage[:4])
    hi = ", ".join(f"{t} {s:.0%}" for s, t, _g, _v in coverage[-4:])
    med = statistics.median(s for s, _t, _g, _v in coverage)
    print(f"  median {med:.0%} | lowest: {lo} | highest: {hi}")

    return ok


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true",
                    help="read data/rz_input_2022_2025.csv instead of fetching")
    ap.add_argument("--k-i10", type=float, default=DEFAULT_K_I10,
                    help=f"inside-10 shrinkage strength (default {DEFAULT_K_I10})")
    ap.add_argument("--k-i5", type=float, default=DEFAULT_K_I5,
                    help=f"inside-5 shrinkage strength (default {DEFAULT_K_I5})")
    args = ap.parse_args()

    depth_cols = {"i10": (C_I10_ATT, C_I10_TD, C_I10_PCT),
                  "i5": (C_I5_ATT, C_I5_TD, C_I5_PCT)}
    ks = {"i10": args.k_i10, "i5": args.k_i5}
    caps = {"i10": MAX_TD_RATE_I10, "i5": MAX_TD_RATE_I5}

    header1, header2, data = fetch_sheet(args.offline)
    by_name, by_id = load_sleeper_players()

    volume, spreads = derive_team_volume(data)
    team_proj = project_team_volume(volume)

    players = build_player_history(data, by_name, by_id)
    print("\nShrinkage priors:")
    baselines = positional_baselines(players, depth_cols)

    # ---- players, pass 1: shares -------------------------------------------
    player_rows, dropped, capped = [], [], []
    for name, entry in sorted(players.items()):
        team = entry["sleeper"]["team"]
        if not team:
            dropped.append({
                "name": name,
                "position": entry["sleeper"]["position"],
                "last_season": max(r[C_SEASON] for r in entry["rows"]),
                "reason": "no 2026 NFL team in Sleeper",
            })
            continue
        if team not in team_proj:
            raise RuntimeError(f"{name} is on {team}, which has no sheet history")

        row = {"name": name, "team": team,
               "pfr_team": SLEEPER_TO_PFR.get(team, team),
               "position": entry["sleeper"]["position"]}
        for depth, (c_att, c_td, c_pct) in depth_cols.items():
            share, n_eff, raw = project_share(
                entry, depth, c_att, c_pct, volume, baselines, ks[depth])
            if share is None:
                # Only 2TM-only players land here: no season carrying a share.
                share, raw, n_eff = baselines[depth].get(row["position"], 0.0), None, 0.0
            row[f"{depth}_share"] = share
            row[f"{depth}_raw_share"] = raw
            row[f"{depth}_n_eff"] = n_eff
        player_rows.append(row)

    # ---- players, pass 2: cap each roster at 100% of its own carries -------
    team_scale = {}
    for depth in depth_cols:
        totals = defaultdict(float)
        for r in player_rows:
            totals[r["team"]] += r[f"{depth}_share"]
        for team, total in totals.items():
            scale = MAX_TEAM_SHARE / total if total > MAX_TEAM_SHARE else 1.0
            team_scale[(team, depth)] = scale
        for r in player_rows:
            r[f"{depth}_share"] *= team_scale[(r["team"], depth)]

    scaled = sorted(((s, t) for (t, d), s in team_scale.items()
                     if d == "i10" and s < 1.0))
    print(f"\nRoster cap: {len(scaled)} of {len(team_proj)} teams projected past "
          f"100% of their own inside-10 carries and were scaled back")
    if scaled:
        print("  hardest hit: " + ", ".join(f"{t} x{s:.2f}" for s, t in scaled[:6]))

    # ---- players, pass 3: attempts and TDs ---------------------------------
    for r in player_rows:
        entry = players[r["name"]]
        for depth, (c_att, c_td, _c_pct) in depth_cols.items():
            att = team_proj[r["team"]].get(depth, 0.0) * r[f"{depth}_share"]
            rate, was_capped = td_rate(entry, c_att, c_td, caps[depth])
            if was_capped:
                capped.append(f"{r['name']} ({depth})")
            r[f"{depth}_att"] = att
            r[f"{depth}_td"] = att * rate

    player_rows.sort(key=lambda r: -r["i10_att"])

    # ---- teams -------------------------------------------------------------
    # Team TD rate comes from the sheet's own listed players. Coverage of team
    # attempts is high (the sheet lists everyone with a carry), so the rate over
    # covered attempts stands in for the team's rate over all of them.
    td_num = defaultdict(lambda: defaultdict(float))
    td_den = defaultdict(lambda: defaultdict(float))
    for r in data:
        if r[C_TEAM] == MULTI_TEAM:
            continue
        team = PFR_TO_SLEEPER.get(r[C_TEAM], r[C_TEAM])
        w = DECAY[r[C_SEASON]]
        for depth, (c_att, c_td, _c_pct) in depth_cols.items():
            td_num[team][depth] += w * num(r[c_td])
            td_den[team][depth] += w * num(r[c_att])

    team_rows = []
    for team, depths in team_proj.items():
        row = {"team": team, "pfr_team": SLEEPER_TO_PFR.get(team, team)}
        for depth in depth_cols:
            att = depths.get(depth, 0.0)
            den = td_den[team][depth]
            rate = (td_num[team][depth] / den) if den else 0.0
            row[f"{depth}_att"] = att
            row[f"{depth}_td"] = att * min(rate, caps[depth])
        team_rows.append(row)
    team_rows.sort(key=lambda r: -r["i10_att"])

    # ---- report ------------------------------------------------------------
    print(f"\n{len(player_rows)} players projected, {len(dropped)} dropped")
    recent = [d for d in dropped if d["last_season"] == "2025"]
    if recent:
        print(f"  {len(recent)} played in 2025 but are unsigned -- re-run after "
              f"they sign and the Sleeper dump refreshes:")
        print("    " + ", ".join(sorted(d["name"] for d in recent)))
    print(f"  {len(dropped) - len(recent)} last played 2024 or earlier (retired)")
    if capped:
        print(f"  TD rate capped for {len(capped)}: {', '.join(sorted(capped)[:8])}"
              + (" ..." if len(capped) > 8 else ""))

    if not verify(player_rows, team_rows, team_proj):
        print("\nRefusing to write output.", file=sys.stderr)
        return 1

    # ---- write -------------------------------------------------------------
    data_dir = repo_path("data")
    os.makedirs(data_dir, exist_ok=True)
    p_path = os.path.join(data_dir, f"rz_projections_{TARGET_SEASON}.csv")
    t_path = os.path.join(data_dir, f"rz_projections_{TARGET_SEASON}_teams.csv")
    m_path = os.path.join(data_dir, f"rz_projections_{TARGET_SEASON}_meta.json")

    write_players(p_path, header1, header2, player_rows)
    write_teams(t_path, team_rows)

    meta = {
        "source": "Google Sheets (hand-maintained), gid " + SHEET_GID,
        "url": SHEET_URL,
        "snapshot": "data/rz_input_2022_2025.csv",
        "sleeper_players": "cache/sleeper_players.json",
        "target_season": TARGET_SEASON,
        "decay_weights": DECAY,
        "shrinkage_k": ks,
        "max_team_share": MAX_TEAM_SHARE,
        "roster_cap_scale": {f"{t}|{d}": round(s, 4)
                             for (t, d), s in sorted(team_scale.items()) if s < 1.0},
        "td_rate_caps": caps,
        "positional_baselines": baselines,
        "player_count": len(player_rows),
        "team_count": len(team_rows),
        "td_rate_capped": sorted(capped),
        "dropped_players": sorted(dropped, key=lambda d: (d["last_season"], d["name"]),
                                  reverse=True),
        "team_volume_implied_spread": spreads,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with open(m_path, "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\nWrote {len(player_rows)} players to {os.path.abspath(p_path)}")
    print(f"Wrote {len(team_rows)} teams to {os.path.abspath(t_path)}")
    print(f"Wrote metadata to {os.path.abspath(m_path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
