#!/usr/bin/env python3
"""
Fold a coaching-staff input into the Baker's Buns score.

Input  : data/nfl_coaches_2026.json  (Action Network's staff tier per team)
Output : data/nfl_projections_2026.json — each team gains
             raw.coachTier   the tier it was placed in, 1 is best   e.g. 2
             z.coaches       that tier as a z against the field      e.g. +1.1
         plus `stats.coachTier`, a `weights.coaches` of 10%, and a `score` moved
         by the difference.

Why this input, and why here
----------------------------
Five of the things the score already carries are about players and the calendar:
the line, the schedule, the rest edge, the eye test, the pass rush. None of them
is about the people deciding what those players run. In a year when ten teams
changed head coach and 25 changed at least one coordinator, a model with nothing
in it about the staff is a model that projects last year's playbook onto this
year's sideline.

The tier rather than the rank
-----------------------------
Action Network publishes both a 1..32 order and the eight tiers that order is
grouped into, and it is the tier that goes in. The gap between the 13th and 14th
staff is a writer breaking a tie inside one bucket; the gap between tier 4 and
tier 5 is the claim the article is actually making. Scoring the rank would treat
both gaps as the same size and hand a team a tenth of a z-score for a placement
its own author would not defend. Eight buckets is the resolution the source has.

The tiers are unequal on purpose — two teams in tier 1, eight in tier 7 — and
z-scoring them keeps that: a tier-1 staff is rare and scores like it.

It is a small weight. This is one outlet's opinion, not a measurement, and
coaching quality is the input with the least settled evidence behind it of
anything in the blend. 10% says "the model now has a view here", not "the model
knows".

The 5% each comes off O-Line and Rest. The line is the heaviest input and stays
the heaviest after this; the rest edge is a schedule quirk worth less than the
staff running the team through it, and the two of them are the two the sheet
weighted most generously against what they can actually explain.

The score
---------
The published `score` is *moved*, not rebuilt, for the same reason
build_bun_havoc.py moves it: the sheet computes from full-precision z-scores
while the JSON rounds each z to one decimal, so recomputing the sum would land
every team about 0.01 off its own published figure. Each team's score takes

    delta = 0.10 x z_coaches - 0.05 x z_oLine - 0.05 x z_rest

rounded to the two decimals the score is quoted in.

Re-running
----------
Safe, and order-independent with build_bun_havoc.py — the two take their 5%
shares from different pairs and each reverses itself before reapplying. The
application is recorded in `coachInput`. Run it again whenever the tiers are
re-published.

Usage:
    python3 scripts/build_bun_coaches.py
    python3 scripts/build_bun_coaches.py --remove     # put the score back as it was
"""

import argparse
import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COACH_PATH = os.path.join(ROOT, "data", "nfl_coaches_2026.json")
PROJ_PATH = os.path.join(ROOT, "data", "nfl_projections_2026.json")

COACH_WEIGHT = 0.10

# Where the 10% comes from. The line is still the heaviest input after this.
TAKEN_FROM = {"oLine": 0.05, "rest": 0.05}

EXPECTED_TEAMS = 32


def load(path):
    if not os.path.exists(path):
        raise SystemExit(f"missing {path}")
    with open(path) as f:
        return json.load(f)


def tiers_from(coach):
    """Each team's staff tier, keyed by this site's abbreviation."""
    out = {}
    for abbr, staff in (coach.get("teams") or {}).items():
        tier = staff.get("tier")
        if tier is None:
            raise SystemExit(f"{abbr} has no coaching tier")
        out[abbr] = tier
    return out


def delta_for(t, weight, taken_from):
    """What one team's score moves by. Rounded here rather than after it is
    added, so that subtracting the same number later lands back on exactly the
    figure the sheet published."""
    z = t["z"]
    moved = weight * z["coaches"]
    for key, share in taken_from.items():
        moved -= share * z[key]
    return round(moved, 2)


def unapply(proj):
    """Reverse a previous run, using the record it left rather than these
    constants: the file may have been built when the weight or the split was
    something else, and reversing with today's numbers would silently corrupt
    every score in it."""
    prev = proj.get("coachInput")
    if not prev:
        return False
    for t in proj["teams"]:
        if t["z"].get("coaches") is None:
            continue
        t["score"] = round(t["score"] - delta_for(t, prev["weight"], prev["takenFrom"]), 2)
        t["z"].pop("coaches", None)
        t["raw"].pop("coachTier", None)
    for key, share in prev["takenFrom"].items():
        proj["weights"][key] = round(proj["weights"][key] + share, 4)
    proj["weights"].pop("coaches", None)
    proj.get("stats", {}).pop("coachTier", None)
    proj.pop("coachInput", None)
    return True


def apply(proj, coach, tiers):
    teams = proj["teams"]
    missing = sorted(t["abbr"] for t in teams if t["abbr"] not in tiers)
    if missing:
        raise SystemExit(f"no coaching tier for {', '.join(missing)}")

    vals = [tiers[t["abbr"]] for t in teams]
    avg = statistics.mean(vals)
    # Sample standard deviation, matching the sheet's other columns and
    # build_bun_havoc.py. See the note there for why the denominator matters.
    std = statistics.stdev(vals)

    for t in teams:
        tier = tiers[t["abbr"]]
        t["raw"]["coachTier"] = tier
        # Inverted, like the two rank columns: tier 1 is the best staff in the
        # league, so a low number has to score as a positive z.
        t["z"]["coaches"] = round((avg - tier) / std, 1)

    for t in teams:
        t["score"] = round(t["score"] + delta_for(t, COACH_WEIGHT, TAKEN_FROM), 2)

    for key, share in TAKEN_FROM.items():
        proj["weights"][key] = round(proj["weights"][key] - share, 4)
    proj["weights"]["coaches"] = COACH_WEIGHT

    proj.setdefault("stats", {})["coachTier"] = {"avg": round(avg, 2), "std": round(std, 2)}
    proj["coachInput"] = {
        "tiers": len(coach.get("tiers") or []),
        "weight": COACH_WEIGHT,
        "takenFrom": dict(TAKEN_FROM),
        "source": coach.get("tierSource"),
        "file": os.path.relpath(COACH_PATH, ROOT),
        "note": ("Action Network's 2026 coaching-staff tier, z-scored against "
                 "the field. Tier 1 is the best staff, so the z is inverted. "
                 "The tier is scored rather than the 1-32 rank because the tier "
                 "is the grouping the source stands behind. Its weight was "
                 "taken from O-Line and Rest, 5 points each."),
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
                    help="reverse a previous run and write the file back without coaches")
    args = ap.parse_args()

    proj = load(PROJ_PATH)
    was = unapply(proj)
    if was:
        print("Reversed the previous coaching application")

    if args.remove:
        if not was:
            print("Nothing to remove.")
            return 0
    else:
        coach = load(COACH_PATH)
        tiers = tiers_from(coach)
        print(f"Coaches: staff tier from {os.path.basename(COACH_PATH)}")
        avg, std = apply(proj, coach, tiers)
        print(f"  {len(tiers)} teams, mean tier {avg:.2f}, sd {std:.2f}")

    if not verify(proj):
        print("\nRefusing to overwrite good data.", file=sys.stderr)
        return 1

    order = ", ".join(f"{k} {round(v * 100)}%" for k, v in proj["weights"].items())
    print(f"  weights: {order}")

    # indent=2, matching build_bun_havoc.py and the file already on disk.
    with open(PROJ_PATH, "w") as f:
        json.dump(proj, f, indent=2)
    print(f"\nWrote {os.path.abspath(PROJ_PATH)} "
          f"({os.path.getsize(PROJ_PATH) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
