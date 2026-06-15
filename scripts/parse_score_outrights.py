#!/usr/bin/env python3
"""
Parse a theScore Recorder bundle's OUTRIGHT (LIST) markets into data/outrights.json.

Input  : data/imports/score.json
Output : data/outrights.json  (merged; SCORE column only — never clobbers DK/FD)

theScore serves GraphQL bodies; walk body.data for any dict with a selections
list (mirrors iter_markets in parse_score_import.py). An outright market has
type == "LIST" (vs "TOTAL" for Over/Under). Selection: name.cleanName is the
candidate, odds.formattedOdds the price ("Even" -> +100), participant.abbreviation
the team code we use to merge teams across books.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from outright_common import (  # noqa: E402
    CANON, FULL_NAME, blocked, host_of, team_key, norm_name, norm_american,
    load_outrights, save_outrights, upsert_market, upsert_milestone,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMPORT_PATH = os.path.join(ROOT, "data", "imports", "score.json")

# "<Team> Regular Season Milestone Wins" — a per-team win-total ladder (1+ .. 16+),
# the team analog of DK's "Player to Have X+ ..." milestones. Folded into the
# shared milestones tree under the "wins" stat (threshold -> teams), so they show
# in the Milestones view and the wins card's per-team ladder.
MILESTONE_WINS_RE = re.compile(r"\bRegular Season Milestone Wins$")
MILESTONE_WINS_TITLE = "Regular Season Wins Milestones"

SCORE_MARKETS = {
    "Regular Season MVP": "mvp",
    "Offensive Player Of The Year": "opoy",
    "Defensive Player Of The Year": "dpoy",
    "Offensive Rookie Of The Year": "oroy",
    "Defensive Rookie Of The Year": "droy",
    "Coach Of The Year": "coy",
    "Comeback Player Of The Year": "cpoy",
    "Super Bowl Winner": "super_bowl_winner",
    "AFC Conference Winner": "afc_winner",
    "NFC Conference Winner": "nfc_winner",
    "AFC East Winner": "afc_east_winner",
    "AFC North Winner": "afc_north_winner",
    "AFC South Winner": "afc_south_winner",
    "AFC West Winner": "afc_west_winner",
    "NFC East Winner": "nfc_east_winner",
    "NFC North Winner": "nfc_north_winner",
    "NFC South Winner": "nfc_south_winner",
    "NFC West Winner": "nfc_west_winner",
    "Most Regular Season Wins": "most_wins",
}


def iter_markets(obj):
    if isinstance(obj, dict):
        if isinstance(obj.get("selections"), list):
            yield obj
        for v in obj.values():
            yield from iter_markets(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from iter_markets(v)


def candidate(sel, kind):
    name = ((sel.get("name") or {}).get("cleanName") or "").strip()
    american = norm_american((sel.get("odds") or {}).get("formattedOdds"))
    if not name or american is None:
        return None
    if kind == "team":
        abbr = (sel.get("participant") or {}).get("abbreviation")
        return (team_key(name, abbr), name, american)
    return (norm_name(name), name, american)


def apply_score_outrights(doc, captures):
    """Upsert theScore's outright (LIST) award/futures columns from a bundle's
    captures into the shared outrights `doc`. Mutates doc and returns a summary
    (with the unmapped LIST market names). Pure: no file I/O — the SCORE column
    never clobbers FD/DK."""
    kept_hosts, dropped = set(), 0
    markets = {}        # canon key -> {cand_key: (disp, american)}
    win_ms = {}         # threshold -> {abbr: (full_name, american)}
    skipped = {}

    for c in captures:
        url = c.get("url", "")
        if blocked(url):
            dropped += 1
            continue
        body = c.get("body")
        if not isinstance(body, dict):
            continue
        kept_hosts.add(host_of(url))
        for m in iter_markets(body.get("data")):
            if m.get("type") != "LIST":
                continue
            name = (m.get("name") or "").strip()

            # Per-team win-total ladder -> milestones["wins"][threshold] = teams.
            if MILESTONE_WINS_RE.search(name):
                abbr = team_key(name)
                if not abbr:
                    continue
                disp = FULL_NAME.get(abbr, name)
                for s in m.get("selections", []):
                    thn = ((s.get("name") or {}).get("cleanName") or "").strip()
                    mth = re.match(r"(\d+)\+?$", thn)
                    american = norm_american((s.get("odds") or {}).get("formattedOdds"))
                    if not mth or american is None:
                        continue
                    win_ms.setdefault(int(mth.group(1)), {})[abbr] = (disp, american)
                continue

            key = SCORE_MARKETS.get(name)
            if key is None:
                if name:
                    skipped[name] = len(m.get("selections", []))
                continue
            kind = CANON[key][1]
            bucket = markets.setdefault(key, {})
            for s in m.get("selections", []):
                cand = candidate(s, kind)
                if cand and cand[0]:
                    bucket[cand[0]] = (cand[1], cand[2])

    for key, bucket in markets.items():
        cands = [(k, disp, am) for k, (disp, am) in bucket.items()]
        upsert_market(doc, key, "score", cands)
    for threshold, bucket in win_ms.items():
        cands = [(k, disp, am) for k, (disp, am) in bucket.items()]
        upsert_milestone(doc, "wins", MILESTONE_WINS_TITLE, threshold, "score", cands)

    return {
        "captures": len(captures),
        "dropped": dropped,
        "kept_hosts": sorted(h for h in kept_hosts if h),
        "markets": {k: len(v) for k, v in markets.items()},
        "win_milestones": {th: len(b) for th, b in win_ms.items()},
        "skipped": skipped,
    }


def main():
    if not os.path.exists(IMPORT_PATH):
        sys.exit("No bundle at %s" % IMPORT_PATH)
    bundle = json.load(open(IMPORT_PATH))
    captures = bundle.get("captures", [])
    doc = load_outrights()
    s = apply_score_outrights(doc, captures)
    save_outrights(doc)

    print("SCORE outrights — parsed %d captures (dropped %d blocked)" %
          (s["captures"], s["dropped"]))
    print("Source hosts:", ", ".join(s["kept_hosts"]) or "-")
    print("\nCanonical markets written (SCORE column):")
    for key in sorted(s["markets"]):
        print("  %-24s %3d candidates" % (key, s["markets"][key]))
    if s["win_milestones"]:
        print("\nWins milestone thresholds written (SCORE column):")
        for th in sorted(s["win_milestones"]):
            print("  %2d+  %3d teams" % (th, s["win_milestones"][th]))
    if s["skipped"]:
        print("\nUnmapped SCORE LIST markets (not written):")
        for n in sorted(s["skipped"]):
            print("  - %s (%d)" % (n, s["skipped"][n]))
    print("\nWrote data/outrights.json")


if __name__ == "__main__":
    main()
