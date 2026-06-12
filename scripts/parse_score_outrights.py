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
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from outright_common import (  # noqa: E402
    CANON, blocked, host_of, team_key, norm_name, norm_american,
    load_outrights, save_outrights, upsert_market,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMPORT_PATH = os.path.join(ROOT, "data", "imports", "score.json")

SCORE_MARKETS = {
    "Regular Season MVP": "mvp",
    "Offensive Player Of The Year": "opoy",
    "Defensive Player Of The Year": "dpoy",
    "Super Bowl Winner": "super_bowl_winner",
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

    return {
        "captures": len(captures),
        "dropped": dropped,
        "kept_hosts": sorted(h for h in kept_hosts if h),
        "markets": {k: len(v) for k, v in markets.items()},
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
    if s["skipped"]:
        print("\nUnmapped SCORE LIST markets (not written):")
        for n in sorted(s["skipped"]):
            print("  - %s (%d)" % (n, s["skipped"][n]))
    print("\nWrote data/outrights.json")


if __name__ == "__main__":
    main()
