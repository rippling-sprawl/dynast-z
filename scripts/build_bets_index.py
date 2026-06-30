#!/usr/bin/env python3
"""Build data/bets-index.json — the autosuggest index for the Bets tracker.

Teams are hardcoded (32 NFL + 30 NBA). NFL players are seeded from the existing
data/fp.json snapshot. NBA players are left empty (typed manually for now).

Run by hand when the source data changes:  python3 scripts/build_bets_index.py
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (abbr, full name). The full name is shown in the dropdown; the abbr is the
# stored/displayed value. Search matches against both (abbr is hidden from the
# dropdown label but still searchable).
NFL_TEAMS = [
    ("ARI", "Arizona Cardinals"), ("ATL", "Atlanta Falcons"),
    ("BAL", "Baltimore Ravens"), ("BUF", "Buffalo Bills"),
    ("CAR", "Carolina Panthers"), ("CHI", "Chicago Bears"),
    ("CIN", "Cincinnati Bengals"), ("CLE", "Cleveland Browns"),
    ("DAL", "Dallas Cowboys"), ("DEN", "Denver Broncos"),
    ("DET", "Detroit Lions"), ("GB", "Green Bay Packers"),
    ("HOU", "Houston Texans"), ("IND", "Indianapolis Colts"),
    ("JAX", "Jacksonville Jaguars"), ("KC", "Kansas City Chiefs"),
    ("LV", "Las Vegas Raiders"), ("LAC", "Los Angeles Chargers"),
    ("LAR", "Los Angeles Rams"), ("MIA", "Miami Dolphins"),
    ("MIN", "Minnesota Vikings"), ("NE", "New England Patriots"),
    ("NO", "New Orleans Saints"), ("NYG", "New York Giants"),
    ("NYJ", "New York Jets"), ("PHI", "Philadelphia Eagles"),
    ("PIT", "Pittsburgh Steelers"), ("SF", "San Francisco 49ers"),
    ("SEA", "Seattle Seahawks"), ("TB", "Tampa Bay Buccaneers"),
    ("TEN", "Tennessee Titans"), ("WAS", "Washington Commanders"),
]

NBA_TEAMS = [
    ("ATL", "Atlanta Hawks"), ("BOS", "Boston Celtics"),
    ("BKN", "Brooklyn Nets"), ("CHA", "Charlotte Hornets"),
    ("CHI", "Chicago Bulls"), ("CLE", "Cleveland Cavaliers"),
    ("DAL", "Dallas Mavericks"), ("DEN", "Denver Nuggets"),
    ("DET", "Detroit Pistons"), ("GSW", "Golden State Warriors"),
    ("HOU", "Houston Rockets"), ("IND", "Indiana Pacers"),
    ("LAC", "LA Clippers"), ("LAL", "Los Angeles Lakers"),
    ("MEM", "Memphis Grizzlies"), ("MIA", "Miami Heat"),
    ("MIL", "Milwaukee Bucks"), ("MIN", "Minnesota Timberwolves"),
    ("NOP", "New Orleans Pelicans"), ("NYK", "New York Knicks"),
    ("OKC", "Oklahoma City Thunder"), ("ORL", "Orlando Magic"),
    ("PHI", "Philadelphia 76ers"), ("PHX", "Phoenix Suns"),
    ("POR", "Portland Trail Blazers"), ("SAC", "Sacramento Kings"),
    ("SAS", "San Antonio Spurs"), ("TOR", "Toronto Raptors"),
    ("UTA", "Utah Jazz"), ("WAS", "Washington Wizards"),
]


def teams(rows):
    return [{"abbr": abbr, "name": name} for abbr, name in rows]


def nfl_players() -> list[dict]:
    """Read data/fp.json and return real players (drop draft PICK entries)."""
    fp = json.loads((ROOT / "data" / "fp.json").read_text())
    players = []
    for p in fp:
        if p.get("position") == "PICK":
            continue
        name = (p.get("name") or "").strip()
        if not name:
            continue
        players.append({
            "name": name,
            "team": p.get("team") or "",
            "position": p.get("position") or "",
        })
    # Stable sort by name for predictable suggestions.
    players.sort(key=lambda x: x["name"].lower())
    return players


def build() -> None:
    index = {
        "leagues": ["NFL", "NBA", "Other"],
        "teams": {"NFL": teams(NFL_TEAMS), "NBA": teams(NBA_TEAMS)},
        "players": {"NFL": nfl_players(), "NBA": []},
    }
    out = ROOT / "data" / "bets-index.json"
    out.write_text(json.dumps(index, indent=2) + "\n")
    print(
        f"Wrote {out.relative_to(ROOT)} — "
        f"NFL teams: {len(index['teams']['NFL'])}, "
        f"NBA teams: {len(index['teams']['NBA'])}, "
        f"NFL players: {len(index['players']['NFL'])}"
    )


if __name__ == "__main__":
    build()
