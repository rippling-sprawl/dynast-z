#!/usr/bin/env python3
"""
Fold a consensus regular-season win total into data/nfl_projections_2026.json,
so Baker's Buns can print an Over/Under column beside the playoff prices it
already carries.

Input  : data/dk.json          (DraftKings, "<TEAM> Regular Season Wins" + alts)
         data/fd.json          (FanDuel, "<Team> - Regular Season Wins 2026-27")
         data/score/wins.json  (theScore, one main line per team)
Output : data/nfl_projections_2026.json — each team's `odds` gains
             winTotal  the consensus line          e.g. 9.5
             over      consensus American price    e.g. -122
             under     consensus American price    e.g. +102
             winBooks  which books priced it       e.g. ["dk", "fd"]

Nothing else in the file is touched: the score, the z-blocks, the notes and the
make/miss/division prices are all read back and written out as they were.

--- picking the line ---
The three books do not always hang the total in the same place (DK had the
Cardinals at 3.5 while FanDuel and theScore had 4.5), so "the consensus total"
has to be chosen rather than copied. Every line either book quotes is a
candidate as long as at least half the books covering that team quote it, and
the winner is the candidate whose average *de-vigged* Over probability sits
closest to a coin flip. That is what a main line is: the number the market
cannot lean off. It reproduces each book's own main line wherever the books
agree, and breaks a straddle on the side two of the three books took.

The vig only comes off to choose the line. The printed prices are the plain
average of the books' implied probabilities at that line, converted back to
American — a price a reader can go and compare against a screen, not a fair
value they can never bet.

Books are used if they have the market, so the consensus widens on its own as
captures are refreshed (see the parse_*_import.py scripts). A team priced by
one book alone still gets that book's line, and `winBooks` says so.
"""
import collections
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from outright_common import team_key  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DK_PATH = os.path.join(ROOT, "data", "dk.json")
FD_PATH = os.path.join(ROOT, "data", "fd.json")
SCORE_PATH = os.path.join(ROOT, "data", "score", "wins.json")
PROJ_PATH = os.path.join(ROOT, "data", "nfl_projections_2026.json")

SOURCE_NOTE = (
    "Consensus regular-season win total: the line whose de-vigged Over price "
    "sits closest to even across DraftKings, FanDuel and theScore, priced at "
    "the average of those books' implied probabilities at that line."
)


# ---------------------------------------------------------------------------
# odds helpers
# ---------------------------------------------------------------------------
def american(value):
    """DK's unicode-minus string, FD's signed int, theScore's '+120' / 'Even'."""
    if value is None:
        return None
    s = str(value).strip().replace("−", "-")
    if s.lower() == "even":
        return 100
    try:
        return int(s.lstrip("+"))
    except ValueError:
        return None


def implied(odds):
    """American price -> implied probability, vig included."""
    o = float(odds)
    return (-o) / ((-o) + 100) if o < 0 else 100.0 / (o + 100)


def to_american(prob):
    """Probability -> American price, rounded to a whole number."""
    if prob >= 0.5:
        return -int(round(100 * prob / (1 - prob)))
    return int(round(100 * (1 - prob) / prob))


# ---------------------------------------------------------------------------
# readers — each returns {team_key: {line: {"over": odds, "under": odds}}}
# ---------------------------------------------------------------------------
def _tree():
    return collections.defaultdict(lambda: collections.defaultdict(dict))


def read_dk(path):
    """DK ships markets and selections as parallel lists linked by marketId."""
    doc = json.load(open(path))
    by_market = collections.defaultdict(list)
    for s in doc.get("selections", []):
        by_market[s.get("marketId")].append(s)

    out = _tree()
    for m in doc.get("markets", []):
        name = m.get("name", "")
        if "Regular Season Wins" not in name:
            continue
        key = team_key(name.split(" Regular Season Wins")[0])
        if not key:
            continue
        for s in by_market.get(m.get("id"), []):
            side = (s.get("outcomeType") or "").lower()
            odds = american((s.get("displayOdds") or {}).get("american"))
            if side in ("over", "under") and s.get("points") is not None and odds:
                out[key][float(s["points"])][side] = odds
    return out


FD_RUNNER = re.compile(r"^(?P<team>.+) (?P<side>Over|Under) (?P<line>[\d.]+) Wins$")


def read_fd(path):
    """FanDuel hangs every alternate off one market as named runners."""
    doc = json.load(open(path))
    out = _tree()
    for m in (doc.get("attachments", {}).get("markets") or {}).values():
        if "Regular Season Wins" not in m.get("marketName", ""):
            continue
        key = team_key(m["marketName"].split(" - ")[0])
        if not key:
            continue
        for r in m.get("runners", []):
            hit = FD_RUNNER.match(r.get("runnerName", ""))
            if not hit:
                continue
            try:
                odds = american(r["winRunnerOdds"]["americanDisplayOdds"]["americanOdds"])
            except (KeyError, TypeError):
                continue
            if odds:
                out[key][float(hit.group("line"))][hit.group("side").lower()] = odds
    return out


def read_score(path):
    """theScore's per-stat file: one TOTAL market per team, main line only."""
    if not os.path.exists(path):
        return _tree()
    doc = json.load(open(path))
    out = _tree()
    markets = []

    def walk(node):
        if isinstance(node, dict):
            if "selections" in node and "name" in node:
                markets.append(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(doc)
    for m in markets:
        name = m.get("name", "")
        if "Regular Season Wins" not in name:
            continue
        key = team_key(name.split(" Regular Season Wins")[0])
        if not key:
            continue
        for s in m.get("selections", []):
            side = (s.get("type") or "").lower()
            line = ((s.get("points") or {}).get("decimalPoints"))
            odds = american(((s.get("odds") or {}).get("formattedOdds")))
            if side in ("over", "under") and line is not None and odds:
                out[key][float(line)][side] = odds
    return out


# ---------------------------------------------------------------------------
# the consensus
# ---------------------------------------------------------------------------
def consensus(books, key):
    """-> (line, over, under, [book, ...]) or None if no book prices the team."""
    quoted = collections.defaultdict(dict)   # line -> {book: {"over":…, "under":…}}
    covering = 0
    for book, teams in books.items():
        lines = teams.get(key)
        if not lines:
            continue
        covering += 1
        for line, sides in lines.items():
            if "over" in sides and "under" in sides:
                quoted[line][book] = sides
    if not quoted:
        return None

    # Half the covering books, rounded up: one book's private alternate never
    # outvotes a line the rest of the market actually hangs.
    need = math.ceil(covering / 2)
    candidates = [ln for ln, at in quoted.items() if len(at) >= need] or list(quoted)

    def balance(line):
        """Mean de-vigged Over probability at this line — 0.5 is a coin flip."""
        vals = []
        for sides in quoted[line].values():
            over, under = implied(sides["over"]), implied(sides["under"])
            vals.append(over / (over + under))
        return sum(vals) / len(vals)

    # Ties (a straddle with no book in the middle) fall to the lower line, so
    # the same input can never produce two different files.
    line = min(candidates, key=lambda ln: (round(abs(balance(ln) - 0.5), 9), ln))

    at = quoted[line]
    over = to_american(sum(implied(s["over"]) for s in at.values()) / len(at))
    under = to_american(sum(implied(s["under"]) for s in at.values()) / len(at))
    return line, over, under, sorted(at)


def main():
    books = {
        "dk": read_dk(DK_PATH),
        "fd": read_fd(FD_PATH),
        "score": read_score(SCORE_PATH),
    }
    for name, teams in books.items():
        print("%-6s %2d teams" % (name, len(teams)))

    proj = json.load(open(PROJ_PATH))
    priced, missing = 0, []
    for team in proj.get("teams", []):
        key = team_key(team.get("team"), team.get("abbr"))
        got = consensus(books, key) if key else None
        odds = team.setdefault("odds", {})
        if not got:
            missing.append(team.get("team"))
            for field in ("winTotal", "over", "under", "winBooks"):
                odds.pop(field, None)
            continue
        line, over, under, at = got
        odds["winTotal"] = line
        odds["over"] = over
        odds["under"] = under
        odds["winBooks"] = at
        priced += 1
        print("  %-4s %5.1f  %+5d / %+5d  %s" % (key, line, over, under, ",".join(at)))

    proj["winTotalSource"] = SOURCE_NOTE
    with open(PROJ_PATH, "w") as fh:
        # ensure_ascii matches how the file is already written, so a rebuild
        # shows only the lines that actually changed.
        json.dump(proj, fh, indent=2)
        fh.write("\n")

    print("\nwrote %s — %d of %d teams priced" % (
        os.path.relpath(PROJ_PATH, ROOT), priced, len(proj.get("teams", []))))
    if missing:
        print("no win total for: " + ", ".join(missing))


if __name__ == "__main__":
    main()
