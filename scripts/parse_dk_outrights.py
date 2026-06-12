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
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from outright_common import (  # noqa: E402
    blocked, host_of, team_key, norm_name, norm_american,
    load_outrights, save_outrights, upsert_market, upsert_milestone,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMPORT_PATH = os.path.join(ROOT, "data", "imports", "dk.json")
MARKET_PATH = "leagueSubcategory/v1/markets"

# DK market name -> canonical key. Division/conference names carry the season
# label, so they're matched by regex below; the rest match exactly.
DK_EXACT = {
    "Winner": "super_bowl_winner",
    "To Make Playoffs": "make_playoffs",
    "Offensive Rookie of the Year": "oroy",
    "Defensive Rookie of the Year": "droy",
    "Most Regular Season Passing Yards": "most_passing_yards",
    "Most Regular Season Rushing Yards": "most_rushing_yards",
    "Most Regular Season Receiving Yards": "most_receiving_yards",
}
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
    n = name.strip()
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


def main():
    if not os.path.exists(IMPORT_PATH):
        sys.exit("No bundle at %s" % IMPORT_PATH)
    import json
    bundle = json.load(open(IMPORT_PATH))
    captures = bundle.get("captures", [])
    doc = load_outrights()

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
            from outright_common import CANON
            kind = CANON[key][1]
            bucket = markets.setdefault(key, {})
            for s in sels:
                cand = candidate(s, kind)
                if cand and cand[0]:
                    bucket[cand[0]] = (cand[1], cand[2])

    # Merge into the shared file (DK column only).
    for key, bucket in markets.items():
        cands = [(k, disp, am) for k, (disp, am) in bucket.items()]
        upsert_market(doc, key, "dk", cands)
    for (stat, threshold, title), bucket in milestones.items():
        cands = [(k, disp, am) for k, (disp, am) in bucket.items()]
        upsert_milestone(doc, stat, title, threshold, "dk", cands)

    save_outrights(doc)

    print("DK outrights — parsed %d captures (dropped %d blocked)" %
          (len(captures), dropped))
    print("Source hosts:", ", ".join(sorted(h for h in kept_hosts if h)) or "-")
    print("\nCanonical markets written (DK column):")
    for key in sorted(markets):
        print("  %-24s %3d candidates" % (key, len(markets[key])))
    print("\nMilestone thresholds written (DK column):")
    for (stat, threshold, _t) in sorted(milestones):
        print("  %-18s %5d+  %3d players" %
              (stat, threshold, len(milestones[(stat, threshold, _t)])))
    if skipped:
        print("\nUnmapped DK outright markets (not written):")
        for n in sorted(skipped):
            print("  - %s (%d)" % (n, skipped[n]))
    print("\nWrote data/outrights.json")


if __name__ == "__main__":
    main()
