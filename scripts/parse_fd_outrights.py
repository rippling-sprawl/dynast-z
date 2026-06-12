#!/usr/bin/env python3
"""
Parse FanDuel's OUTRIGHT (field) markets into data/outrights.json.

Input  : data/fd.json   (the parsed FanDuel layout+attachments consumer file —
                          already tick-refreshed by parse_fd_import.py, so its
                          prices match what the Player Props view shows)
Output : data/outrights.json  (merged; FD column only — never clobbers DK/SCORE)

FanDuel's awards/futures are "field" markets: a coupon whose market lists one
runner per entity (team or player) instead of Over/Under runners. We read
layout.coupons -> marketId -> attachments.markets[id].runners; each runner has
runnerName (the candidate) and winRunnerOdds.americanDisplayOdds.americanOdds.

(The player-prop and per-team-wins coupons whose runners are "... Over/Under N"
don't match any canonical award key, so they're skipped automatically.)
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from outright_common import (  # noqa: E402
    CANON, team_key, norm_name, norm_american,
    load_outrights, save_outrights, upsert_market,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FD_PATH = os.path.join(ROOT, "data", "fd.json")

DIVISIONS = {
    "afc east": "afc_east_winner", "afc north": "afc_north_winner",
    "afc south": "afc_south_winner", "afc west": "afc_west_winner",
    "nfc east": "nfc_east_winner", "nfc north": "nfc_north_winner",
    "nfc south": "nfc_south_winner", "nfc west": "nfc_west_winner",
}


def fd_canon(title):
    """Map an FD coupon title to a canonical key, or None to skip."""
    low = re.sub(r"\s*20\d\d[-/]\d\d(\d\d)?\s*$", "", title or "").lower().strip()
    # divisions before the generic conference check
    for frag, key in DIVISIONS.items():
        if frag + " winner" in low:
            return key
    if "super bowl" in low and "winner" in low:
        return "super_bowl_winner"
    if "afc championship" in low:
        return "afc_winner"
    if "nfc championship" in low:
        return "nfc_winner"
    if "regular season mvp" in low or low.endswith(" mvp"):
        return "mvp"
    # rookie checks must precede the player-of-the-year checks
    if "offensive rookie of the year" in low:
        return "oroy"
    if "defensive rookie of the year" in low:
        return "droy"
    if "offensive player of the year" in low:
        return "opoy"
    if "defensive player of the year" in low:
        return "dpoy"
    if "coach of the year" in low:
        return "coy"
    if "comeback player of the year" in low:
        return "cpoy"
    if "make the playoffs" in low:
        return "make_playoffs"
    if "miss the playoffs" in low:
        return "miss_playoffs"
    if "number 1 seed" in low:
        if low.startswith("to be the afc") or "afc" in low:
            return "afc_1_seed"
        if "nfc" in low:
            return "nfc_1_seed"
    if "rookie receiving yards" in low:
        return "most_rookie_receiving_yards"
    return None


def runner_odds(r):
    try:
        return r["winRunnerOdds"]["americanDisplayOdds"]["americanOdds"]
    except Exception:
        return None


def apply_fd_outrights(doc, fd):
    """Upsert FanDuel's outright/award columns from a parsed fd.json dict (the
    {layout, attachments} shape) into the shared outrights `doc`. Mutates doc and
    returns a summary. Pure: no file I/O — the FD column never clobbers DK/SCORE."""
    layout = fd.get("layout") or {}
    markets_att = (fd.get("attachments") or {}).get("markets") or {}
    coupons = layout.get("coupons") or {}

    markets = {}        # canon key -> {cand_key: (disp, american)}
    for coup in coupons.values():
        title = coup.get("title") or ""
        mid = coup.get("marketId")
        m = markets_att.get(str(mid)) if mid is not None else None
        runners = (m or {}).get("runners") or []
        if not runners:
            continue
        key = fd_canon(title)
        if key is None:
            continue
        kind = CANON[key][1]
        bucket = markets.setdefault(key, {})
        for r in runners:
            name = (r.get("runnerName") or "").strip()
            american = norm_american(runner_odds(r))
            if not name or american is None:
                continue
            ckey = team_key(name) if kind == "team" else norm_name(name)
            if ckey:
                bucket[ckey] = (name, american)

    for key, bucket in markets.items():
        cands = [(k, disp, am) for k, (disp, am) in bucket.items()]
        upsert_market(doc, key, "fd", cands)

    return {"coupons": len(coupons),
            "markets": {k: len(v) for k, v in markets.items()}}


def main():
    if not os.path.exists(FD_PATH):
        sys.exit("No FanDuel file at %s (run parse_fd_import.py first)" % FD_PATH)
    fd = json.load(open(FD_PATH))
    doc = load_outrights()
    s = apply_fd_outrights(doc, fd)
    save_outrights(doc)

    print("FD outrights — read data/fd.json (%d coupons)" % s["coupons"])
    print("\nCanonical markets written (FD column):")
    for key in sorted(s["markets"]):
        print("  %-26s %3d candidates" % (key, s["markets"][key]))
    print("\nWrote data/outrights.json")


if __name__ == "__main__":
    main()
