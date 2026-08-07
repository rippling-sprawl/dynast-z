#!/usr/bin/env python3
"""
Season-long player props, reduced to two numbers a draft board can print:
data/nfl_prop_lines.json.

Reads the three committed book snapshots — data/fd.json (FanDuel),
data/dk.json (DraftKings), data/score/*.json (ESPN, "SCORE") — which are the
same three files /odds reads, and which the Recorder ingest keeps current. This
script adds no network calls and no new source: everything here is already in
the repo, just spread across three vendor shapes and 196 markets.

What comes out, per player:

    yards   the consensus season yardage line
    tds     the consensus season touchdown line

CONSENSUS = the mean of the books' main lines for that market, which is exactly
what /odds already calls FMV (fair market value). It is not de-vigged and it is
not a probability: an O/U line is already the market's midpoint estimate of the
quantity, and the vig lives in the two prices flanking it, not in the number
itself. Averaging the number across books is the whole of the fair value here.
The prices are read only to decide WHICH line is a book's main one — see
main_line() — and are then discarded.

BOTH NUMBERS ARE SUMS ACROSS MARKETS. A player is priced on one to three
separate markets (passing/rushing/receiving x yards/TDs); "his yards" is all of
them added up, so a dual-threat QB with a 4,000-yard passing line and a 575-yard
rushing line reads 4575, and Bijan reads his rushing line because that is the
only yardage the market prices him for. The alternative — one market chosen per
position — would have thrown away a real priced market on the six players whose
legs are the reason they go in the first round. The per-market breakdown ships
alongside the totals so the board's tooltip can say which markets made the sum.

Coverage is thin by nature and that is fine: the books price ~105 players, the
board holds ~860. A player with no market gets no entry and the board prints
nothing for him. A player priced for yards but not TDs gets one of the two.

Usage:
    python3 scripts/build_prop_lines.py
"""
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone

# The six season-long markets the books actually put up. Ordered so the
# breakdown in a tooltip reads pass -> rush -> receive, the way a stat line does.
YARD_STATS = ("passing yards", "rushing yards", "receiving yards")
TD_STATS = ("passing tds", "rushing tds", "receiving tds")
STATS = YARD_STATS + TD_STATS

# Sanity floor. The books price roughly a hundred skill players each summer; a
# run that produces a handful means a vendor shape moved and the parse fell
# through, which must not overwrite a good file.
MIN_EXPECTED_PLAYERS = 40

BOOKS = ("fd", "dk", "score")


def repo_path(*parts):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", *parts)


# ---------------------------------------------------------------------------
# Player keys
#
# norm_name() MUST stay byte-for-byte equivalent to normName() in
# scripts/primary/oven-board.js — and to the identical copies in
# fetch_pos_ranks.py and fetch_nfl_weekly.py. The board joins this file by that
# string. If they drift, the join silently returns nothing and the odds columns
# go blank on every row with no error anywhere.
#
# Unlike the pos-ranks file, the key here carries NO position prefix. A book
# market says "Lamar Jackson Regular Season Rushing Yards" and nothing else —
# there is no position in the feed, and inferring one from the market would file
# every rushing line under RB, which is wrong for exactly the players who matter
# most. So this file keys on the name alone and the board looks up by name.
# ---------------------------------------------------------------------------

_SUFFIXES = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b")


def norm_name(s):
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.lower().replace(".", "")
    s = re.sub(r"['‘’`]", "", s)
    s = re.sub(r"[-–—]", " ", s)
    s = _SUFFIXES.sub("", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def stat_key(s):
    """Collapse a market title to its stat: both "Aaron Rodgers Regular Season
    Passing Yards 2026-27" and the ESPN page title "Regular Season Passing
    Yards" become "passing yards". Mirrors statKey() in views/odds/index.html —
    it is what keeps a QB's passing line from landing on a rushing market."""
    s = (s or "").lower()
    s = re.sub(r".*regular season\s*", "", s)
    s = re.sub(r"[^a-z\s]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def american_to_prob(odds):
    """American price -> implied probability, vig included. Only used to rank a
    book's alternate lines by how balanced they are, so the vig is irrelevant."""
    if odds is None:
        return None
    s = str(odds).strip().replace("−", "-")
    if re.fullmatch(r"(?i)even", s):
        s = "+100"
    if not re.fullmatch(r"[+-]?\d+", s):
        return None
    n = int(s)
    if n == 0:
        return None
    return (-n) / ((-n) + 100) if n < 0 else 100 / (n + 100)


def main_line(lines):
    """A book's featured line for one player+stat, given {line: {Over: price,
    Under: price}}.

    DraftKings and FanDuel both list alternates. The main one is the paired O/U
    whose two implied probabilities sit closest together — that is the number
    the book is actually hanging its market on, and the only one comparable to
    another book's. A line missing a side scores worst and is taken only if it
    is all there is. Same rule as buildDkIndex()/buildOuBody() in
    views/odds/index.html, so this file and the /odds FMV column never disagree
    about which line a book is offering."""
    best, best_score = None, None
    for value, sides in lines.items():
        po = american_to_prob(sides.get("Over"))
        pu = american_to_prob(sides.get("Under"))
        score = abs(po - pu) if (po is not None and pu is not None) else 9.0
        # Ties break toward the lower line only so the output is deterministic
        # across dict orderings; a real tie between two alternates is a book
        # quoting the same market twice and either answer is the same market.
        if best_score is None or score < best_score or (score == best_score and value < best):
            best, best_score = value, score
    return best


# ---------------------------------------------------------------------------
# Book parsers — one per vendor shape, all returning the same thing:
#   { (book_name_as_written, stat): line }
# Names are kept AS THE BOOK WROTE THEM here and reconciled later, because the
# reconciliation needs to see the spellings side by side to match "Cam Ward" to
# "Cameron Ward".
# ---------------------------------------------------------------------------

def parse_fd(path):
    """FanDuel: one market per player+stat, titled "<Player> Regular Season
    <Stat> 2026-27", with runners named "<Player> Over 3025.5"."""
    out = {}
    try:
        with open(path) as f:
            doc = json.load(f)
    except (OSError, ValueError) as e:
        print(f"  fd: unreadable ({e})", file=sys.stderr)
        return out

    markets = ((doc.get("attachments") or {}).get("markets") or {})
    for m in markets.values():
        title = m.get("marketName") or ""
        stat = stat_key(re.sub(r"\s*20\d\d[-/]\d\d\s*$", "", title))
        if stat not in STATS:
            continue
        player = re.sub(r"\s+Regular Season.*$", "", title, flags=re.I).strip()
        if not player:
            continue
        lines = {}
        for r in m.get("runners") or []:
            rm = re.match(r"^(.*?)\s+(Over|Under)\s+([\d.]+)(?:\s+.*)?$", r.get("runnerName") or "")
            if not rm:
                continue
            odds = ((r.get("winRunnerOdds") or {}).get("americanDisplayOdds") or {}).get("americanOdds")
            lines.setdefault(float(rm.group(3)), {})[rm.group(2)] = odds
        line = main_line(lines) if lines else None
        if line is not None:
            out[(player, stat)] = line
    return out


def parse_dk(path):
    """DraftKings: markets named "NFL 2026/27 - <Player> Regular Season <Stat>",
    with the line in each selection's LABEL ("Over 1024.5") rather than in a
    points field — the props feed leaves points null, unlike team win totals."""
    out = {}
    try:
        with open(path) as f:
            doc = json.load(f)
    except (OSError, ValueError) as e:
        print(f"  dk: unreadable ({e})", file=sys.stderr)
        return out

    info = {}
    for m in doc.get("markets") or []:
        name = m.get("name") or ""
        stat = stat_key(name)
        if stat not in STATS:
            continue
        # The league/season prefix, e.g. "NFL 2026/27 - ". The separator is a
        # plain hyphen on most markets and an EN DASH on some (Travis Kelce's
        # two, in the current snapshot) — matching only the hyphen leaves the
        # prefix glued to the name, and "nfl 2026 27 travis kelce" joins to no
        # board row and reports no error.
        player = re.sub(r"^NFL\s*[^–—-]*[–—-]\s*", "", name)
        player = re.sub(r"\s+Regular Season.*$", "", player, flags=re.I).strip()
        if player:
            info[m.get("id")] = (player, stat)

    acc = {}
    for s in doc.get("selections") or []:
        meta = info.get(s.get("marketId"))
        if not meta:
            continue
        side = s.get("outcomeType")
        if side not in ("Over", "Under"):
            continue
        pts = s.get("points")
        if isinstance(pts, dict):
            pts = pts.get("decimalPoints")
        if pts is None:
            lm = re.search(r"([\d.]+)", s.get("label") or "")
            pts = float(lm.group(1)) if lm else None
        if pts is None:
            continue
        price = (s.get("displayOdds") or {}).get("american")
        acc.setdefault(meta, {}).setdefault(float(pts), {})[side] = price

    for meta, lines in acc.items():
        line = main_line(lines)
        if line is not None:
            out[meta] = line
    return out


def parse_score(dirpath):
    """ESPN ("SCORE"): one file per stat, the stat named by the page title, with
    TOTAL markets buried in a nested page tree ("<Player> Total Rushing Yards").
    One line per market — no alternates."""
    out = {}
    if not os.path.isdir(dirpath):
        print(f"  score: no directory at {dirpath}", file=sys.stderr)
        return out

    for fname in sorted(os.listdir(dirpath)):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(dirpath, fname)) as f:
                doc = json.load(f)
        except (OSError, ValueError) as e:
            print(f"  score/{fname}: unreadable ({e})", file=sys.stderr)
            continue
        page = ((doc.get("data") or {}).get("page") or {})
        stat = stat_key(page.get("title") or "")
        if stat not in STATS:
            continue
        for sec in page.get("pageChildren") or []:
            for shelf in sec.get("sectionChildren") or []:
                for card in shelf.get("marketplaceShelfChildren") or []:
                    for m in card.get("markets") or []:
                        name = m.get("name") or ""
                        player = re.sub(r"\s+Total\s+.*$", "", name, flags=re.I)
                        player = re.sub(r"\s+Regular Season.*$", "", player, flags=re.I).strip()
                        if not player:
                            continue
                        lines = {}
                        for s in m.get("selections") or []:
                            raw = ((s.get("name") or {}).get("cleanName")) or s.get("type") or ""
                            side = ("Over" if re.fullmatch(r"(?i)over", raw)
                                    else "Under" if re.fullmatch(r"(?i)under", raw) else None)
                            pts = (s.get("points") or {}).get("decimalPoints")
                            if side is None or pts is None:
                                continue
                            lines.setdefault(float(pts), {})[side] = \
                                (s.get("odds") or {}).get("formattedOdds")
                        line = main_line(lines) if lines else None
                        if line is not None:
                            out[(player, stat)] = line
    return out


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

def match_existing(keys, key):
    """Find `key` among already-registered normalized names, allowing the same
    slack /odds allows across books: a shared last name plus one first name that
    prefixes the other. That is what joins "Cam Ward" to "Cameron Ward" and
    "Marquise Brown" to "Marquise Hollywood Brown" without collapsing the two
    Browns who are actually different men."""
    if key in keys:
        return key
    parts = key.split(" ")
    if len(parts) < 2:
        return None
    first, last = parts[0], parts[-1]
    for k in keys:
        kp = k.split(" ")
        if len(kp) < 2 or kp[-1] != last:
            continue
        if kp[0].startswith(first) or first.startswith(kp[0]):
            return k
    return None


def collect(by_book):
    """Fold the three book maps into one: key -> {stat: {book: line}}, plus the
    prettiest spelling seen for each key (the longest, so "Cameron Ward" wins
    over "Cam Ward" — it is the one a board row is more likely to also spell)."""
    players = {}
    display = {}
    for book in BOOKS:
        for (raw_name, stat), line in sorted(by_book.get(book, {}).items()):
            key = norm_name(raw_name)
            if not key:
                continue
            hit = match_existing(players.keys(), key)
            if hit is None:
                players[key] = {}
                display[key] = raw_name
                hit = key
            elif len(raw_name) > len(display[hit]):
                display[hit] = raw_name
            players[hit].setdefault(stat, {})[book] = line
    return players, display


def consensus(book_lines):
    """FMV for one market: the mean of whichever books priced it."""
    vals = [v for v in book_lines.values() if v is not None]
    return sum(vals) / len(vals) if vals else None


def build(players, display):
    lines = {}
    for key, stats in sorted(players.items()):
        parts, books = {}, set()
        for stat in STATS:
            if stat not in stats:
                continue
            fmv = consensus(stats[stat])
            if fmv is None:
                continue
            parts[stat] = round(fmv, 2)
            books.update(stats[stat].keys())

        yards = [parts[s] for s in YARD_STATS if s in parts]
        tds = [parts[s] for s in TD_STATS if s in parts]
        if not yards and not tds:
            continue

        # In BOOKS order, not alphabetical, so a tooltip lists them the way the
        # /odds columns do and the two pages read as one account of the market.
        entry = {"name": display[key],
                 "books": [b for b in BOOKS if b in books],
                 "parts": parts}
        # Rounded here, not at render: the board prints these verbatim, and a
        # sum of two half-point lines (4025.5 + 574.5) has no business showing a
        # precision the underlying markets don't have. Yards to the whole yard —
        # a tenth of a yard over a season is noise. TDs to a tenth, because the
        # lines themselves are half-points and a tenth is where two books
        # disagreeing (7.5 and 8.5 -> 8.0) still shows.
        if yards:
            entry["yards"] = round(sum(yards))
        if tds:
            entry["tds"] = round(sum(tds), 1)
        lines[key] = entry
    return lines


def verify(lines, by_book):
    ok = True
    for book in BOOKS:
        n = len(by_book.get(book, {}))
        print(f"  {book:>5}: {n:>3} markets parsed")
        if n == 0:
            print(f"ERROR: no markets parsed from {book} — its feed shape moved, "
                  f"or the snapshot is empty.", file=sys.stderr)
            ok = False

    if len(lines) < MIN_EXPECTED_PLAYERS:
        print(f"ERROR: only {len(lines)} players priced, expected at least "
              f"{MIN_EXPECTED_PLAYERS}. Refusing to overwrite good data.",
              file=sys.stderr)
        ok = False

    # A number that came out the wrong end of a unit conversion or a bad line
    # parse would be obvious here and invisible on the board, where one wrong row
    # in 860 reads as a player nobody likes.
    for key, e in lines.items():
        if "yards" in e and not (0 < e["yards"] < 7000):
            print(f"ERROR: implausible yards for {e['name']}: {e['yards']}", file=sys.stderr)
            ok = False
        if "tds" in e and not (0 < e["tds"] < 70):
            print(f"ERROR: implausible TDs for {e['name']}: {e['tds']}", file=sys.stderr)
            ok = False

    both = sum(1 for e in lines.values() if "yards" in e and "tds" in e)
    multi = sum(1 for e in lines.values() if len(e["parts"]) > 2)
    print(f"\n  {len(lines)} players priced — {both} with both numbers, "
          f"{multi} summed across more than one market")
    for key, e in sorted(lines.items(), key=lambda kv: -(kv[1].get("yards") or 0))[:5]:
        print(f"    {e['name']:<22} {e.get('yards', '—'):>6} yds  "
              f"{e.get('tds', '—'):>5} TD   [{', '.join(e['books'])}]")
    return ok


def main():
    print("Building consensus season prop lines from the committed book snapshots\n")

    by_book = {
        "fd": parse_fd(repo_path("data", "fd.json")),
        "dk": parse_dk(repo_path("data", "dk.json")),
        "score": parse_score(repo_path("data", "score")),
    }

    players, display = collect(by_book)
    lines = build(players, display)

    if not verify(lines, by_book):
        return 1

    out_path = repo_path("data", "nfl_prop_lines.json")
    with open(out_path, "w") as f:
        # Compact: this ships to every board load.
        json.dump({"lines": lines}, f, separators=(",", ":"))
    size_kb = os.path.getsize(out_path) / 1024
    print(f"\nWrote {len(lines)} players to {os.path.abspath(out_path)} ({size_kb:.0f} KB)")

    meta_path = repo_path("data", "nfl_prop_lines_meta.json")
    with open(meta_path, "w") as f:
        json.dump({
            "sources": ["data/fd.json", "data/dk.json", "data/score/*.json"],
            "books": list(BOOKS),
            "stats": list(STATS),
            "consensus": "mean of each book's main O/U line; yards and TDs each "
                         "summed across the player's priced markets",
            "player_count": len(lines),
            "markets_per_book": {b: len(by_book[b]) for b in BOOKS},
            "size_bytes": os.path.getsize(out_path),
            "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }, f, indent=2)
    print(f"Wrote {os.path.abspath(meta_path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
