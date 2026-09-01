#!/usr/bin/env python3
"""
Fetch FantasyPros dynasty trade values and save to data/fp.json.

Player data comes from Datawrapper CSV endpoints embedded in the article.
Draft pick data comes from HTML tables in the article.

Re-run this script (or replace data/fp.json manually) to update values.
"""

import csv
import io
import json
import os
import re
import subprocess
import sys

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

ARTICLE_URL = "https://www.fantasypros.com/2026/09/fantasy-football-rankings-dynasty-trade-value-chart-september-2026-update/"

# Datawrapper CSV endpoints for each position group
POSITION_CSVS = {
    "QB": "https://datawrapper.dwcdn.net/l2wfo/1/dataset.csv",
    "RB": "https://datawrapper.dwcdn.net/20Vr9/1/dataset.csv",
    "WR": "https://datawrapper.dwcdn.net/m7Gli/1/dataset.csv",
    "TE": "https://datawrapper.dwcdn.net/Ar02Z/1/dataset.csv",
}


def curl_fetch(url):
    result = subprocess.run(
        ["curl", "-s", "-A", UA, "--max-time", "15", url],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"curl failed for {url}: {result.stderr.strip()}")
    return result.stdout


def parse_player_csv(csv_text, position):
    """Parse a Datawrapper tab-separated CSV into player records."""
    players = []
    reader = csv.DictReader(io.StringIO(csv_text), delimiter="\t")
    for row in reader:
        name = row.get("Name", "").strip()
        team = row.get("Team", "").strip()
        # Prefer SF Value, fall back to Trade Value
        value_str = row.get("SF Value", "").strip() or row.get("Trade Value", "").strip()
        if not name or not value_str:
            continue
        try:
            value = int(value_str)
        except ValueError:
            continue
        players.append({
            "name": name,
            "position": position,
            "team": team,
            "value": value,
        })
    return players


def parse_pick_tables(html):
    """Parse draft pick tables from the article HTML."""
    picks = []
    slot_values = {}  # year -> {(round, slot): value} for pick-by-pick tables

    # Split by the year headers to determine context
    # Find all table blocks with their preceding context
    year = None
    html_joined = html

    # Determine year boundaries. FP publishes the next three rookie classes; the
    # furthest-out one is quoted in ranges rather than pick by pick.
    year_starts = []
    for y in ("2026", "2027", "2028", "2029", "2030"):
        pos = html_joined.find(f"{y} Dynasty Rookie Draft Pick Values")
        if pos > 0:
            year_starts.append((pos, y))
    year_starts.sort(reverse=True)

    # Find all tables within mobile-table divs
    table_pattern = re.compile(r'<div class="mobile-table">\s*<table[^>]*>(.*?)</table>', re.DOTALL)
    row_pattern = re.compile(r'<tr[^>]*>(.*?)</tr>', re.DOTALL)
    cell_pattern = re.compile(r'<td[^>]*>(.*?)</td>', re.DOTALL)

    for match in table_pattern.finditer(html_joined):
        table_html = match.group(1)
        table_pos = match.start()

        # Determine year from position in document (last header before the table)
        year = next((y for pos, y in year_starts if table_pos > pos), None)
        if not year:
            continue

        rows = row_pattern.findall(table_html)
        if not rows:
            continue

        # First row is header - skip it
        for row_html in rows[1:]:
            cells = cell_pattern.findall(row_html)
            if len(cells) < 3:
                continue

            pick_label = cells[0].strip()
            # Clean HTML entities
            pick_label = pick_label.replace("&#8211;", "–").replace("&ndash;", "–")
            pick_label = re.sub(r'<[^>]+>', '', pick_label).strip()

            # Prefer SF value (3rd column), fall back to 1QB (2nd column)
            value_str = re.sub(r'<[^>]+>', '', cells[2]).strip()
            if not value_str:
                value_str = re.sub(r'<[^>]+>', '', cells[1]).strip()

            try:
                value = int(value_str)
            except ValueError:
                continue

            # Skip "All Picks" / "All others" catch-alls
            if pick_label.lower().startswith("all"):
                continue

            slot_match = re.match(r'^(\d+)\.(\d+)$', pick_label)
            if slot_match:
                slot_values.setdefault(year, {})[
                    (int(slot_match.group(1)), int(slot_match.group(2)))
                ] = value

            pick_name = normalize_pick_name(pick_label, year)
            if pick_name:
                picks.append({
                    "name": pick_name,
                    "position": "PICK",
                    "team": "",
                    "value": value,
                })

    picks.extend(tiers_from_slots(slot_values, {p["name"] for p in picks}))
    return picks


# Slot buckets for a 12-team rookie draft, matching server.py's
# pick_tier_from_slot() (thirds of the round).
_SLOT_TIERS = (("Early", range(1, 5)), ("Mid", range(5, 9)), ("Late", range(9, 13)))
_ROUND_ORDINALS = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th"}


def tiers_from_slots(slot_values, existing_names):
    """Synthesize Early/Mid/Late tier entries from a pick-by-pick table.

    FP quotes the nearest rookie classes slot by slot ("1.01"), but a future
    season whose draft order isn't set yet can only be matched by tier
    ("2027 Early 1st") — that's the key server.py indexes picks under. Average
    each third of the round so those tiers stay populated. Any tier FP already
    publishes outright wins over the synthesized one."""
    synthesized = []
    for year, slots in slot_values.items():
        rounds = {rd for rd, _ in slots}
        for rd in sorted(rounds):
            ordinal = _ROUND_ORDINALS.get(rd, f"{rd}th")
            for tier, slot_range in _SLOT_TIERS:
                name = f"{year} {tier} {ordinal}"
                if name in existing_names:
                    continue
                vals = [slots[(rd, s)] for s in slot_range if (rd, s) in slots]
                if not vals:
                    continue
                synthesized.append({
                    "name": name,
                    "position": "PICK",
                    "team": "",
                    "value": round(sum(vals) / len(vals)),
                })
    return synthesized


def normalize_pick_name(label, year):
    """Convert FP pick labels to match existing naming conventions.

    FC format: "2026 Pick 1.01"
    KTC format: "2027 Early 1st"
    """
    # Specific picks like "1.01", "1.02", etc.
    if re.match(r'^\d+\.\d+$', label):
        return f"{year} Pick {label}"

    # 2027 range picks like "1.01 – 1.03"
    range_match = re.match(r'^(\d+)\.(\d+)\s*[–-]\s*(\d+)\.(\d+)$', label)
    if range_match:
        rd = int(range_match.group(1))
        start = int(range_match.group(2))
        end = int(range_match.group(4))
        rd_name = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th"}.get(rd, f"{rd}th")
        # Map position ranges to tiers
        if start <= 3:
            return f"{year} Early {rd_name}"
        elif start <= 6:
            return f"{year} Mid {rd_name}"
        else:
            return f"{year} Late {rd_name}"

    # Tier picks like "Early 2nd", "Mid 2nd", "Late 2nd", "Middle 3rd"
    tier_match = re.match(r'^(Early|Mid|Middle|Late)\s+(\d+)(st|nd|rd|th)$', label, re.IGNORECASE)
    if tier_match:
        tier = tier_match.group(1).capitalize()
        if tier == "Middle":
            tier = "Mid"
        rd_num = tier_match.group(2)
        rd_suffix = tier_match.group(3)
        return f"{year} {tier} {rd_num}{rd_suffix}"

    return None


MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}


def parse_article_month(url):
    """Extract (month_number, year, label) from the article URL slug, e.g.
    '...dynasty-trade-value-chart-july-2026-update/' -> (7, 2026, 'July 2026').

    The /football route uses this to warn when the served FP data is older than
    the current real-life month. Returns None if the slug can't be parsed."""
    match = re.search(
        r"(" + "|".join(MONTHS) + r")-(\d{4})-update", url, re.IGNORECASE
    )
    if not match:
        return None
    month_name = match.group(1).lower()
    year = int(match.group(2))
    return MONTHS[month_name], year, f"{month_name.capitalize()} {year}"


def main():
    all_players = []

    # Fetch player CSVs
    for position, url in POSITION_CSVS.items():
        print(f"Fetching {position} data...")
        csv_text = curl_fetch(url)
        players = parse_player_csv(csv_text, position)
        print(f"  Found {len(players)} {position}s")
        all_players.extend(players)

    # Fetch article HTML for pick tables
    print("Fetching article for pick tables...")
    html = curl_fetch(ARTICLE_URL)
    picks = parse_pick_tables(html)
    print(f"  Found {len(picks)} picks")
    all_players.extend(picks)

    # Verify expected values
    by_name = {p["name"]: p for p in all_players}
    # Spot values read off the September 2026 article (SF column)
    checks = [
        ("Josh Allen", 100),
        ("Jahmyr Gibbs", 86),
        ("Ja'Marr Chase", 89),
        ("Brock Bowers", 72),  # non-TEP column, matching the SF chart
        ("2026 Pick 1.01", 69),
        ("2026 Early 2nd", 34),
        ("2027 Pick 1.01", 76),
        ("2027 Late 2nd", 35),
        ("2028 Early 1st", 51),
        ("2028 Late 1st", 32),
    ]
    print("\nVerification:")
    for name, expected in checks:
        actual = by_name.get(name, {}).get("value")
        status = "OK" if actual == expected else f"MISMATCH (got {actual})"
        print(f"  {name}: expected {expected} -> {status}")

    # Write output
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
    os.makedirs(data_dir, exist_ok=True)
    out_path = os.path.join(data_dir, "fp.json")
    with open(out_path, "w") as f:
        json.dump(all_players, f, indent=2)
    print(f"\nWrote {len(all_players)} entries to {os.path.abspath(out_path)}")

    # Write metadata (article month) so /football can flag stale data
    parsed = parse_article_month(ARTICLE_URL)
    if not parsed:
        print(f"WARNING: could not parse month from ARTICLE_URL: {ARTICLE_URL}")
    else:
        month, year, label = parsed
        meta_path = os.path.join(data_dir, "fp_meta.json")
        with open(meta_path, "w") as f:
            json.dump({
                "month": month,
                "year": year,
                "label": label,
                "articleUrl": ARTICLE_URL,
            }, f, indent=2)
        print(f"Wrote metadata ({label}) to {os.path.abspath(meta_path)}")


if __name__ == "__main__":
    main()
