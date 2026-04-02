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

ARTICLE_URL = "https://www.fantasypros.com/2026/04/fantasy-football-rankings-dynasty-trade-value-chart-april-2026-update/"

# Datawrapper CSV endpoints for each position group
POSITION_CSVS = {
    "QB": "https://datawrapper.dwcdn.net/yqKj2/1/dataset.csv",
    "RB": "https://datawrapper.dwcdn.net/ZVpNh/1/dataset.csv",
    "WR": "https://datawrapper.dwcdn.net/yuwfA/1/dataset.csv",
    "TE": "https://datawrapper.dwcdn.net/GFqDz/1/dataset.csv",
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

    # Split by the year headers to determine context
    # Find all table blocks with their preceding context
    year = None
    lines = html.split("\n")
    html_joined = html

    # Determine year boundaries
    year_2026_start = html_joined.find("2026 Dynasty Rookie Draft Pick Values")
    year_2027_start = html_joined.find("2027 Dynasty Rookie Draft Pick Values")

    # Find all tables within mobile-table divs
    table_pattern = re.compile(r'<div class="mobile-table">\s*<table[^>]*>(.*?)</table>', re.DOTALL)
    row_pattern = re.compile(r'<tr>(.*?)</tr>', re.DOTALL)
    cell_pattern = re.compile(r'<td[^>]*>(.*?)</td>', re.DOTALL)

    for match in table_pattern.finditer(html_joined):
        table_html = match.group(1)
        table_pos = match.start()

        # Determine year from position in document
        if year_2027_start > 0 and table_pos > year_2027_start:
            year = "2027"
        elif year_2026_start > 0 and table_pos > year_2026_start:
            year = "2026"
        else:
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

            pick_name = normalize_pick_name(pick_label, year)
            if pick_name:
                picks.append({
                    "name": pick_name,
                    "position": "PICK",
                    "team": "",
                    "value": value,
                })

    return picks


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
    checks = [
        ("Josh Allen", 101),
        ("Bo Nix", 70),
        ("2026 Pick 1.01", 68),
        ("2027 Early 1st", 68),
        ("2027 Late 1st", 47),
        ("2027 Late 2nd", 29),
        ("2026 Early 2nd", 37),
    ]
    print("\nVerification:")
    for name, expected in checks:
        actual = by_name.get(name, {}).get("value")
        status = "OK" if actual == expected else f"MISMATCH (got {actual})"
        print(f"  {name}: expected {expected} -> {status}")

    # Write output
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "fp.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(all_players, f, indent=2)
    print(f"\nWrote {len(all_players)} entries to {os.path.abspath(out_path)}")


if __name__ == "__main__":
    main()
