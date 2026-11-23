#!/usr/bin/env python3
"""Where each open future stands right now, for the Action Ledger's Chances column.

    cache/an_picks.json ─────┐
    balldontlie (stats) ─────┤ build_futures_status.py ─> PUT /api/action-ledger ─> Supabase
    Action Network futures ──┘                                (slug ledger-status)

The ledger's Chances column is a number an admin types. This script supplies
what to type it against: for every pending future, one line of where the bet
stands ("144 rush yds through 5 GP; needs <455.5 more") and, where there is
one, a reference chance -- a live market price or a pace model. It never
writes a chance; ledger-chances is a separate slug and stays the admin's.

WHERE THE REFERENCE CHANCE COMES FROM

  Team and award markets (division, conference, Super Bowl, playoffs, MVP,
  OPOY, ...): Action Network's futures feed, which carries every book's live
  price. The consensus line's implied chance is the reference; DraftKings and
  FanDuel are listed beside it.

  Player season totals and win totals: a pace model, NOT the feed. Books stop
  moving those lines once the season starts, and the feed keeps serving the
  preseason number (Kenneth Walker o950.5 at -115 with 872 yards banked), so a
  price there would be worse than none. The model assumes the player keeps his
  per-game rate and plays every remaining team game -- "played 5 of 11" in the
  line is the cue that it is too generous for someone hurt. Yards are normal
  around the pace, TDs Poisson, win totals binomial on a win rate shrunk toward
  .500.

  Stat-leader markets ("Most Receiving Yards"): rank and gap to the leader.
  Those prices go stale the same way, so none is shown.

  Custom picks are free text, so each one is described in CUSTOM below.
  Anything not there gets the bet's text back as "no tracker" so it is obvious
  what to add.

ONLY OPEN BETS

A ticket gets a status only while it is still live: Action Network has it as
pending, it has no settle time, and its end date is still ahead. That last one
matters -- the export carries tickets from past seasons that were never graded
(a 2025 win total ending March 2026 still reads "pending"), and a status line
on one of those would be today's numbers on a bet about a season that is over.
api/action-ledger.py applies the same rule against the ledger when it stores
the set, so a bet graded since the last export is dropped there too.

USAGE

    python3 scripts/build_futures_status.py            build and print, write nothing
    python3 scripts/build_futures_status.py --push     PUT to /api/action-ledger
    python3 scripts/build_futures_status.py --seed     write straight to Supabase

Needs BALLDONTLIE_API_KEY (ALL-STAR or better, for /season_stats and
/standings). --push needs ADMIN_USER_ID; --seed needs SUPABASE_URL and
SUPABASE_KEY. All read .env. Run fetch_action_network.py first so the set of
open tickets is current.
"""

import argparse
import json
import math
import os
import re
import subprocess
import sys
import unicodedata
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import bdl_common as B  # noqa: E402

SOURCE = os.path.join(ROOT, "cache", "an_picks.json")
SLUG = "ledger-status"
INGEST_URL = os.environ.get("ACTION_LEDGER_URL",
                            "https://www.dynastz.com/api/action-ledger")
SEASON = 2026
GAMES = 17

AN_API = "https://api.actionnetwork.com/web/v1/leagues"
AN_LEAGUE = {"nfl": 1, "ncaaf": 2, "nba": 4, "ncaab": 6}
# Consensus first: it is the reference chance. The rest are listed by name.
AN_BOOKS = {15: "Cons", 68: "DK", 69: "FD", 75: "MGM", 123: "CZR"}
SHOWN_BOOKS = ("DK", "FD")
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/147.0.0.0 Safari/537.36")
# Action Network's option ids for an over/under leg. A team market's Yes is
# either an explicit Yes option or no option id at all.
OVER, UNDER = 170, 171


def load_env():
    path = os.path.join(ROOT, ".env")
    if not os.path.exists(path):
        return
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


# ---- stats -----------------------------------------------------------------

def norm(name):
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    return re.sub(r"[^a-z]", "", s)


class Stats:
    """balldontlie's season totals and standings, indexed for lookups by name."""

    def __init__(self):
        standings = list(B.paginate("/standings", {"season": SEASON}, mode="record", quiet=True))
        season = list(B.paginate("/season_stats", {"season": SEASON}, mode="record", quiet=True))
        active = {p["id"]: p for p in B.paginate("/players/active", {}, mode="record", quiet=True)}
        self.teams = {t["team"]["abbreviation"]: t for t in standings}
        self.by_name = {t["team"]["full_name"]: a for a, t in self.teams.items()}
        self.rows = []
        for r in season:
            if r.get("postseason"):
                continue
            p = r["player"]
            r["_name"] = f'{p["first_name"]} {p["last_name"]}'
            r["_key"] = norm(r["_name"])
            r["_team"] = ((active.get(p["id"]) or {}).get("team") or {}).get("abbreviation")
            r["_pos"] = p.get("position_abbreviation")
            self.rows.append(r)

    def team_games(self, abbr):
        t = self.teams.get(abbr)
        return t["wins"] + t["losses"] + t["ties"] if t else 0

    def find(self, name):
        """The best season row for a name: exact, then prefix, then first-
        three + last name, preferring whoever has played the most."""
        k = norm(name)
        hits = [r for r in self.rows if r["_key"] == k]
        if not hits:
            hits = [r for r in self.rows if r["_key"].startswith(k) or k.startswith(r["_key"])]
        if not hits and " " in name:
            first, last = norm(name.split()[0])[:3], norm(name.split()[-1])
            hits = [r for r in self.rows if r["_key"].startswith(first) and r["_key"].endswith(last)]
        return max(hits, key=lambda r: r["games_played"] or 0) if hits else None

    def ranked(self, field, where=lambda r: True):
        return sorted((r for r in self.rows if where(r)), key=lambda r: -v(r, field))


def v(r, field):
    if field == "touchdowns":
        return v(r, "rushing_touchdowns") + v(r, "receiving_touchdowns")
    return (r or {}).get(field) or 0


UNIT = {"passing_yards": "pass yds", "rushing_yards": "rush yds", "receiving_yards": "rec yds",
        "receiving_touchdowns": "rec TD", "rushing_touchdowns": "rush TD",
        "passing_touchdowns": "pass TD", "passing_interceptions": "INT", "touchdowns": "TD"}
# Per-game spread of each yardage stat, as a share of the player's own rate.
SPREAD = {"passing_yards": 0.30, "rushing_yards": 0.55, "receiving_yards": 0.65}


def ncdf(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def poisson_at_least(lam, k):
    if k <= 0:
        return 1.0
    return 1 - sum(math.exp(-lam) * lam ** i / math.factorial(i) for i in range(k))


def stat_total(st, name, field, side, line):
    r = st.find(name)
    if not r:
        return {"t": f"No {SEASON} stats found for {name}"}
    cur = v(r, field)
    gp = r["games_played"] or 0
    tg = st.team_games(r["_team"])
    left = GAMES - tg
    rate = cur / gp if gp else 0
    if field.endswith("touchdowns"):
        need = math.floor(line) + 1 - cur
        p_over = poisson_at_least(rate * left, need)
        need_txt = f"needs {need} more" if need > 0 else "cleared"
    else:
        need = line - cur
        sd = max(SPREAD[field] * rate, 15) * math.sqrt(left) if left else 1e-9
        p_over = 1 - ncdf((need - rate * left) / sd) if left else float(cur > line)
        need_txt = f"needs {need:,.1f} more ({need / left:.1f}/g)" if need > 0 and left else "cleared"
    if cur > line:
        p_over = 1.0
    played = f" of {tg}" if gp < tg - 1 else ""
    text = (f"{cur:,g} {UNIT[field]} through {gp}{played} GP ({r['_team']}), {rate:.1f}/g · "
            f"pace {cur + rate * left:,.0f} · ")
    if side == "o":
        text += "WON — over cleared" if cur > line else need_txt
    else:
        text += "LOST — over cleared" if cur > line else f"can add {line - cur:,.1f} at most"
    via = "settled" if cur > line else "pace model"
    return {"t": text, "c": round(100 * (p_over if side == "o" else 1 - p_over)), "via": via}


def win_total(st, team, side, line):
    abbr = st.by_name.get(team)
    if not abbr:
        return {"t": f"No standings for {team}"}
    t = st.teams[abbr]
    w, tie = t["wins"], t["ties"]
    gp = st.team_games(abbr)
    left = GAMES - gp
    rate = (w + 0.5 * tie + 3.5) / (gp + 7)
    need = math.ceil(math.floor(line) + 1 - w - 0.5 * tie)
    p_over = sum(math.comb(left, k) * rate ** k * (1 - rate) ** (left - k)
                 for k in range(max(need, 0), left + 1))
    if side == "o":
        text = f"{t['overall_record']}, {left} left · " + (
            "WON" if need <= 0 else f"needs {need} more wins")
    else:
        text = f"{t['overall_record']}, {left} left · " + (
            "LOST" if need <= 0 else f"can win {need - 1} more at most")
    via = "settled" if need <= 0 else "win-rate model"
    return {"t": text, "c": round(100 * (p_over if side == "o" else 1 - p_over)), "via": via}


def leader(st, name, field, where=lambda r: True, label=""):
    ranked = st.ranked(field, where)
    r = st.find(name)
    top = ", ".join(f"{x['_name']} {v(x, field):g}" for x in ranked[:3])
    if not r:
        return {"t": f"No stats for {name} · {label}top: {top}"}
    rank = next((i for i, x in enumerate(ranked, 1) if x is r), None)
    gap = v(ranked[0], field) - v(r, field)
    pos = f"#{rank}" if rank else "unranked"
    behind = "leads" if gap <= 0 else f"{gap:g} back"
    return {"t": f"{r['_name']} {v(r, field):g} {UNIT[field]} ({pos}, {behind}) · {label}top: {top}"}


def standings_line(st, abbrs):
    rows = sorted((st.teams[a] for a in abbrs), key=lambda t: (-t["wins"], t["losses"]))
    return ", ".join(f"{t['team']['abbreviation']} {t['overall_record']}" for t in rows)


def conference_top(st, conf):
    rows = sorted((t for t in st.teams.values() if t["team"]["conference"] == conf),
                  key=lambda t: t["playoff_seed"] or 99)[:3]
    return f"{conf} seeds: " + ", ".join(
        f"#{t['playoff_seed']} {t['team']['abbreviation']} {t['overall_record']}" for t in rows)


def division_of(st, abbr):
    t = st.teams[abbr]["team"]
    return [a for a, x in st.teams.items()
            if x["team"]["conference"] == t["conference"] and x["team"]["division"] == t["division"]]


def bottom(st):
    rows = sorted(st.teams.values(), key=lambda t: (t["wins"] + 0.5 * t["ties"], -t["losses"]))[:3]
    return "fewest wins: " + ", ".join(f"{t['team']['abbreviation']} {t['overall_record']}" for t in rows)


def qb_ppg(r):
    pts = (v(r, "passing_yards") * .04 + v(r, "passing_touchdowns") * 4
           - v(r, "passing_interceptions") * 2 + v(r, "rushing_yards") * .1
           + v(r, "rushing_touchdowns") * 6)
    return pts / max(r["games_played"] or 0, 1)


def defender(st, name):
    r = st.find(name)
    if not r:
        return f"No stats for {name}"
    bits = [f"{v(r, f):g} {u}" for f, u in (("total_tackles", "tkl"), ("defensive_sacks", "sk"),
                                            ("defensive_interceptions", "INT"),
                                            ("fumbles_forced", "FF")) if v(r, f)]
    return f"{r['_name']} ({r['_team']}, {r['games_played']} GP): " + ", ".join(bits)


# ---- markets ---------------------------------------------------------------

def fetch_market(league, kind):
    url = f"{AN_API}/{AN_LEAGUE[league]}/futures/{kind}?bookIds=" + ",".join(map(str, AN_BOOKS))
    out = subprocess.run(["curl", "-s", "--max-time", "30", "-A", USER_AGENT, url],
                         capture_output=True, text=True)
    try:
        data = json.loads(out.stdout)
    except ValueError:
        return None
    return data if "books" in data else None


def implied(money):
    return 100 / (money + 100) if money > 0 else -money / (-money + 100)


def fmt(money):
    return f"{money:+d}"


def priced(prices):
    ref = prices.get("Cons") or next(iter(prices.values()))
    shown = [f"{b} {fmt(prices[b])}" for b in SHOWN_BOOKS if b in prices] or \
        [f"{b} {fmt(m)}" for b, m in prices.items()]
    return {"c": round(100 * implied(ref)), "via": ", ".join(shown)}


def market_price(market, player_id=None, team_id=None, no=False):
    """{book: money} for one side of a team or award market."""
    names = {k: (o.get("option_type") or "").lower()
             for k, o in (market.get("rules") or {}).get("options", {}).items()}
    prices = {}
    for b in market["books"]:
        book = AN_BOOKS.get(b["book_id"])
        if not book:
            continue
        for o in b["odds"]:
            if player_id is not None and o.get("player_id") != player_id:
                continue
            if player_id is None and o.get("team_id") != team_id:
                continue
            option = names.get(str(o.get("option_type_id")), "")
            if (option == "no") != no:
                continue
            prices.setdefault(book, []).append(o["money"])
    # A book can list one side more than once, and the extras are junk (FanDuel
    # had the 4-6 Texans at +1500 and +165 for the AFC South). Keep, per book,
    # the price nearest the median of every book's prices.
    every = sorted(implied(m) for ms in prices.values() for m in ms)
    if not every:
        return {}
    mid = every[len(every) // 2]
    return {b: min(ms, key=lambda m: abs(implied(m) - mid)) for b, ms in prices.items()}


def award(markets, kind, name):
    for key, market in markets.items():
        if market and kind in key:
            ids = [p["id"] for p in market.get("players") or []
                   if norm(p["full_name"]) == norm(name)]
            prices = market_price(market, player_id=ids[0]) if ids else {}
            if prices:
                return priced(prices)
    return {}


# ---- custom picks ----------------------------------------------------------
#
# Action Network's custom picks are free text, so each needs telling what it is
# about. Keyed by the ticket's description, which is what the ledger shows.
# Each entry is a function of (stats, markets) returning the same
# {"t", "c", "via"} the market rows do.

def team_td(name, team):
    def f(st, _):
        r = st.find(name)
        top = ", ".join(f"{x['_name']} {v(x, 'touchdowns'):g}"
                        for x in st.ranked("touchdowns", lambda x: x["_team"] == team)[:3])
        mine = f"{r['_name']} {v(r, 'touchdowns'):g} TD ({r['_team'] or 'no team'}, {r['games_played']} GP)" \
            if r else f"{name}: no stats"
        return {"t": f"{mine} · {team} top: {top}"}
    return f


def ranked_in(name, field, teams=None, pos=None, label=""):
    def f(st, _):
        where = lambda r: (teams is None or r["_team"] in teams) and (pos is None or r["_pos"] == pos)
        return leader(st, name, field, where, label)
    return f


def award_of(kind, name, line=None):
    def f(st, markets):
        out = award(markets, kind, name)
        return {"t": line(st) if line else "", **out} if out else \
            {"t": (line(st) + " · " if line else "") + "off the board", "c": 0, "via": "no market"}
    return f


def record(abbr, note=""):
    return lambda st, _: {"t": f"{abbr} {st.teams[abbr]['overall_record']}" + (f" · {note}" if note else "")}


def division(abbr, note):
    return lambda st, _: {"t": f"{note} · " + standings_line(st, division_of(st, abbr))}


def fewest(abbr):
    return lambda st, _: {"t": f"{abbr} {st.teams[abbr]['overall_record']} · " + bottom(st)}


def ppg_vs(a, b, min_games):
    def f(st, _):
        ra, rb = st.find(a), st.find(b)
        short = lambda r: f" (under the {min_games}-game min)" if r["games_played"] < min_games else ""
        return {"t": f"{ra['_name']} {qb_ppg(ra):.1f} ppg in {ra['games_played']} GP{short(ra)} vs "
                     f"{rb['_name']} {qb_ppg(rb):.1f} in {rb['games_played']} GP{short(rb)}"}
    return f


def note(text, chance=None):
    return lambda st, _: {"t": text, **({"c": chance, "via": "settled"} if chance is not None else {})}


NFC_SOUTH = ("ATL", "CAR", "NO", "TB")
AFC_SOUTH = ("HOU", "IND", "JAX", "TEN")
CUSTOM = {
    "Caleb Downs DROY": award_of("defensive_rookie", "Caleb Downs", lambda st: defender(st, "Caleb Downs")),
    "Jahmyr Gibbs OPOY": award_of("offensive_player", "Jahmyr Gibbs"),
    "Ladd McConkey OPOY": award_of("offensive_player", "Ladd McConkey"),
    "Justin Herbert MVP": award_of("_mvp", "Justin Herbert"),
    "Joe Burrow MVP": award_of("_mvp", "Joe Burrow"),
    "CHI+DET 1+2 in NFC North": division("CHI", "need CHI & DET 1-2"),
    "Eagles/Cowboys 1-2 NFC East": division("PHI", "need PHI & DAL 1-2"),
    "Bucs/Saints 1-2 NFC South": division("TB", "need TB & NO 1-2"),
    "ATL 4th in NFC South": division("ATL", "need ATL 4th"),
    "DEN/LAC: 1-2 exacta": division("DEN", "need DEN 1st, LAC 2nd"),
    "Falcons: fewest wins": fewest("ATL"),
    "WSH fewest wins": fewest("WSH"),
    "Jets fewest wins": fewest("NYJ"),
    "M. Willis: most rush yards (QB)": ranked_in("Malik Willis", "rushing_yards", pos="QB", label="QB "),
    "LaPorta: Most TDs be a TE": ranked_in("Sam LaPorta", "receiving_touchdowns", pos="TE", label="TE "),
    "Olave: most rec TDs NFC South": ranked_in("Chris Olave", "receiving_touchdowns", NFC_SOUTH, label="NFC South "),
    "Nico: most rec TDs AFC South": ranked_in("Nico Collins", "receiving_touchdowns", AFC_SOUTH, label="AFC South "),
    "Etienne: most rush TDs in NFC South": ranked_in("Travis Etienne", "rushing_touchdowns", NFC_SOUTH, label="NFC South "),
    "Najee: most NYG TDs": team_td("Najee Harris", "NYG"),
    "Chig: most WSH TDs": team_td("Chig Okonkwo", "WSH"),
    "Jetta: most MIN TDs": team_td("Justin Jefferson", "MIN"),
    "Bell: most MIA TDs": team_td("Chris Bell", "MIA"),
    "Willis: most MIA TDs": team_td("Malik Willis", "MIA"),
    "Vidal: most LAC TDs": team_td("Kimani Vidal", "LAC"),
    "Tucker: most TB TDs": team_td("Sean Tucker", "TB"),
    "Pittman: most PIT TDs": team_td("Michael Pittman", "PIT"),
    "Nico: most HOU TDs": team_td("Nico Collins", "HOU"),
    "Allgeier: most ARI TDs": team_td("Tyler Allgeier", "ARI"),
    "B. Allen: Most NYJ TDs": team_td("Braelon Allen", "NYJ"),
    "Kyler higher PPG than Willis (min 8 games)": ppg_vs("Kyler Murray", "Malik Willis", 8),
    "K. Hamilton: All Pro": lambda st, _: {"t": defender(st, "Kyle Hamilton") + " · no All-Pro market"},
    "C. Humphrey: All Pro": record("KC", "Creed Humphrey (C) · no OL stats or All-Pro market"),
    "COY: Schottenheimer": record("DAL"),
    "COY: Steichen": record("IND"),
    "COY: Bowles": record("TB"),
    "ACOY: Graham": record("LV", "Patrick Graham (DC) · no ACOY market"),
    "ACOY: Sheppard": record("DET", "Kelvin Sheppard (DC) · no ACOY market"),
    "ACOY: Adams": note("No ACOY market"),
    "ACOY: Kuhr": note("Zak Kuhr (DC) · no ACOY market"),
    "ACOY: Caley": note("Nick Caley (OC) · no ACOY market"),
    "#1 overall pick - Leavitt": note("2027 draft · no market"),
}
CUSTOM_STAT = {"rush yds": "rushing_yards", "rec yds": "receiving_yards", "rec TDs": "receiving_touchdowns"}

TOTALS = {"Total Passing Yards": "passing_yards", "Total Receiving Yards": "receiving_yards",
          "Total Receiving TDs": "receiving_touchdowns", "Total Rushing Yards": "rushing_yards",
          "Total Rushing TDs": "rushing_touchdowns"}
LEADERS = {"Most Passing Yards": "passing_yards", "Most Passing TDs": "passing_touchdowns",
           "Most Receiving Yards": "receiving_yards", "Most Receiving TDs": "receiving_touchdowns",
           "Most Rushing Yards": "rushing_yards", "Most Rushing TDs": "rushing_touchdowns",
           "Most Interceptions Thrown": "passing_interceptions"}
OU_RE = re.compile(r"^(.+?) ([ou])([\d.]+)$")


# ---- one ticket ------------------------------------------------------------

def status_of(p, st, markets):
    raw = p["raw"]
    name = raw.get("custom_pick_name") or ""
    desc = p["description"]
    nfl = p["league"] == "nfl"

    if nfl and name.endswith("Total Wins"):
        m = OU_RE.match(desc)
        return win_total(st, m.group(1), m.group(2), float(m.group(3)))
    for k, field in TOTALS.items():
        if nfl and name.endswith(k):
            m = OU_RE.match(desc)
            return stat_total(st, m.group(1), field, m.group(2), float(m.group(3)))
    for k, field in LEADERS.items():
        if nfl and name.endswith(k):
            return leader(st, desc, field)
    if nfl and name.endswith("#1 Seed"):
        abbr = st.by_name.get(desc)
        return {"t": conference_top(st, st.teams[abbr]["team"]["conference"])} if abbr else {"t": desc}
    if name == "Custom Picks":
        m = re.match(r"^(.+?) ([ou])([\d.]+) (rush yds|rec yds|rec TDs)$", desc)
        if m:
            return stat_total(st, m.group(1), CUSTOM_STAT[m.group(4)], m.group(2), float(m.group(3)))
        fn = CUSTOM.get(desc)
        return fn(st, markets) if fn else {"t": "No tracker -- add it to CUSTOM in build_futures_status.py"}

    market = markets.get(p["pick_type"])
    if not market:
        return {"t": "No live market"}
    player = raw.get("player_id")
    prices = market_price(market, player_id=player, team_id=None if player else raw.get("side_id"),
                          no=desc.endswith(" No"))
    out = priced(prices) if prices else {"c": 0, "via": "off the board"}
    text = ""
    if nfl and not player:
        team = re.sub(r" (Yes|No)$", "", desc)
        abbr = st.by_name.get(team)
        if abbr:
            text = f"{abbr} {st.teams[abbr]['overall_record']}"
    return {"t": text or ("Off the board" if not prices else ""), **out}


def is_open(p, now):
    """Pending, unsettled, and not yet past its end -- see ONLY OPEN BETS."""
    ends = p["raw"].get("ends_at")
    return (p.get("result") == "pending" and not p.get("settled_at")
            and (not ends or ends > now))


def build(picks, st):
    markets = {}
    for p in picks:
        kind = p.get("pick_type") or ""
        if "futures_special" in kind and kind not in markets and p["league"] in AN_LEAGUE:
            markets[kind] = fetch_market(p["league"], kind)
    bets = {}
    for p in picks:
        try:
            s = status_of(p, st, markets)
        except Exception as e:  # noqa: BLE001 -- one bad row is not the whole set
            s = {"t": f"Could not work this one out: {e}"}
        bets[str(p["id"])] = {k: val for k, val in s.items() if val not in (None, "")}
    return bets


def push(body, user_id):
    req = urllib.request.Request(INGEST_URL, data=json.dumps(body).encode(), method="PUT")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-User-Id", user_id)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read() or b"{}")


def ledger_open_ids(url, key, now):
    """What api/action-ledger.py's open_ids() keeps, for --seed, which goes
    around it: ids the ledger has as pending and not past their end."""
    req = urllib.request.Request(f"{url}/rest/v1/action_pages?slug=eq.ledger&select=data")
    req.add_header("apikey", key)
    req.add_header("Authorization", f"Bearer {key}")
    with urllib.request.urlopen(req) as resp:
        rows = json.loads(resp.read() or b"[]")
    ledger = (rows[0]["data"] if rows else None) or {}
    return {str(r["id"]) for r in ledger.get("rows", [])
            if r.get("r") == "pending" and (not r.get("en") or r["en"] > now)}


def seed(status, url, key, now):
    live = ledger_open_ids(url, key, now)
    status = {**status, "bets": {k: s for k, s in status["bets"].items() if k in live}}
    row = {"slug": SLUG, "data": status, "etag": status["as_of"], "updated_at": "now()"}
    req = urllib.request.Request(f"{url}/rest/v1/action_pages?on_conflict=slug",
                                 data=json.dumps([row]).encode(), method="POST")
    req.add_header("apikey", key)
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Prefer", "resolution=merge-duplicates,return=minimal")
    with urllib.request.urlopen(req) as resp:
        resp.read()


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--push", action="store_true", help="PUT to /api/action-ledger")
    parser.add_argument("--seed", action="store_true", help="write straight to Supabase")
    args = parser.parse_args()
    load_env()

    if not os.path.exists(SOURCE):
        print(f"{SOURCE} not found -- run scripts/fetch_action_network.py first.", file=sys.stderr)
        return 1
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    pending = json.load(open(SOURCE))["futures"]["pending"]
    picks = [p for p in pending if is_open(p, now)]
    skipped = [p["description"] for p in pending if not is_open(p, now)]
    if skipped:
        print(f"Skipping {len(skipped)} not open (graded, or past its end): " + "; ".join(skipped))
    bets = build(picks, Stats())
    status = {"as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"), "bets": bets}

    by_desc = {str(p["id"]): p["description"] for p in picks}
    for tid, s in bets.items():
        ref = f"{s['c']}% ({s['via']})" if "c" in s else "—"
        print(f"{by_desc[tid][:40]:<40}  {ref:<28}  {s.get('t', '')}")
    missing = [by_desc[t] for t, s in bets.items() if s.get("t", "").startswith("No tracker")]
    print(f"\n{len(bets)} open futures, {sum('c' in s for s in bets.values())} with a reference chance")
    if missing:
        print("No tracker for: " + "; ".join(missing))

    if args.seed:
        url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
        if not url or not key:
            print("--seed needs SUPABASE_URL and SUPABASE_KEY", file=sys.stderr)
            return 1
        seed(status, url, key, now)
        print(f"Seeded action_pages/{SLUG}")
    if args.push:
        user_id = os.environ.get("ADMIN_USER_ID")
        if not user_id:
            print("--push needs ADMIN_USER_ID", file=sys.stderr)
            return 1
        print(f"Pushed to {INGEST_URL}: {push({'status': status}, user_id)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
