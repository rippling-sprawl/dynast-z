#!/usr/bin/env python3
"""
Fetch FantasyPros half-PPR REDRAFT rankings and save to data/fp_redraft.json.

Sibling of fetch_fp.py, which handles the *dynasty* trade value chart. This one
handles seasonal half-PPR expert consensus rankings (ECR) — the currency that
matters for a redraft/keeper draft. Keep both; they feed different features.

The rankings arrive as a `var ecrData = {...};` JSON blob embedded in the page
HTML, so no HTML table parsing is needed.

Re-run this script before the draft to refresh. The output is committed and
served from the CDN, matching how data/fp.json works — FantasyPros would likely
block a Vercel serverless IP if we scraped at request time.
"""

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

RANKINGS_URL = "https://www.fantasypros.com/nfl/rankings/half-point-ppr-cheatsheets.php"

# Sanity floor: the half-PPR cheatsheet carries the full draft pool. Anything
# far below this means the page shape changed and we're parsing a fragment.
MIN_EXPECTED_PLAYERS = 300


def curl_fetch(url):
    result = subprocess.run(
        ["curl", "-s", "-A", UA, "--max-time", "30", url],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"curl failed for {url}: {result.stderr.strip()}")
    return result.stdout


def parse_ecr_data(html):
    """Extract and parse the `var ecrData = {...};` blob from the page HTML."""
    match = re.search(r"var ecrData\s*=\s*(\{.*?\});\s*\n", html, re.S)
    if not match:
        raise RuntimeError(
            "Could not find `var ecrData = {...};` in the page. FantasyPros "
            "likely changed their page structure — inspect the HTML and update "
            "the regex in parse_ecr_data()."
        )
    return json.loads(match.group(1))


def to_int(value):
    """Coerce FantasyPros' mixed str/int fields to int, or None."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


# FantasyPros and Sleeper disagree on two points of vocabulary. Reconcile here,
# at scrape time, so everything downstream speaks Sleeper's dialect and no
# consumer has to remember the difference.
#   - team defenses: FP says "DST", Sleeper says "DEF"
#   - Jacksonville: FP says "JAC", Sleeper says "JAX" (23 players affected)
_POSITION_ALIASES = {"DST": "DEF", "D/ST": "DEF", "PK": "K"}
_TEAM_ALIASES = {
    "JAC": "JAX", "GBP": "GB", "KCC": "KC", "LVR": "LV",
    "NEP": "NE", "NOS": "NO", "SFO": "SF", "TBB": "TB",
}


def normalize_players(data):
    """Reduce the raw ecrData players to the fields the board actually uses,
    translated into Sleeper's position/team vocabulary."""
    players = []
    for p in data.get("players", []):
        name = (p.get("player_name") or "").strip()
        rank = to_int(p.get("rank_ecr"))
        if not name or rank is None:
            continue
        pos = (p.get("player_position_id") or "").strip().upper()
        team = (p.get("player_team_id") or "").strip().upper()
        pos = _POSITION_ALIASES.get(pos, pos)
        team = _TEAM_ALIASES.get(team, team)
        pos_rank = (p.get("pos_rank") or "").strip()
        if pos == "DEF":
            pos_rank = pos_rank.replace("DST", "DEF")
        players.append({
            "name": name,
            "position": pos,
            "team": team,
            "rank": rank,
            "pos_rank": pos_rank,
            "tier": to_int(p.get("tier")),
            "bye": to_int(p.get("player_bye_week")),
        })
    players.sort(key=lambda x: x["rank"])
    return players


def main():
    print(f"Fetching {RANKINGS_URL} ...")
    html = curl_fetch(RANKINGS_URL)
    print(f"  {len(html):,} bytes")

    data = parse_ecr_data(html)
    players = normalize_players(data)
    print(f"  Parsed {len(players)} players "
          f"({data.get('type')}, {data.get('total_experts')} experts, "
          f"updated {data.get('last_updated')})")

    if len(players) < MIN_EXPECTED_PLAYERS:
        print(f"ERROR: only {len(players)} players parsed, expected at least "
              f"{MIN_EXPECTED_PLAYERS}. Refusing to overwrite good data.",
              file=sys.stderr)
        return 1

    # Verification: the top of the board should be recognizable skill players,
    # and every position group the draft uses should be represented.
    by_pos = {}
    for p in players:
        by_pos[p["position"]] = by_pos.get(p["position"], 0) + 1
    print("\nPosition counts:")
    for pos in sorted(by_pos, key=lambda k: -by_pos[k]):
        print(f"  {pos}: {by_pos[pos]}")

    missing = [pos for pos in ("QB", "RB", "WR", "TE", "K", "DEF") if pos not in by_pos]
    if missing:
        print(f"WARNING: no players found for position(s): {', '.join(missing)}")

    # Vocabulary must match Sleeper's, or nothing resolves to a player_id.
    stray_pos = sorted(set(by_pos) - {"QB", "RB", "WR", "TE", "K", "DEF"})
    if stray_pos:
        print(f"WARNING: unexpected position code(s) {stray_pos} — these will "
              f"fail to resolve against Sleeper.")
    if any(p["team"] == "JAC" for p in players):
        print("WARNING: 'JAC' survived normalization; Sleeper uses 'JAX'.")

    print("\nTop 5:")
    for p in players[:5]:
        print(f"  {p['rank']:>3}. {p['name']} ({p['pos_rank']}, {p['team']}) tier {p['tier']}")

    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
    os.makedirs(data_dir, exist_ok=True)

    out_path = os.path.join(data_dir, "fp_redraft.json")
    with open(out_path, "w") as f:
        json.dump(players, f, indent=2)
    print(f"\nWrote {len(players)} players to {os.path.abspath(out_path)}")

    # Metadata so the board can show its own freshness and warn when stale.
    meta = {
        "source": "FantasyPros",
        "type": data.get("type", "Draft Half PPR"),
        "scoring": data.get("scoring", "HALF"),
        "year": data.get("year"),
        "experts": data.get("total_experts"),
        "count": len(players),
        # FantasyPros' own "M/D" label, plus our fetch time — the label alone
        # has no year, so the board needs the timestamp to compute staleness.
        "last_updated": data.get("last_updated"),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fetched_ts": int(time.time()),
        "url": RANKINGS_URL,
    }
    meta_path = os.path.join(data_dir, "fp_redraft_meta.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Wrote metadata to {os.path.abspath(meta_path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
