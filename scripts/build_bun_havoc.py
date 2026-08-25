#!/usr/bin/env python3
"""
Fold a defensive-pressure input into the Baker's Buns score.

Input  : data/nfl_regression_2026.json  (havoc rate per team per season)
Output : data/nfl_projections_2026.json — each team gains
             raw.havoc   the two-season blended pressure rate   e.g. 15.4
             z.havoc     that rate as a z against the field      e.g. +0.6
         plus `stats.havoc`, a `weights.havoc` of 15%, and a `score` moved by
         the difference.

Why this input, and why here
----------------------------
The four things the sheet already scores — the offensive line, the schedule,
the rest edge and the eye test — describe an offense and its circumstances.
None of them is about a defense. Pressure rate is the cheapest honest fix for
that: it is the stickiest thing a defense does, which is exactly the property an
input to a *projection* has to have. A number that does not repeat is a number
that cannot forecast, whatever it says about last year.

It is deliberately a modest weight. This is a floor on pressure rather than the
real thing — hurries are hand-charted and in no free feed — and one defensive
number is not a defense. 15% says "the model was blind here and is now looking",
which is the honest size of the claim: enough to move a team a place or two,
never enough to carry one on its own.

The blend
---------
    havoc% = 0.75 x last season + 0.25 x the season before

Two seasons, weighted toward the recent one, because pressure is sticky but a
roster is not: a team that added an edge rusher in March should not be scored on
what its 2024 front did, and a team whose 2025 rate came off one healthy year
should not be scored as though that is settled. One season alone would take
every injury and every soft schedule at face value; an even split would argue
that a two-year-old front tells you as much as the current one, which is a
stronger claim than the numbers support.

The 10 points off O-Line and 5 off SoS are on purpose. The line is still the
heaviest input at 25%, and taking it mostly out of the line rather than
out of the eye test or the rest edge keeps the smallest weights where they are:
an input already down at 10% cannot lend 5% without becoming a rounding error.
The line's own rank is also the most consensus-driven number on the page — six
boards agreeing is worth something, but not 40% of a projection.

The score
---------
The published `score` is *moved*, not rebuilt. The sheet computes it from
full-precision z-scores while the JSON rounds each z to one decimal, so
recomputing the whole sum here would land every team about 0.01 off its own
published figure for no reason. Instead each team's score takes

    delta = 0.15 x z_havoc - 0.10 x z_oLine - 0.05 x z_sos

rounded to the two decimals the score is quoted in, which leaves the four
original terms at exactly the precision the sheet computed them with.

Re-running
----------
Safe. The application is recorded in `havocInput`, and a second run reverses the
first exactly before applying itself — the deltas are rounded before they are
added, so nothing drifts across a cycle. Run it again whenever
fetch_nfl_regression.py refreshes the seasons underneath it.

Usage:
    python3 scripts/build_bun_havoc.py
    python3 scripts/build_bun_havoc.py --remove     # put the score back as it was
"""

import argparse
import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG_PATH = os.path.join(ROOT, "data", "nfl_regression_2026.json")
PROJ_PATH = os.path.join(ROOT, "data", "nfl_projections_2026.json")

# Newest season first. The pair has to stay ordered, because it is written into
# the file as the record of what was blended.
BLEND = [0.75, 0.25]

HAVOC_WEIGHT = 0.15

# Where the 15% comes from. The line is still the heaviest input after this,
# at 25%.
TAKEN_FROM = {"oLine": 0.10, "sos": 0.05}

EXPECTED_TEAMS = 32


def load(path):
    if not os.path.exists(path):
        raise SystemExit(f"missing {path}")
    with open(path) as f:
        return json.load(f)


def blended_rates(reg):
    """Each team's two-season pressure rate, keyed by this site's abbreviation.

    Read off the regression file's `history` rather than its `teams` block,
    because only the history carries a season before the current one — and
    reading both seasons from one place is what keeps the blend from silently
    becoming a single season if the history is ever shortened."""
    seasons = reg.get("historySeasons") or []
    if len(seasons) < len(BLEND):
        raise SystemExit(f"regression file has {len(seasons)} seasons, "
                         f"needs {len(BLEND)} for the blend")
    want = list(reversed(seasons[-len(BLEND):]))     # newest first, to match BLEND

    out = {}
    for abbr, rows in (reg.get("history") or {}).items():
        by_season = {r["season"]: r["havoc"] for r in rows}
        missing = [s for s in want if s not in by_season]
        if missing:
            raise SystemExit(f"{abbr} has no havoc rate for {missing}")
        out[abbr] = sum(w * by_season[s] for w, s in zip(BLEND, want))
    return want, out


def delta_for(t, weight, taken_from):
    """What one team's score moves by. Rounded here rather than after it is
    added, so that subtracting the same number later lands back on exactly the
    figure the sheet published."""
    z = t["z"]
    moved = weight * z["havoc"]
    for key, share in taken_from.items():
        moved -= share * z[key]
    return round(moved, 2)


def unapply(proj):
    """Reverse a previous run, using the record it left rather than these
    constants: the file may have been built when the weight or the split was
    something else, and reversing with today's numbers would silently corrupt
    every score in it."""
    prev = proj.get("havocInput")
    if not prev:
        return False
    for t in proj["teams"]:
        if t["z"].get("havoc") is None:
            continue
        t["score"] = round(t["score"] - delta_for(t, prev["weight"], prev["takenFrom"]), 2)
        t["z"].pop("havoc", None)
        t["raw"].pop("havoc", None)
    for key, share in prev["takenFrom"].items():
        proj["weights"][key] = round(proj["weights"][key] + share, 4)
    proj["weights"].pop("havoc", None)
    proj.get("stats", {}).pop("havoc", None)
    proj.pop("havocInput", None)
    return True


def apply(proj, seasons, rates):
    teams = proj["teams"]
    missing = sorted(t["abbr"] for t in teams if t["abbr"] not in rates)
    if missing:
        raise SystemExit(f"no havoc rate for {', '.join(missing)}")

    vals = [rates[t["abbr"]] for t in teams]
    avg = statistics.mean(vals)
    # Sample standard deviation, which is what the sheet's other four columns
    # use — its O-Line std of 9.38 is stdev(1..32), not pstdev's 9.23. A z-score
    # that used a different denominator from the columns beside it would not be
    # comparable with them, which is the entire point of a z-score.
    std = statistics.stdev(vals)

    for t in teams:
        rate = rates[t["abbr"]]
        t["raw"]["havoc"] = round(rate, 1)
        # Higher is better and needs no inverting, unlike the two rank columns:
        # a defense that gets hands on the quarterback more often is the better
        # defense, and the number already runs that way.
        t["z"]["havoc"] = round((rate - avg) / std, 1)

    for t in teams:
        t["score"] = round(t["score"] + delta_for(t, HAVOC_WEIGHT, TAKEN_FROM), 2)

    for key, share in TAKEN_FROM.items():
        proj["weights"][key] = round(proj["weights"][key] - share, 4)
    proj["weights"]["havoc"] = HAVOC_WEIGHT

    proj.setdefault("stats", {})["havoc"] = {"avg": round(avg, 2), "std": round(std, 2)}
    proj["havocInput"] = {
        "seasons": seasons,
        "blend": BLEND,
        "weight": HAVOC_WEIGHT,
        "takenFrom": dict(TAKEN_FROM),
        "source": os.path.relpath(REG_PATH, ROOT),
        "note": (f"Pressure rate blended {int(BLEND[0] * 100)}% {seasons[0]} / "
                 f"{int(BLEND[1] * 100)}% {seasons[1]}, z-scored against the field. "
                 "Rank 1 is the highest rate. Its weight was taken "
                 + " and ".join(f"{round(share * 100)} points from {key}"
                                for key, share in TAKEN_FROM.items()) + "."),
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
                    help="reverse a previous run and write the file back without havoc")
    args = ap.parse_args()

    proj = load(PROJ_PATH)
    was = unapply(proj)
    if was:
        print("Reversed the previous havoc application")

    if args.remove:
        if not was:
            print("Nothing to remove.")
            return 0
    else:
        reg = load(REG_PATH)
        seasons, rates = blended_rates(reg)
        print(f"Havoc: {int(BLEND[0] * 100)}% {seasons[0]} / "
              f"{int(BLEND[1] * 100)}% {seasons[1]}, from {os.path.basename(REG_PATH)}")
        avg, std = apply(proj, seasons, rates)
        print(f"  {len(rates)} teams, mean {avg:.2f}%, sd {std:.2f}")

    if not verify(proj):
        print("\nRefusing to overwrite good data.", file=sys.stderr)
        return 1

    order = ", ".join(f"{k} {round(v * 100)}%" for k, v in proj["weights"].items())
    print(f"  weights: {order}")

    # indent=2, matching build_bun_win_totals.py and the file already on disk.
    # This one is hand-maintained between builds, so a script that minified it
    # would make the next diff against it unreadable — the opposite of the
    # regression file, which is generated whole and never edited by hand.
    with open(PROJ_PATH, "w") as f:
        json.dump(proj, f, indent=2)
    print(f"\nWrote {os.path.abspath(PROJ_PATH)} "
          f"({os.path.getsize(PROJ_PATH) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
