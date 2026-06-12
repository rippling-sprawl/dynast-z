#!/usr/bin/env python3
"""
Parse a DraftKings Recorder bundle's OUTRIGHT markets into data/outrights.json.

Input  : data/imports/dk.json
Output : data/outrights.json  (merged; DK column only — never clobbers FD/SCORE)

The DK player-prop parser (parse_dk_import.py) keeps only Over/Under markets and
reports the rest. This is the other half: the outright / award / division-winner
/ statistical-leader markets (selections with no Over/Under outcome), plus the
"Player to Have X+ ..." milestone lists (over-only player markets that also feed
the Player Props view).

Native DK shape: parallel markets[] + selections[] linked by selection.marketId.
A selection's candidate is `label`; the price is `displayOdds.american` (unicode
minus); teams carry participants[].type == "Team" but players are tagged "Team"
too in this feed, so we classify by the canonical market, not the participant.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from outright_common import (  # noqa: E402
    CANON, blocked, host_of, team_key, norm_name, norm_american,
    load_outrights, save_outrights, upsert_market, upsert_milestone,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMPORT_PATH = os.path.join(ROOT, "data", "imports", "dk.json")
MARKET_PATH = "leagueSubcategory/v1/markets"

# DK market name -> canonical key. DK names are inconsistent across pages: some
# carry a leading "NFL 2026/27 - " prefix and/or a trailing season, and divisions
# /conferences vary further, so canon_key() strips the season label off both ends
# before matching here. The rest match exactly.
DK_EXACT = {
    "Winner": "super_bowl_winner",
    "Super Bowl Winner": "super_bowl_winner",
    "To Make Playoffs": "make_playoffs",
    "To Miss Playoffs": "miss_playoffs",
    "Regular Season MVP": "mvp",
    "Offensive Player of the Year": "opoy",
    "Defensive Player of the Year": "dpoy",
    "Offensive Rookie of the Year": "oroy",
    "Defensive Rookie of the Year": "droy",
    "Coach of the Year": "coy",
    "Comeback Player of the Year": "cpoy",
    "Most Regular Season Wins": "most_wins",
    "Most Regular Season Passing Yards": "most_passing_yards",
    "Most Regular Season Rushing Yards": "most_rushing_yards",
    "Most Regular Season Receiving Yards": "most_receiving_yards",
    "AFC 1 Seed": "afc_1_seed",
    "NFC 1 Seed": "nfc_1_seed",
}

# Leading "NFL 2026/27 - " prefix DK puts on many futures markets.
SEASON_PREFIX_RE = re.compile(r"^NFL\s+20\d\d/\d\d\s*-\s*", re.I)
# Trailing " 2026/27" / " 2026-27" season label.
SEASON_SUFFIX_RE = re.compile(r"\s+20\d\d[-/]\d\d(\d\d)?$")
DK_DIVISIONS = {
    "afc east": "afc_east_winner", "afc north": "afc_north_winner",
    "afc south": "afc_south_winner", "afc west": "afc_west_winner",
    "nfc east": "nfc_east_winner", "nfc north": "nfc_north_winner",
    "nfc south": "nfc_south_winner", "nfc west": "nfc_west_winner",
}

# "Player to Have 1500+ Regular Season Rushing Yards" -> (stat, threshold)
MILESTONE_RE = re.compile(
    r"Player to Have\s+(\d+)\+\s+Regular Season\s+(Passing|Rushing|Receiving)\s+(Yards|TDs)",
    re.I)
MILESTONE_STAT = {
    ("passing", "yards"): ("passing_yards", "Passing Yards Milestones"),
    ("passing", "tds"):   ("passing_tds",   "Passing TD Milestones"),
    ("rushing", "yards"): ("rushing_yards", "Rushing Yards Milestones"),
    ("receiving", "yards"): ("receiving_yards", "Receiving Yards Milestones"),
}


def canon_key(name):
    """Map a DK outright market name to a canonical key, or None."""
    n = SEASON_PREFIX_RE.sub("", name.strip())
    n = SEASON_SUFFIX_RE.sub("", n).strip()
    if n in DK_EXACT:
        return DK_EXACT[n]
    low = n.lower()
    if re.search(r"\bafc winner\b", low):
        return "afc_winner"
    if re.search(r"\bnfc winner\b", low):
        return "nfc_winner"
    for frag, key in DK_DIVISIONS.items():
        if frag + " winner" in low:
            return key
    return None


def candidate(sel, kind):
    """(cand_key, display_name, american) for one DK selection."""
    label = (sel.get("label") or "").strip()
    american = norm_american((sel.get("displayOdds") or {}).get("american"))
    if not label or american is None:
        return None
    if kind == "team":
        return (team_key(label), label, american)
    return (norm_name(label), label, american)


def apply_dk_outrights(doc, captures):
    """Upsert DraftKings' outright/award/leader columns and milestone lists from
    a bundle's captures into the shared outrights `doc`. Mutates doc and returns a
    summary (with the unmapped market names). Pure: no file I/O — the DK column
    never clobbers FD/SCORE."""
    kept_hosts, dropped = set(), 0
    # canonical key -> {cand_key: (disp, american)} de-duped across captures
    markets = {}                 # canon key -> dict
    milestones = {}              # (stat, threshold, title) -> dict
    skipped = {}                 # unmapped outright market name -> sel count

    for c in captures:
        url = c.get("url", "")
        if blocked(url):
            dropped += 1
            continue
        if MARKET_PATH not in url:
            continue
        body = c.get("body")
        if not isinstance(body, dict):
            continue
        kept_hosts.add(host_of(url))

        sels_by_mid = {}
        for s in body.get("selections", []):
            sels_by_mid.setdefault(s.get("marketId"), []).append(s)

        for m in body.get("markets", []):
            name = (m.get("name") or "").strip()
            if not name:
                continue
            sels = sels_by_mid.get(m.get("id"), [])
            # Over/Under markets are the player-prop parser's job — skip here.
            if any(s.get("outcomeType") in ("Over", "Under") for s in sels):
                continue

            ms = MILESTONE_RE.search(name)
            if ms:
                threshold = int(ms.group(1))
                statkey = (ms.group(2).lower(), ms.group(3).lower())
                if statkey not in MILESTONE_STAT:
                    continue
                stat, title = MILESTONE_STAT[statkey]
                bucket = milestones.setdefault((stat, threshold, title), {})
                for s in sels:
                    cand = candidate(s, "player")
                    if cand and cand[0]:
                        bucket[cand[0]] = (cand[1], cand[2])
                continue

            key = canon_key(name)
            if key is None:
                skipped[name] = len(sels)
                continue
            kind = CANON[key][1]
            bucket = markets.setdefault(key, {})
            for s in sels:
                cand = candidate(s, kind)
                if cand and cand[0]:
                    bucket[cand[0]] = (cand[1], cand[2])

    # Merge into the shared doc (DK column only).
    for key, bucket in markets.items():
        cands = [(k, disp, am) for k, (disp, am) in bucket.items()]
        upsert_market(doc, key, "dk", cands)
    for (stat, threshold, title), bucket in milestones.items():
        cands = [(k, disp, am) for k, (disp, am) in bucket.items()]
        upsert_milestone(doc, stat, title, threshold, "dk", cands)

    return {
        "captures": len(captures),
        "dropped": dropped,
        "kept_hosts": sorted(h for h in kept_hosts if h),
        "markets": {k: len(v) for k, v in markets.items()},
        "milestones": {(stat, threshold): len(b)
                       for (stat, threshold, _t), b in milestones.items()},
        "skipped": skipped,
    }


def main():
    if not os.path.exists(IMPORT_PATH):
        sys.exit("No bundle at %s" % IMPORT_PATH)
    bundle = json.load(open(IMPORT_PATH))
    captures = bundle.get("captures", [])
    doc = load_outrights()
    s = apply_dk_outrights(doc, captures)
    save_outrights(doc)

    print("DK outrights — parsed %d captures (dropped %d blocked)" %
          (s["captures"], s["dropped"]))
    print("Source hosts:", ", ".join(s["kept_hosts"]) or "-")
    print("\nCanonical markets written (DK column):")
    for key in sorted(s["markets"]):
        print("  %-24s %3d candidates" % (key, s["markets"][key]))
    print("\nMilestone thresholds written (DK column):")
    for (stat, threshold) in sorted(s["milestones"]):
        print("  %-18s %5d+  %3d players" %
              (stat, threshold, s["milestones"][(stat, threshold)]))
    if s["skipped"]:
        print("\nUnmapped DK outright markets (not written):")
        for n in sorted(s["skipped"]):
            print("  - %s (%d)" % (n, s["skipped"][n]))
    print("\nWrote data/outrights.json")


if __name__ == "__main__":
    main()
