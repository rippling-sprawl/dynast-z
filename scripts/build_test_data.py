#!/usr/bin/env python3
"""Build data/test_data.json — a read-only seed of demo bets for the tracker.

Coerces scripts/test_data.csv (a flat wager log, ~470 NFL/NBA bets from
2019-2021) into the app's per-bet schema (see scripts/primary/bets.js). The
output is loaded at runtime as a read-only "seed" layer merged into the bets
views FOR DISPLAY ONLY — it is never written to localStorage, so it can't
collide with the user's real bets. Every seeded bet carries `_test: true`.

Accuracy of the demo data is not critical; the goal is a realistic-looking
history to design and test the UI against.

Run by hand when the CSV changes:  python3 scripts/build_test_data.py
"""

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "scripts" / "test_data.csv"
OUT_PATH = ROOT / "data" / "test_data.json"

# Mirror SPORT_BY_LEAGUE in scripts/primary/bets.js.
SPORT_BY_LEAGUE = {"NFL": "Football", "NBA": "Basketball", "Other": ""}

# CSV "Result" -> app status. The app has no "cancelled" status, so a voided /
# cancelled bet is graded as a push (stake returned, P/L 0).
STATUS_BY_RESULT = {
    "win": "win",
    "loss": "loss",
    "push": "push",
    "cancelled": "void",
    "void": "void",
}

# How many of the most-recent rows (by start time) to leave as `pending`, so the
# /bets landing page (which only shows pending) also renders seeded tiles.
PENDING_SAMPLE = 5


def american_to_decimal(american):
    """Same math as americanToDecimal() in bets.js."""
    a = float(american)
    if a == 0:
        return None
    return (a / 100) + 1 if a > 0 else (100 / abs(a)) + 1


def to_win_from_odds(stake, american):
    """Profit if the bet wins — same as toWinFromOdds() in bets.js."""
    d = american_to_decimal(american)
    s = float(stake)
    if not d or not s:
        return None
    return round(s * (d - 1), 2)


def fmt_line(value):
    """Render a spread/total number without a trailing .0 (e.g. -3, 6.5)."""
    f = float(value)
    return str(int(f)) if f == int(f) else str(f)


def fmt_spread(value):
    """Like fmt_line but with an explicit sign for the favorite/dog (e.g. +5)."""
    f = float(value)
    return ("+" if f > 0 else "") + fmt_line(value)


def parse_game(game):
    """'AWAY @ HOME' -> (away, home). Falls back gracefully if malformed."""
    parts = [p.strip() for p in game.split("@")]
    if len(parts) == 2:
        return parts[0], parts[1]
    return game.strip(), ""


def coerce_row(row, index):
    league = (row["League"] or "").strip().upper()
    bet_type = (row["Type"] or "").strip()
    away, home = parse_game(row["Game"])
    line = row["Odds/Spread/Total"]
    odds = int(float(row["Odds"]))
    stake = round(float(row["Money Wagered"]), 2)

    # Which side is backed, and the opponent.
    is_away = bet_type.endswith("_away") or bet_type.startswith("away_")
    is_home = bet_type.endswith("_home") or bet_type.startswith("home_")
    game_total = bet_type in ("over", "under")

    if game_total:
        side, opponent = row["Game"].strip(), ""
    elif is_home:
        side, opponent = home, away
    else:  # default to away for *_away and anything unrecognized
        side, opponent = away, home

    # Human-readable selection from the bet type + line.
    if bet_type.startswith("ml_"):
        selection = "ML"
    elif bet_type.startswith("spread_"):
        selection = "PK" if float(line) == 0 else fmt_spread(line)
    elif bet_type == "over":
        selection = "Over " + fmt_line(line)
    elif bet_type == "under":
        selection = "Under " + fmt_line(line)
    elif bet_type.endswith("_over"):
        selection = "Team Over " + fmt_line(line)
    elif bet_type.endswith("_under"):
        selection = "Team Under " + fmt_line(line)
    else:
        selection = ""

    match = (side + " vs " + opponent) if opponent else row["Game"].strip()

    status = STATUS_BY_RESULT.get((row["Result"] or "").strip().lower(), "void")
    when = (row["Start Time"] or "").strip()

    return {
        "id": "t_%04d" % index,
        "league": league,
        "sport": SPORT_BY_LEAGUE.get(league, ""),
        "side": side,
        "opponent": opponent,
        "match": match,
        "selection": selection,
        "stake": stake,
        "odds_american": odds,
        "odds_decimal": american_to_decimal(odds),
        "to_win": to_win_from_odds(stake, odds),
        "event_date": when,
        "status": status,
        "placed_at": when,
        "settled_at": when,
        "_test": True,
    }


def main():
    with CSV_PATH.open(newline="") as f:
        rows = list(csv.DictReader(f))

    bets = [coerce_row(row, i + 1) for i, row in enumerate(rows)]

    # Flip the most-recent N bets to pending so /bets shows seeded tiles too.
    by_recency = sorted(
        range(len(bets)), key=lambda i: bets[i]["placed_at"], reverse=True
    )
    for i in by_recency[:PENDING_SAMPLE]:
        bets[i]["status"] = "pending"
        bets[i]["settled_at"] = None

    OUT_PATH.write_text(json.dumps(bets, indent=2) + "\n")

    pending = sum(1 for b in bets if b["status"] == "pending")
    print(
        "Wrote %d bets to %s (%d pending, %d settled)"
        % (len(bets), OUT_PATH.relative_to(ROOT), pending, len(bets) - pending)
    )


if __name__ == "__main__":
    main()
