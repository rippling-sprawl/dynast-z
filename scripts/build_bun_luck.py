#!/usr/bin/env python3
"""
Fold 2025 luck — wins above Pythagorean expectation — into the Baker's Buns score.

Input  : data/nfl_projections_2026.json  (each team's `pythag` block, already there)
Output : the same file — each team gains
             raw.winsAbovePythag   last season's wins minus its expected wins   e.g. +1.9
             z.luck                that gap as an inverted z against the field  e.g. -1.3
         plus `stats.winsAbovePythag`, a `weights.luck` of 5%, and a `score`
         moved by the difference.

Why this input, and why here
----------------------------
The Luck column has sat beside the six scored ones since the table was built and
counted for nothing: a raw win total in a row of z-scores, read and then stepped
over. It is the only column on the page that says something about the *next*
season that the season it describes did not already say — a team that won three
more games than its points did is carrying a record it has to repeat rather than
a level it has established, and the league's history is that it does not.

The inversion
-------------
Positive wins-above-pythag is the thing that regresses, so it scores as a
negative the way the rank and tier columns do: the z is (mean - value) / sd, and
a team that won *fewer* games than its points implied comes out positive. That
is the whole claim being made — the bounce-back team is the buy, the
over-performer is the fade — and it is the reason this column could not simply
be dropped into the blend with its raw sign.

It is the lightest weight on the page, and lighter than the two 10% inputs, for
a reason they do not share: it is a single season of a single team's point
differential, the noisiest input here by construction, and half of what it
measures is a real thing (close-game coaching, a kicker) rather than variance.
5% says the model will not ignore a three-win gap, not that it knows which half
of one it is looking at.

The 5% comes off SoS, which drops to 15%. Both are circumstance rather than
roster, both are about the shape of a season rather than the quality of a team,
and of the two the schedule was the one carrying more weight than what it can
explain on its own.

The score
---------
The published `score` is *moved*, not rebuilt, for the same reason
build_bun_havoc.py and build_bun_coaches.py move it: the sheet computes from
full-precision z-scores while the JSON rounds each z to one decimal, so
recomputing the sum would land every team about 0.01 off its own published
figure. Each team's score takes

    delta = 0.05 x z_luck - 0.05 x z_sos

rounded to the two decimals the score is quoted in.

Re-running
----------
Safe, and order-independent with build_bun_havoc.py and build_bun_coaches.py —
each takes its share from a different pair and each reverses itself before
reapplying. The application is recorded in `luckInput`. Run it again whenever
the pythag block is re-exported.

Usage:
    python3 scripts/build_bun_luck.py
    python3 scripts/build_bun_luck.py --remove     # put the score back as it was
"""

import argparse
import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJ_PATH = os.path.join(ROOT, "data", "nfl_projections_2026.json")

LUCK_WEIGHT = 0.05

# Where the 5% comes from. SoS goes 20% -> 15%; see the note above for why it is
# the one that pays.
TAKEN_FROM = {"sos": 0.05}

EXPECTED_TEAMS = 32


def load(path):
    if not os.path.exists(path):
        raise SystemExit(f"missing {path}")
    with open(path) as f:
        return json.load(f)


def gaps_from(proj):
    """Each team's wins above its Pythagorean expectation, keyed by abbr."""
    out = {}
    for t in proj["teams"]:
        p = t.get("pythag")
        if not p or p.get("winsAbovePythag") is None:
            raise SystemExit(f"{t['abbr']} has no pythag block to score")
        out[t["abbr"]] = p["winsAbovePythag"]
    return out


def delta_for(t, weight, taken_from):
    """What one team's score moves by. Rounded here rather than after it is
    added, so that subtracting the same number later lands back on exactly the
    figure the sheet published."""
    z = t["z"]
    moved = weight * z["luck"]
    for key, share in taken_from.items():
        moved -= share * z[key]
    return round(moved, 2)


def unapply(proj):
    """Reverse a previous run, using the record it left rather than these
    constants: the file may have been built when the weight or the split was
    something else, and reversing with today's numbers would silently corrupt
    every score in it."""
    prev = proj.get("luckInput")
    if not prev:
        return False
    for t in proj["teams"]:
        if t["z"].get("luck") is None:
            continue
        t["score"] = round(t["score"] - delta_for(t, prev["weight"], prev["takenFrom"]), 2)
        t["z"].pop("luck", None)
        t["raw"].pop("winsAbovePythag", None)
    for key, share in prev["takenFrom"].items():
        proj["weights"][key] = round(proj["weights"][key] + share, 4)
    proj["weights"].pop("luck", None)
    proj.get("stats", {}).pop("winsAbovePythag", None)
    proj.pop("luckInput", None)
    return True


def apply(proj, gaps):
    teams = proj["teams"]

    vals = [gaps[t["abbr"]] for t in teams]
    avg = statistics.mean(vals)
    # Sample standard deviation, matching the sheet's other columns and the two
    # other build_bun_* scripts. See the note in build_bun_havoc.py for why the
    # denominator matters.
    std = statistics.stdev(vals)

    for t in teams:
        gap = gaps[t["abbr"]]
        t["raw"]["winsAbovePythag"] = gap
        # Inverted, like the rank and tier columns: winning more than your
        # points implied is the thing that regresses, so it has to score as a
        # negative and the team that got robbed has to score as a positive.
        t["z"]["luck"] = round((avg - gap) / std, 1)

    for t in teams:
        t["score"] = round(t["score"] + delta_for(t, LUCK_WEIGHT, TAKEN_FROM), 2)

    for key, share in TAKEN_FROM.items():
        proj["weights"][key] = round(proj["weights"][key] - share, 4)
    proj["weights"]["luck"] = LUCK_WEIGHT

    proj.setdefault("stats", {})["winsAbovePythag"] = {
        "avg": round(avg, 2), "std": round(std, 2)
    }
    proj["luckInput"] = {
        "season": 2025,
        "weight": LUCK_WEIGHT,
        "takenFrom": dict(TAKEN_FROM),
        "source": proj.get("pythagSource"),
        "note": ("2025 wins above Pythagorean expectation, z-scored against the "
                 "field and inverted: a team that won more than its points "
                 "implied is the one due to regress, so it scores as a "
                 "negative. It is the lightest input in the blend because it is "
                 "one season of one team's point differential. Its weight was "
                 "taken from SoS, which drops to 15%."),
    }
    return avg, std


def verify(proj):
    ok = True
    total = sum(proj["weights"].values())
    if abs(total - 1) > 1e-9:
        print(f"! weights sum to {total}, not 1", file=sys.stderr)
        ok = False
    if len(proj["teams"]) != EXPECTED_TEAMS:
        print(f"! {len(proj['teams'])} teams, expected {EXPECTED_TEAMS}", file=sys.stderr)
        ok = False
    for t in proj["teams"]:
        for key in proj["weights"]:
            if t["z"].get(key) is None:
                print(f"! {t['abbr']} has no z for {key}", file=sys.stderr)
                ok = False
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--remove", action="store_true",
                    help="reverse a previous run and write the file back without luck")
    args = ap.parse_args()

    proj = load(PROJ_PATH)
    was = unapply(proj)
    if was:
        print("Reversed the previous luck application")

    if args.remove:
        if not was:
            print("Nothing to remove.")
            return 0
    else:
        gaps = gaps_from(proj)
        print(f"Luck: 2025 wins above pythag from {os.path.basename(PROJ_PATH)}")
        avg, std = apply(proj, gaps)
        hot = max(gaps.items(), key=lambda kv: kv[1])
        cold = min(gaps.items(), key=lambda kv: kv[1])
        print(f"  {len(gaps)} teams, mean {avg:+.2f}, sd {std:.2f}")
        print(f"  luckiest {hot[0]} {hot[1]:+.1f}, unluckiest {cold[0]} {cold[1]:+.1f}")

    if not verify(proj):
        print("\nRefusing to overwrite good data.", file=sys.stderr)
        return 1

    order = ", ".join(f"{k} {round(v * 100)}%" for k, v in proj["weights"].items())
    print(f"  weights: {order}")

    # indent=2, matching the other build_bun_* scripts and the file on disk.
    with open(PROJ_PATH, "w") as f:
        json.dump(proj, f, indent=2)
    print(f"\nWrote {os.path.abspath(PROJ_PATH)} "
          f"({os.path.getsize(PROJ_PATH) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
