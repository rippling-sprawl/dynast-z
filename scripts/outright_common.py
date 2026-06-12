#!/usr/bin/env python3
"""
Shared helpers for the outright / award / futures parsers (DK, SCORE, FD).

All three books feed ONE merged file, data/outrights.json, so a candidate's
price from each book lines up in a single row. The merge rule mirrors the
player-prop pipeline: union by (canonical market, candidate key); a fresh
capture only ever updates *its own book's* name + price for a candidate and
never deletes other books' fields, other candidates, or other markets.

Candidate keys:
  - teams  -> a canonical NFL abbreviation. Every team's nickname (the last
    word) is unique across all 32 clubs, so "BUF Bills" (DK), "Buffalo Bills"
    (FD) and "LA Rams" (SCORE) all collapse by nickname; SCORE's participant
    abbreviation is used directly when present.
  - players/coaches -> norm_name(): lowercased, punctuation/suffix stripped.
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(ROOT, "data", "outrights.json")

# Mirror of the Recorder's blocklist (keep in sync with odds-recorder.js): drop
# analytics hosts at parse time too — exact, dot-subdomain, or hyphen sibling
# (browser-intake-datadoghq.com joins with a hyphen, not a dot).
BLOCK = ["datadoghq.com", "launchdarkly.com"]


def host_of(url):
    try:
        return url.split("/")[2].lower()
    except Exception:
        return ""


def blocked(url):
    h = host_of(url)
    return any(h == d or h.endswith("." + d) or h.endswith("-" + d) for d in BLOCK)


# ---------------------------------------------------------------------------
# Teams: canonical abbreviation, full name, and the nickname used to match.
# ---------------------------------------------------------------------------
TEAMS = [
    ("ARI", "Arizona Cardinals", "cardinals"),
    ("ATL", "Atlanta Falcons", "falcons"),
    ("BAL", "Baltimore Ravens", "ravens"),
    ("BUF", "Buffalo Bills", "bills"),
    ("CAR", "Carolina Panthers", "panthers"),
    ("CHI", "Chicago Bears", "bears"),
    ("CIN", "Cincinnati Bengals", "bengals"),
    ("CLE", "Cleveland Browns", "browns"),
    ("DAL", "Dallas Cowboys", "cowboys"),
    ("DEN", "Denver Broncos", "broncos"),
    ("DET", "Detroit Lions", "lions"),
    ("GB", "Green Bay Packers", "packers"),
    ("HOU", "Houston Texans", "texans"),
    ("IND", "Indianapolis Colts", "colts"),
    ("JAX", "Jacksonville Jaguars", "jaguars"),
    ("KC", "Kansas City Chiefs", "chiefs"),
    ("LV", "Las Vegas Raiders", "raiders"),
    ("LAC", "Los Angeles Chargers", "chargers"),
    ("LAR", "Los Angeles Rams", "rams"),
    ("MIA", "Miami Dolphins", "dolphins"),
    ("MIN", "Minnesota Vikings", "vikings"),
    ("NE", "New England Patriots", "patriots"),
    ("NO", "New Orleans Saints", "saints"),
    ("NYG", "New York Giants", "giants"),
    ("NYJ", "New York Jets", "jets"),
    ("PHI", "Philadelphia Eagles", "eagles"),
    ("PIT", "Pittsburgh Steelers", "steelers"),
    ("SF", "San Francisco 49ers", "49ers"),
    ("SEA", "Seattle Seahawks", "seahawks"),
    ("TB", "Tampa Bay Buccaneers", "buccaneers"),
    ("TEN", "Tennessee Titans", "titans"),
    ("WAS", "Washington Commanders", "commanders"),
]
_NICK_TO_ABBR = {nick: abbr for abbr, _full, nick in TEAMS}
_ABBR_SET = {abbr for abbr, _full, _nick in TEAMS}
FULL_NAME = {abbr: full for abbr, full, _nick in TEAMS}
# A few abbreviation aliases books use that differ from our canonical key.
_ABBR_ALIAS = {"JAC": "JAX", "WSH": "WAS", "LA": "LAR", "SFO": "SF", "TAM": "TB",
               "GBP": "GB", "KAN": "KC", "NOR": "NO", "NWE": "NE"}


def team_key(name, abbr=None):
    """Canonical NFL abbreviation for a team string, or None if not a team."""
    if abbr:
        a = abbr.strip().upper()
        a = _ABBR_ALIAS.get(a, a)
        if a in _ABBR_SET:
            return a
    if not name:
        return None
    toks = name.strip().lower().split()
    # Match by nickname anywhere in the string (last word for "BUF Bills",
    # "Buffalo Bills"; handles "49ers" since digits are preserved here).
    for t in reversed(toks):
        if t in _NICK_TO_ABBR:
            return _NICK_TO_ABBR[t]
    return None


# ---------------------------------------------------------------------------
# Player / coach name normalization (the candidate key for non-team markets).
# ---------------------------------------------------------------------------
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def norm_name(name):
    """Lowercase, drop punctuation and a trailing Jr/Sr/III suffix."""
    s = (name or "").lower()
    s = s.replace(".", "")
    s = "".join(ch if (ch.isalpha() or ch.isspace()) else " " for ch in s)
    toks = [t for t in s.split() if t]
    if len(toks) > 1 and toks[-1] in _SUFFIXES:
        toks = toks[:-1]
    return " ".join(toks)


# ---------------------------------------------------------------------------
# Odds normalization -> a clean American string ("+550" / "-130").
# ---------------------------------------------------------------------------
def norm_american(value):
    """Accept DK's unicode-minus string, FD's signed int, or SCORE's string."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        n = int(value)
        return "+" + str(n) if n > 0 else str(n)
    s = str(value).strip().replace("−", "-")  # unicode minus -> ASCII
    if s.lower() == "even":
        return "+100"
    if s and s[0] not in "+-" and s.lstrip("-").isdigit():
        return "+" + s
    return s


# ---------------------------------------------------------------------------
# Canonical market registry — the single source of truth for a market's
# display title, candidate kind, and UI group. Every book maps its own market
# name onto one of these keys; the title/kind/group come from here so the three
# parsers can never disagree. group order in the UI: awards, futures, leaders.
# ---------------------------------------------------------------------------
CANON = {
    # Season awards (single winner; candidates are players/coaches)
    "mvp":    ("Most Valuable Player",            "player", "awards"),
    "opoy":   ("Offensive Player of the Year",    "player", "awards"),
    "dpoy":   ("Defensive Player of the Year",    "player", "awards"),
    "oroy":   ("Offensive Rookie of the Year",    "player", "awards"),
    "droy":   ("Defensive Rookie of the Year",    "player", "awards"),
    "coy":    ("Coach of the Year",               "player", "awards"),
    "cpoy":   ("Comeback Player of the Year",     "player", "awards"),
    # Team futures
    "super_bowl_winner": ("Super Bowl Winner",    "team", "futures"),
    "afc_winner": ("AFC Champion",                "team", "futures"),
    "nfc_winner": ("NFC Champion",                "team", "futures"),
    "afc_east_winner":  ("AFC East Winner",       "team", "futures"),
    "afc_north_winner": ("AFC North Winner",      "team", "futures"),
    "afc_south_winner": ("AFC South Winner",      "team", "futures"),
    "afc_west_winner":  ("AFC West Winner",       "team", "futures"),
    "nfc_east_winner":  ("NFC East Winner",       "team", "futures"),
    "nfc_north_winner": ("NFC North Winner",      "team", "futures"),
    "nfc_south_winner": ("NFC South Winner",      "team", "futures"),
    "nfc_west_winner":  ("NFC West Winner",       "team", "futures"),
    "make_playoffs": ("To Make Playoffs",         "team", "futures"),
    "miss_playoffs": ("To Miss Playoffs",         "team", "futures"),
    "afc_1_seed": ("AFC No. 1 Seed",              "team", "futures"),
    "nfc_1_seed": ("NFC No. 1 Seed",              "team", "futures"),
    # Statistical leaders
    "most_wins":            ("Most Regular Season Wins",            "team",   "leaders"),
    "most_passing_yards":   ("Most Regular Season Passing Yards",   "player", "leaders"),
    "most_rushing_yards":   ("Most Regular Season Rushing Yards",   "player", "leaders"),
    "most_receiving_yards": ("Most Regular Season Receiving Yards", "player", "leaders"),
    "most_rookie_receiving_yards": ("Most Rookie Receiving Yards",  "player", "leaders"),
}


# ---------------------------------------------------------------------------
# Merge into data/outrights.json (single shared file, never clobber).
# ---------------------------------------------------------------------------
def load_outrights():
    if os.path.exists(OUT_PATH):
        try:
            return json.load(open(OUT_PATH))
        except Exception:
            pass
    return {"markets": {}, "milestones": {}}


def sort_doc(doc):
    # Keep candidates sorted best-price-first so the file is stable to diff and
    # the renderer needs no sort. Implied prob: higher = shorter (better) price.
    # Pure (mutates and returns doc, no I/O) so the serverless ingest endpoint
    # can reuse it before persisting to its store.
    for mkt in doc.get("markets", {}).values():
        mkt["candidates"].sort(key=_cand_sort_key)
    for ms in doc.get("milestones", {}).values():
        for th in ms.get("thresholds", {}).values():
            th["candidates"].sort(key=_cand_sort_key)
    return doc


def save_outrights(doc):
    sort_doc(doc)
    with open(OUT_PATH, "w") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)


def american_to_prob(american):
    """Implied probability (with vig) from an American odds string."""
    try:
        n = int(str(american).replace("−", "-"))
    except Exception:
        return None
    if n == 0:
        return None
    return (-n) / (-n + 100.0) if n < 0 else 100.0 / (n + 100.0)


def _best_prob(prices):
    probs = [american_to_prob(v) for v in prices.values() if v]
    probs = [p for p in probs if p is not None]
    return max(probs) if probs else -1.0


def _cand_sort_key(c):
    # Shortest (best) price first; ties broken by display name.
    return (-_best_prob(c.get("prices", {})), _disp(c))


def _disp(c):
    names = c.get("names", {})
    return names.get("fd") or names.get("score") or names.get("dk") or ""


def upsert_market(doc, key, book, candidates):
    """
    candidates: list of (cand_key, display_name, american). Upserts this book's
    name + price per candidate into doc["markets"][key], preserving every other
    book's fields and any candidates this capture didn't include. Title/kind/
    group come from the CANON registry so all books stay consistent.
    """
    title, kind, group = CANON[key]
    mkt = doc["markets"].setdefault(
        key, {"title": title, "kind": kind, "group": group, "candidates": []})
    mkt["title"], mkt["kind"], mkt["group"] = title, kind, group
    by_key = {c["key"]: c for c in mkt["candidates"]}
    for cand_key, disp, american in candidates:
        if not cand_key:
            continue
        c = by_key.get(cand_key)
        if c is None:
            c = {"key": cand_key, "names": {}, "prices": {}}
            mkt["candidates"].append(c)
            by_key[cand_key] = c
        c["names"][book] = disp
        c["prices"][book] = american      # fresh capture wins this book's cell


def upsert_milestone(doc, stat, title, threshold, book, candidates):
    """Like upsert_market but into the milestones tree, keyed stat -> threshold."""
    ms = doc["milestones"].setdefault(
        stat, {"title": title, "thresholds": {}})
    ms["title"] = title
    th = ms["thresholds"].setdefault(str(threshold), {"candidates": []})
    by_key = {c["key"]: c for c in th["candidates"]}
    for cand_key, disp, american in candidates:
        if not cand_key:
            continue
        c = by_key.get(cand_key)
        if c is None:
            c = {"key": cand_key, "names": {}, "prices": {}}
            th["candidates"].append(c)
            by_key[cand_key] = c
        c["names"][book] = disp
        c["prices"][book] = american
