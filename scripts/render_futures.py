#!/usr/bin/env python3
"""Render the open betting book from cache/an_picks.json as a set of pages.

Reads the export written by fetch_action_network.py and writes one page per
slate under views/football/, plus the same set as plain files in cache/action/:

  /football/action                 the index -- every slate as a cell in a
                                   grid, with the ungraded tickets beneath it
  /football/action/futures         NFL FUTURES: the pending futures grouped
                                   conference -> division -> club, with the
                                   league-wide markets and the season-futures
                                   parlays lifted out into their own section
  /football/action/week/1 ... /18  one page per week of the schedule, holding
                                   that week's parlays and its singles by game
  /football/action/preseason       the off-calendar slates, each of which
  /football/action/postseason      exists only while something is on it
  /football/action/other

THE SECOND BOARD, AND WHY A PARLAY IS NOT A LIST

A four-leg parlay is one wager. Rendered as four rows it reads as four wagers at
four prices and the +406 it actually pays goes missing, so its legs are strung
on a rail instead: one line runs through a node on every leg and stops at the
first and the last, the combined price sits alone at the head of the card, and
the foot says in words that all of them have to land. There is deliberately no
per-leg stake column, because there is no per-leg stake.

Singles are filed by the game they are bets on rather than by club, since that
is the grouping that puts six Barkley rushing tickets and the Eagles spread on
one card. Both boards share every token and component; the second one is slate
where the first is red/blue/brass, because on this page colour says which board
you are reading and AFC/NFC/NFL are spoken for.

WHY THE SECOND BOARD IS FILED BY WEEK

The two boards are the two things a bet can be on: a season, or a week of it.
So the first holds every ticket whose subject is the whole season -- the futures
singles and any parlay built entirely out of futures legs -- and the second
holds the game book, split into the weeks it plays in. Sunday's parlay and the
six props on the same slate are one week's exposure and now read as one block,
where being split by ticket shape meant carrying a date in your head to line the
two lists up.

The week itself is not in the payload -- Action Network records a kickoff and
nothing more -- so it comes from data/nfl_schedule_{season}.json, the committed
ESPN pull, by asking which week's window the kickoff falls in. Ids cannot do it:
ESPN's game ids and Action Network's are unrelated numbers. Bets the calendar
cannot place -- another league, a preseason or a playoff game -- get a named
block of their own rather than being forced into a week they are not in.

WHAT COUNTS AS STILL PENDING

`result == "pending"` is Action Network's own field and it is not enough: a
parlay with a lost leg is decided whatever the field says, and the book leaves
finished tickets ungraded for years. A ticket is live here only if its event
has not ended and no leg has already lost. The rest are still shown -- muted,
in an "Ungraded" block, out of every total -- because dropping them silently
would shrink the book on screen without saying so.

WHY THE PAGE INLINES ITS IMAGES

The output is meant to be published as an Artifact, and those run under a strict
CSP that blocks every external host. A remote <img src> to static.sprtactn.co
would silently render as a broken icon, so each distinct logo/headshot is
fetched once, downscaled, and embedded as a data: URI. Downloads are cached in
cache/an_images/ so re-runs are offline and instant.

HOW A PICK GETS ATTRIBUTED TO A TEAM

Only two sources are trusted, because a wrong team is worse than no team:

  1. `side_id` -- Action Network's own team id, authoritative, covers the picks
     placed through their market UI.
  2. An explicit team token in the description ("ATL 4th in NFC South", "Jets
     fewest wins") for hand-typed free-form picks, matched against TEAM_TOKENS.

Player nicknames are deliberately NOT resolved against data/fp.json. That was
tried and it returns confidently wrong answers -- "Kyler" matches a Kyler on
Minnesota rather than Kyler Murray, "Monty" and "Willis" likewise. Anything not
covered by the two rules above lands in an "Other" block rather than being
guessed into a club.

WHAT DOES NOT BELONG TO A CLUB AT ALL

A season-long award or stat-leader ticket is drawn from a field of every player
in the league, so filing it under whichever club the pick happens to play for is
a category error -- it buries a league-wide market inside one of thirty-two
cards and splits the field across them. Those markets are lifted out into an
"NFL" section alongside AFC and NFC, split into "Stat Leaders" and "Awards", and
grouped there by the market itself so the whole field reads as one block. The
picks that match no club go in the same section under "Other".

A pick naming two teams in one division ("Bears/Lions 1-2 NFC North") is a bet on
the division, not on either club, so it renders at the division level rather than
being arbitrarily filed under the first team named.

USAGE

    python3 scripts/render_futures.py
    python3 scripts/render_futures.py --open     # also open the offline index
"""

import argparse
import base64
import hashlib
import io
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
    EASTERN, TZ_LABEL = ZoneInfo("America/New_York"), "ET"
except Exception:                                   # no tzdata on the host
    EASTERN, TZ_LABEL = timezone.utc, "UTC"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "cache", "an_picks.json")
# The book is a folder of pages, not a page: views/football/action.html is the
# index and action-<slug>.html each slate. OUT_DIR is the same set as plain
# files, which open off the filesystem and publish as an Artifact.
VIEW_DIR = os.path.join(ROOT, "views", "football")
OUT_DIR = os.path.join(ROOT, "cache", "action")
IMG_CACHE = os.path.join(ROOT, "cache", "an_images")
IMG_PX = 72

# The league calendar the game bets are filed by. One file per season, written
# by scripts/fetch_nfl_schedule.py off ESPN and committed.
SEASON = 2026
SCHEDULE = os.path.join(ROOT, "data", f"nfl_schedule_{SEASON}.json")

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/147.0.0.0 Safari/537.36")

# Action Network's NFL team ids, read off /web/v1/scoreboard/nfl. Stable, and the
# only authoritative link between a pick and a club.
TEAMS = {
    125: ("BUF", "Buffalo Bills"),      126: ("MIA", "Miami Dolphins"),
    127: ("NYJ", "New York Jets"),      128: ("CIN", "Cincinnati Bengals"),
    129: ("NE", "New England Patriots"), 130: ("CLE", "Cleveland Browns"),
    131: ("BAL", "Baltimore Ravens"),   132: ("PIT", "Pittsburgh Steelers"),
    133: ("IND", "Indianapolis Colts"), 134: ("JAC", "Jacksonville Jaguars"),
    135: ("TEN", "Tennessee Titans"),   136: ("DEN", "Denver Broncos"),
    137: ("HOU", "Houston Texans"),     139: ("KC", "Kansas City Chiefs"),
    140: ("DAL", "Dallas Cowboys"),     142: ("PHI", "Philadelphia Eagles"),
    143: ("CHI", "Chicago Bears"),      144: ("NYG", "New York Giants"),
    145: ("WAS", "Washington Commanders"), 146: ("DET", "Detroit Lions"),
    147: ("GB", "Green Bay Packers"),   148: ("MIN", "Minnesota Vikings"),
    149: ("TB", "Tampa Bay Buccaneers"), 150: ("CAR", "Carolina Panthers"),
    151: ("ATL", "Atlanta Falcons"),    152: ("NO", "New Orleans Saints"),
    153: ("ARI", "Arizona Cardinals"),  154: ("SF", "San Francisco 49ers"),
    156: ("SEA", "Seattle Seahawks"),   251: ("LA", "Los Angeles Rams"),
    1325: ("LAC", "Los Angeles Chargers"), 2045: ("LV", "Las Vegas Raiders"),
}

# Team marks, read off /web/v1/scoreboard/nfl. Hardcoded rather than derived
# from the abbreviation because Action Network still serves several teams off
# their legacy slug -- the Chargers are sd.png, and the Jets, Browns, Rams and
# Commanders are one-off uploads under assets.actionnetwork.com.
LOGOS = {
    "ARI": "https://static.sprtactn.co/teamlogos/nfl/100/ari.png",
    "ATL": "https://static.sprtactn.co/teamlogos/nfl/100/atl.png",
    "BAL": "https://static.sprtactn.co/teamlogos/nfl/100/bal.png",
    "BUF": "https://static.sprtactn.co/teamlogos/nfl/100/buf.png",
    "CAR": "https://static.sprtactn.co/teamlogos/nfl/100/car.png",
    "CHI": "https://assets.actionnetwork.com/598430_bears1.png",
    "CIN": "https://static.sprtactn.co/teamlogos/nfl/100/cin.png",
    "CLE": "https://assets.actionnetwork.com/519602_browns.png",
    "DAL": "https://static.sprtactn.co/teamlogos/nfl/100/dal.png",
    "DEN": "https://static.sprtactn.co/teamlogos/nfl/100/den.png",
    "DET": "https://static.sprtactn.co/teamlogos/nfl/100/det.png",
    "GB": "https://static.sprtactn.co/teamlogos/nfl/100/gb.png",
    "HOU": "https://static.sprtactn.co/teamlogos/nfl/100/hou.png",
    "IND": "https://static.sprtactn.co/teamlogos/nfl/100/ind.png",
    "JAC": "https://static.sprtactn.co/teamlogos/nfl/100/jac.png",
    "KC": "https://static.sprtactn.co/teamlogos/nfl/100/kc.png",
    "LA": "https://assets.actionnetwork.com/524632_rams.png",
    "LAC": "https://static.sprtactn.co/teamlogos/nfl/100/sd.png",
    "LV": "https://static.sprtactn.co/teamlogos/nfl/100/oak.png",
    "MIA": "https://static.sprtactn.co/teamlogos/nfl/100/mia.png",
    "MIN": "https://static.sprtactn.co/teamlogos/nfl/100/min.png",
    "NE": "https://static.sprtactn.co/teamlogos/nfl/100/ne.png",
    "NO": "https://static.sprtactn.co/teamlogos/nfl/100/no.png",
    "NYG": "https://static.sprtactn.co/teamlogos/nfl/100/nygd.png",
    "NYJ": "https://assets.actionnetwork.com/372790_jets.png",
    "PHI": "https://static.sprtactn.co/teamlogos/nfl/100/phi.png",
    "PIT": "https://static.sprtactn.co/teamlogos/nfl/100/pit.png",
    "SEA": "https://static.sprtactn.co/teamlogos/nfl/100/sea.png",
    "SF": "https://static.sprtactn.co/teamlogos/nfl/100/sf.png",
    "TB": "https://static.sprtactn.co/teamlogos/nfl/100/tb.png",
    "TEN": "https://assets.actionnetwork.com/683711_titans.png",
    "WAS": "https://assets.actionnetwork.com/698864_Commanders.png",
}


STRUCTURE = {
    "AFC": {
        "East": ["BUF", "MIA", "NE", "NYJ"],
        "North": ["BAL", "CIN", "CLE", "PIT"],
        "South": ["HOU", "IND", "JAC", "TEN"],
        "West": ["DEN", "KC", "LAC", "LV"],
    },
    "NFC": {
        "East": ["DAL", "NYG", "PHI", "WAS"],
        "North": ["CHI", "DET", "GB", "MIN"],
        "South": ["ATL", "CAR", "NO", "TB"],
        "West": ["ARI", "LA", "SEA", "SF"],
    },
}

CONF_OF = {abbr: conf for conf, divs in STRUCTURE.items()
           for teams in divs.values() for abbr in teams}
DIV_OF = {abbr: div for conf, divs in STRUCTURE.items()
          for div, teams in divs.items() for abbr in teams}

# What a club can be called in a hand-typed description. Nicknames are matched
# without regard to case, because "Bears" and "bears" are both the club and
# neither is anything else.
TEAM_NAMES = {
    "FALCONS": "ATL", "COMMANDERS": "WAS", "JETS": "NYJ", "EAGLES": "PHI",
    "COWBOYS": "DAL", "BUCS": "TB", "BUCCANEERS": "TB", "SAINTS": "NO",
    "BEARS": "CHI", "LIONS": "DET", "PACKERS": "GB", "VIKINGS": "MIN",
    "GIANTS": "NYG", "RAMS": "LA", "49ERS": "SF", "NINERS": "SF",
    "SEAHAWKS": "SEA", "CARDINALS": "ARI", "PANTHERS": "CAR", "BILLS": "BUF",
    "DOLPHINS": "MIA", "PATRIOTS": "NE", "RAVENS": "BAL", "BENGALS": "CIN",
    "BROWNS": "CLE", "STEELERS": "PIT", "TEXANS": "HOU", "COLTS": "IND",
    "JAGUARS": "JAC", "JAGS": "JAC", "TITANS": "TEN", "BRONCOS": "DEN",
    "CHIEFS": "KC", "CHARGERS": "LAC", "RAIDERS": "LV",
}

# Team codes, matched ONLY as written -- in capitals. Half of them are also
# ordinary English words, and a case-blind table quietly files "(min 8 games)"
# under Minnesota, "fewest wins, no vig" under New Orleans and "ten legs" under
# Tennessee. A code is a club when it is written as a code; anywhere else it is
# just a word. Word boundaries are enforced at match time on top of that, so
# "NE" cannot fire inside "NFC".
TEAM_CODES = {abbr: abbr for abbr in DIV_OF}
TEAM_CODES.update({"WSH": "WAS", "JAX": "JAC", "LAR": "LA", "STL": "LA",
                   "OAK": "LV", "SD": "LAC", "NOR": "NO", "TAM": "TB",
                   "KAN": "KC", "GNB": "GB", "SFO": "SF", "NWE": "NE",
                   "NYA": "NYJ"})

# A division named outright. It files a ticket only when no club is named in
# the same line: "ATL 4th in NFC South" is a bet on the Falcons and says so,
# while "Etienne: most rush TDs in NFC South" is a bet on a field of one
# division and has nothing else to be filed under.
DIVISION_RE = re.compile(r"\b(AFC|NFC)\s+(East|North|South|West)\b", re.I)


def division_in_text(text):
    """The division a description names outright, or None."""
    found = DIVISION_RE.search(text or "")
    if not found:
        return None
    return found.group(1).upper(), found.group(2).title()


# A race typed by hand rather than entered in a market: "Most rush yards thru
# week 3: Bucky", "#1 overall pick - Leavitt". The book has no market record
# for these, so the line has to be read as one: what is being raced for on the
# left of the separator, who was backed in it on the right. Only openers that
# can only be a market are accepted -- a line that opens with a name ("Olave:
# most rec TDs NFC South") is not one of these and must not be split.
HAND_MARKET_RE = re.compile(
    r"^(?P<market>(?:most|fewest|highest|lowest|first|last|#\d+)\b[^:]*?)"
    r"\s*(?::|\s-\s)\s*(?P<field>[^:]+?)\s*$", re.I)


def hand_market(text):
    """(market, who was backed) for a hand-typed race, else None."""
    found = HAND_MARKET_RE.match((text or "").strip())
    return (found.group("market"), found.group("field")) if found else None


# Action Network stamps league, season and direction onto every market name --
# "2026 NFL Regular Season - Most Interceptions Thrown", "2026 NFL AFC West -
# To Win". Every ticket on this board is a 2026 NFL outright, so all three say
# the same thing on all 136 rows while eating the width of the one column that
# has to hold a real sentence. The season is optional in the prefix because
# only in-season markets carry it; awards and seeds go straight from the league
# to the market name.
SEASON_RE = re.compile(r"^2026 NFL (?:Regular Season - )?")
TOWIN_RE = re.compile(r"\s+-\s+To Win$", re.I)


def market_of(pick):
    """The market a ticket was entered in, per meta.description. May be "".

    This is the only record of what a non-over/under ticket actually bets:
    `play` holds nothing but a name."""
    meta = pick["raw"].get("meta") or {}
    market = (meta.get("description") or "").strip()
    return TOWIN_RE.sub("", SEASON_RE.sub("", market))


def teams_in_text(text):
    """Every club named in a free-form description, in order of appearance."""
    found = []
    for token in re.findall(r"[A-Za-z0-9']+", text or ""):
        abbr = TEAM_CODES.get(token) or TEAM_NAMES.get(token.upper())
        if abbr and abbr not in found:
            found.append(abbr)
    return found


# Markets whose field is the whole league rather than one roster. Matched on
# the market name because that is the only place the distinction is recorded:
# "Most Receiving Yards" is a race, "Total Receiving Yards" is a player prop,
# and nothing else in the payload tells them apart.
LEADER_RE = re.compile(r"^Most\b")
AWARD_RE = re.compile(r"\b(?:MVP|of the Year)$")


def bucket_of(market):
    """Which board a league-wide market is read on.

    'Other' is where a market that is neither a race nor an award lands -- the
    draft's first pick, say -- rather than being dropped back among the
    unfilable tickets, which is a different thing and reads as one."""
    if LEADER_RE.match(market):
        return "Stat Leaders"
    if AWARD_RE.search(market):
        return "Awards"
    return "Other"


def league_bucket(pick):
    """'Stat Leaders', 'Awards', or None if the ticket belongs to a club."""
    market = market_of(pick)
    if not market:
        return None
    bucket = bucket_of(market)
    return bucket if bucket != "Other" else None


def attribute(pick):
    """(scope, key) where scope is 'league', 'team', 'division' or 'other'.

    Read most specific first. A club named outright beats the division it plays
    in, a division named outright beats the league, and a hand-typed race is
    the last thing tried, because a line that names nobody at all is the only
    line a race can be read out of without stepping on a ticket that has a
    subject of its own.
    """
    bucket = league_bucket(pick)
    if bucket:
        return "league", (bucket, market_of(pick))

    side = pick["raw"].get("side_id")
    if side in TEAMS:
        return "team", TEAMS[side][0]

    desc = pick.get("description")
    named = teams_in_text(desc)
    if len(named) == 1:
        return "team", named[0]
    if len(named) > 1:
        divisions = {(CONF_OF[a], DIV_OF[a]) for a in named}
        # Two clubs from one division is a bet on that division's order.
        if len(divisions) == 1:
            return "division", divisions.pop()
        return "team", named[0]

    division = division_in_text(desc)
    if division:
        return "division", division

    race = hand_market(desc)
    if race:
        return "league", (bucket_of(race[0]), race[0])
    return "other", None


# ---- images ---------------------------------------------------------------

def data_uri(url):
    """Download once, downscale, return a data: URI. Empty string on failure."""
    if not url:
        return ""
    os.makedirs(IMG_CACHE, exist_ok=True)
    key = hashlib.sha1(url.encode()).hexdigest()[:16]
    cached = os.path.join(IMG_CACHE, f"{key}.png")

    if not os.path.exists(cached):
        result = subprocess.run(
            ["curl", "-sL", "--max-time", "30", "-A", USER_AGENT, url],
            capture_output=True)
        if result.returncode != 0 or not result.stdout:
            return ""
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(result.stdout)).convert("RGBA")
            img.thumbnail((IMG_PX, IMG_PX), Image.LANCZOS)
            img.save(cached, "PNG", optimize=True)
        except Exception:
            return ""

    with open(cached, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode()


# ---- formatting -----------------------------------------------------------

def fmt_odds(odds, ratio=True):
    """American odds, except that four-figure longshots read as a ratio.

    "+15000" is six glyphs of noise in a narrow column and nobody parses it as
    a price; "150:1" is the same number said the way the payout is spoken.
    `ratio` is off for a ticket price, which is the headline number of its card
    and is quoted the way the book quotes it."""
    try:
        n = int(odds)
    except (TypeError, ValueError):
        return "--"
    if ratio and n >= 10000:
        return f"{n / 100:g}:1"
    return f"+{n}" if n > 0 else str(n)


def fmt_units(units):
    try:
        u = float(units)
    except (TypeError, ValueError):
        return "--"
    return f"{u:.2f}"


def unit_str(n):
    """Units, said with the u that names what the number is.

    The board is denominated in units end to end, because a unit is the size of
    the bet to the person who placed it and a dollar is only what the book
    happened to charge for it that week."""
    return f"{n:,.2f}u"


def esc(text):
    return (str(text or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


# ---- html -----------------------------------------------------------------

CSS = """
/* Scoped to .fb so the board cannot leak into the site header, nav drawer or
   hub cards, which keep their own theme tokens from styles/base/theme.css.

   The board is deliberately light-only: it is a printed-ticket board, and the
   odds/units columns were tuned for dark ink on paper. It therefore does NOT
   follow the site's dark toggle -- every value below is a fixed light token
   rather than a var() that flips. */
.fb{
  --ground:#EDEFF2; --surface:#FFFFFF; --sunk:#F5F7F9;
  /* Header shades, darkest first: division encloses club encloses picks, and
     the picks sit on --surface. Reading the greys top to bottom tells you how
     deep in the board you are without a single extra rule or label. */
  --head-div:#D3DAE2; --head-team:#E3E8EE;
  --ink:#11161C; --muted:#5C6773; --line:#D8DDE3;
  --afc:#C8102E; --nfc:#21437E; --brass:#8A6520;
  /* Slate heads the second board; win/loss ink the result nodes on a leg. */
  --slate:#39434F; --win:#1E7A46; --loss:#B4232B; --rail:#B8C1CB;
  --shadow:0 1px 2px rgba(17,22,28,.06),0 8px 20px -12px rgba(17,22,28,.18);
  background:var(--ground); color:var(--ink);
  font-family:"Helvetica Neue",Helvetica,Arial,sans-serif;
  font-size:17.81px; line-height:1.5; -webkit-font-smoothing:antialiased;
  border:1px solid var(--line); border-radius:14px;
  /* Three boxes nest between the viewport and the table -- .masters-content,
     this, and the .ledger card -- so the gutter is the one thing charged
     three times over. It scales with the width rather than stepping at a
     breakpoint: ~7px a side on a 390px phone, the drawn 22px past 850px. */
  padding:clamp(14px,3.2vw,26px) clamp(6px,1.85vw,22px) clamp(20px,4vw,34px);
  margin-top:18px;
}
.fb *{box-sizing:border-box}
/* styles/base/styles.css styles bare tags globally -- `header` is flex+sticky
   for the site chrome, and h2..h5 carry hub sizing. Neutralise all of that
   inside the board so its own rules below are what actually apply. */
.fb div,.fb section,.fb ul,.fb li{display:block;position:static}
.fb h3,.fb h4,.fb h5{display:block;margin:0;font-family:inherit;
  color:inherit;border:0;padding:0}
.fb ul{list-style:none}

/* Helvetica Neue throughout. The scoreboard voice comes from weight, caps and
   tracking rather than from a second family. */
.fb .condensed{font-weight:700;text-transform:uppercase;letter-spacing:.09em}
.fb .num{font-variant-numeric:tabular-nums;
  font-feature-settings:"tnum" 1;letter-spacing:.01em}

.fb .mast{border-bottom:2px solid var(--ink);padding-bottom:16px;margin-bottom:20px}
.fb .eyebrow{font-size:13.06px;color:var(--muted)}
.fb .mast h3{font-size:clamp(30.88px,4.75vw,45.12px);line-height:1.04;margin:6px 0 0;
  font-weight:700;letter-spacing:-.01em;text-transform:uppercase;text-wrap:balance}
.fb .asof{font-size:14.84px;color:var(--muted);margin-top:7px}

/* Three readings of one book, so they are three rows of one table: the label
   on the left, the number in a column of its own so the three of them rule up,
   and what the number is made of trailing it in the muted voice. */
.fb table.totals{width:100%;border-collapse:collapse;margin-bottom:28px;
  background:var(--surface);border:1px solid var(--line);border-radius:10px}
.fb .totals th,.fb .totals td{padding:10px 15px;text-align:left;
  border-bottom:1px solid var(--line)}
.fb .totals tr:last-child th,.fb .totals tr:last-child td{border-bottom:0}
.fb .totals th{font-size:12.47px;color:var(--muted);font-weight:700;
  white-space:nowrap;width:1%}
.fb .totals .v{font-size:27.31px;font-weight:600;letter-spacing:-.01em;
  text-align:right;white-space:nowrap;width:1%}
.fb .totals .s{font-size:13.66px;color:var(--muted)}
@media (max-width:560px){
  .fb .totals th,.fb .totals td{padding:8px 10px}
  .fb .totals .v{font-size:21px}
  .fb .totals .s{font-size:12px}}

.fb .conf{margin-top:34px}
/* The conference accent fills the bar rather than tinting the type, which puts
   the strongest value on the board at its top level and leaves the greys below
   to carry division/club/pick depth on their own. */
.fb .conf-head{display:flex;align-items:baseline;gap:4px 12px;flex-wrap:wrap;
  background:var(--c);color:#FFFFFF;border-radius:10px;
  padding:11px 16px;margin-bottom:15px}
.fb .conf-head h4{font-size:28.5px;margin:0;color:#FFFFFF;letter-spacing:.07em;
  font-weight:700;text-transform:uppercase}
.fb .conf-head .meta{font-size:14.84px;color:#FFFFFF;margin-left:auto}

/* min() rather than a bare 340px: a bare track floor is a hard minimum, so on
   a 390px phone the 330px column box was overflowed by its own grid. */
.fb .divs{display:grid;gap:16px;align-items:start;
  grid-template-columns:repeat(auto-fit,minmax(min(425px,100%),1fr))}
@media (min-width:900px){.fb .divs{grid-template-columns:repeat(2,1fr)}}
.fb .div{background:var(--surface);border:1px solid var(--line);
  border-radius:12px;box-shadow:var(--shadow);overflow:hidden}
.fb .div-head{display:flex;align-items:baseline;gap:4px 8px;flex-wrap:wrap;
  padding:clamp(8px,2.1vw,11px) clamp(9px,2.5vw,14px);background:var(--head-div);
  border-bottom:1px solid var(--line)}
.fb .div-head h5{font-size:clamp(12.75px,2.85vw,16.03px);margin:0;
  letter-spacing:.11em;font-weight:700;text-transform:uppercase}

.fb .team{border-bottom:1px solid var(--line)}
.fb .team:last-child{border-bottom:0}
.fb .team-head{display:flex;align-items:center;gap:4px 10px;flex-wrap:wrap;
  padding:9px 14px;background:var(--head-team);
  border-bottom:1px solid var(--line)}
.fb .team-head img{width:27.5px;height:27.5px;object-fit:contain;flex:none}
.fb .team-head .nm{font-size:14.84px;letter-spacing:.06em;font-weight:600;
  text-transform:uppercase}
/* The club header used to carry that club's stake. It said the same thing 27
   times in 27 places and could not be compared across any two of them, so the
   money moved out into one ledger and the header kept only the name. */
.fb .team-head .colhead{margin-left:auto}

.fb .picks{list-style:none;margin:0;padding:6px 14px 10px}
.fb .picks>.pick:first-child{border-top:0}
.fb .pick,.fb .subj{display:flex;align-items:center;gap:10px}
.fb .pick{padding:6px 0;border-top:1px dashed var(--line)}
.fb .pick img,.fb .subj img{width:32.5px;height:32.5px;object-fit:contain;
  border-radius:50%;background:var(--sunk);flex:none}
.fb .pick .ph,.fb .subj .ph{width:32.5px;height:32.5px;border-radius:50%;
  background:var(--sunk);flex:none;display:grid;place-items:center;
  font-size:10.69px;color:var(--muted)}
.fb .pick .d,.fb .cols .d{flex:1;min-width:0;font-size:16.03px;
  overflow-wrap:anywhere}

/* A subject owns its headshot and its name; the tickets beneath it carry only
   what differs between them, indented to the width of the mark they share. */
.fb .subj{padding:10px 0 4px;border-top:1px solid var(--line)}
.fb .subj:first-child{border-top:0}
.fb .subj .nm{font-size:14.25px;font-weight:700;letter-spacing:.06em}
.fb .subj+.pick{border-top:0}
.fb .pick.sub{padding-left:36px}

/* Units and odds are fixed-width so every ticket on the board rules up into
   two columns, whatever the length of the line to its left. */
.fb .col{flex:none;font-size:14.25px;text-align:right}
.fb .col.u{width:68px}
.fb .col.odds{width:68px}
.fb .pick .col.odds{padding:2px 7px;color:var(--brass)}

/* The columns are named in the card's own header, so the list underneath is
   nothing but tickets. .colhead pairs them at the same width and gap the rows
   use, and both headers pad to 14px like .picks, so the two rule up. The odds
   cell repeats the row's own 7px padding so the label sits over the prices
   rather than over the column's outer edge. */
.fb .colhead{display:flex;flex:none;gap:10px;margin-left:6px}
.fb .div-head .colhead{margin-left:auto}
.fb .colhead .col{font-size:10.69px;color:var(--muted);font-weight:700;
  text-transform:uppercase;letter-spacing:.08em}
.fb .colhead .col.odds{padding:2px 7px}

/* The club ledger. A real table rather than the .picks flex rows used
   everywhere else, because this is the one place on the board where numbers
   have to rule up into columns that can be read against each other -- which is
   the whole reason the money left the club headers.

   EVERY SIZE IN HERE SCALES. The board was drawn at one width and every rule
   under it was a fixed px, so a 390px phone was handed a desktop table and
   paid for it in sideways scroll. The sizes are clamp(floor, vw, ceiling)
   now: the ceiling is the drawing this was tuned at, the floor is what still
   reads on the narrowest phone, and the vw between them means there is no
   width at which the table is suddenly wrong. What the narrow board gives up
   it gives up on purpose -- see --hrow, .lb and the pick indents below. */
.fb .ledger{
  /* The head is two stacked sticky rows, so the second has to know exactly how
     tall the first is. One token holds it, because the `height` floor on the
     cell and the `top` offset on the row beneath must never disagree. */
  --hrow:38px;
  background:var(--surface);border:1px solid var(--line);
  border-radius:12px;box-shadow:var(--shadow);margin-bottom:28px;
  /* clip rather than hidden: hidden would make this a scroll container and a
     sticky table head cannot escape one. */
  overflow:clip}
.fb .ledger .div-head{align-items:baseline}
.fb .ledger .meta{font-size:clamp(11px,2.2vw,13.06px);color:var(--muted);
  margin-left:auto;text-align:right}
/* No scroll container at any width, deliberately. The table used to get one
   below 760px, which is exactly the width at which the head stopped sticking:
   a sticky cell sticks to its scrollport, and an overflow-x:auto wrapper IS
   one, so the phone got a head that scrolled away while the desktop kept it.
   The columns are sized to fit a 390px viewport instead -- there is nothing
   left to scroll sideways, so nothing has to scroll sideways. */
.fb .ledger .scroll{overflow-x:visible}
.fb .ledger table{width:100%;border-collapse:collapse;
  font-size:clamp(11.5px,2.55vw,15.44px)}
.fb .ledger th,.fb .ledger td{padding:5px clamp(4px,1.35vw,12px);
  text-align:right;border-bottom:1px solid var(--line)}
/* Thirty-two clubs, any of them able to open onto its tickets: the table is
   taller than the screen, and four money columns are unreadable without the
   two rows that name them, so the head stays put. `height` on a cell is a
   floor, so the rows hold --hrow at every width. */
.fb .ledger thead th{background:var(--head-team);font-weight:700;
  font-size:clamp(8.75px,1.95vw,11.28px);text-transform:uppercase;
  letter-spacing:.08em;color:var(--muted);white-space:nowrap;
  padding-top:6px;padding-bottom:6px;
  position:sticky;z-index:3;height:var(--hrow);
  /* The head's rules are drawn inside the cell rather than on its edge.
     Under border-collapse a border belongs to the table, not to the cell, so
     a stuck head left its own borders behind with the rows and the lines it
     was ruled with went see-through as the board scrolled under it. An inset
     shadow is painted by the cell and travels with it. */
  border-bottom:0;box-shadow:inset 0 -1px 0 var(--line)}
.fb .ledger thead tr:first-child th{top:var(--stick,0px)}
.fb .ledger thead tr+tr th{top:calc(var(--stick,0px) + var(--hrow))}
/* The rule opening each pair is what makes "team" and "player" read as two
   blocks of two rather than as four unrelated money columns. */
.fb .ledger thead th.g{border-left:0;
  box-shadow:inset 1px 0 0 var(--line),inset 0 -1px 0 var(--line)}
/* Team, Team markets and Player markets are the three groups the head names,
   so all three are set the same: the size and the full-strength ink that says
   this row is the head of a group, not a label inside one. */
.fb .ledger thead tr:first-child th{color:var(--ink);
  font-size:clamp(9.25px,2.1vw,12.47px)}
.fb .ledger thead tr:first-child th.g{text-align:center}
.fb .ledger th.g,.fb .ledger td.g{border-left:1px solid var(--line)}
.fb .ledger th.c,.fb .ledger td.c{text-align:left;font-weight:600}
.fb .ledger td.c{font-size:clamp(11.5px,2.5vw,14.84px);letter-spacing:.02em;
  overflow-wrap:anywhere}
.fb .ledger td.c img{width:25px;height:25px;object-fit:contain;
  vertical-align:-5px;margin-right:9px}
/* Fixed on the wide board, where 130px is comfort rather than need: the four
   money columns rule up with room around them however many clubs are open.
   Below 840px it stops being comfort and starts costing the club column the
   width its names live in, so it is handed back -- see the two media queries
   at the foot of this block. */
.fb .ledger td.n{width:130px;white-space:nowrap}
/* Teams with nothing on them stay in the table -- the list of what is not bet
   is worth as much as the list of what is -- but they are greyed so the eye
   runs down the live rows without having to read the dashes. */
.fb .ledger tr.zero td{color:var(--muted)}
.fb .ledger tr.zero td.c img{filter:grayscale(1);opacity:.42}
.fb .ledger td.zip{color:var(--muted)}
.fb .ledger tfoot td{background:var(--head-div);font-weight:700;
  border-bottom:0;padding-top:8px;padding-bottom:8px}

/* The conference band. It carries the same red and blue the AFC and NFC
   section bars used to wear, because those sections are now these rows: the
   board reads conference, division, club, tickets straight down one table
   instead of down a page and back up a grid of cards. */
.fb .ledger tr.band td{background:var(--c);border-bottom-color:var(--c);
  color:#FFFFFF;padding-top:9px;padding-bottom:9px}
.fb .ledger tr.band td.c{font-size:clamp(13.5px,3vw,17.81px);font-weight:700;
  letter-spacing:.1em;text-transform:uppercase}
.fb .ledger tr.band td.bmeta{font-size:clamp(10.5px,2.3vw,13.66px);
  letter-spacing:.03em;color:rgba(255,255,255,.86)}
.fb .ledger tbody.bd td{border-bottom:0}
.fb .ledger tr.dband td{background:var(--head-div);
  font-size:clamp(10px,2.1vw,12.47px);font-weight:700;letter-spacing:.11em;
  text-transform:uppercase}

/* A club row is a disclosure. Closed it is the money, open it is the tickets,
   and nothing at all is added to the cell to say so: the caret that used to
   sit there taught on the first press what the first press teaches anyway,
   and it charged the club column 19px for the lesson on the width that could
   least afford it. The cursor, the hover and the focus ring say it instead --
   and a row with nothing behind it gets none of the three. */
.fb .ledger tr.tm[aria-controls]{cursor:pointer}
.fb .ledger tr.tm[aria-controls]:hover td{background:var(--sunk)}
.fb .ledger tr.tm.on td{background:var(--head-team)}
.fb .ledger tr.tm:focus{outline:2px solid var(--brass);outline-offset:-2px}
.fb .ledger tr.tm.oth td.c{color:var(--muted);font-style:italic}
/* A club's tickets, closed until its row is opened. They are rows of the one
   table, so a ticket's units sit in the Risk column and its price in the To
   win column of the pair that counts it -- which is why neither carries a
   label of its own down here: the head two rows up already names them. */
.fb .ledger tbody.grp:not(.on) tr.pk{display:none}
.fb .ledger tr.pk td{background:var(--sunk);
  font-size:clamp(11.5px,2.5vw,14.84px);border-bottom:1px dashed var(--line)}
.fb .ledger tbody.grp tr:last-child td{border-bottom:1px solid var(--line)}
/* The indent has one job -- say these rows hang off the one above -- so it is
   the smallest step that still says it. It used to be a fixed 41px clearing a
   caret that is gone, which on a phone was a tenth of the whole board spent
   on white space. */
.fb .ledger tr.pk td.c{padding-left:clamp(11px,3.4vw,22px);font-weight:400;
  color:var(--ink)}
/* One step further in, so a run of tickets reads as hanging off one player
   rather than as five more rows. */
.fb .ledger tr.pk.sub td.c{padding-left:clamp(22px,7vw,55px)}
/* The price rides with the words, not in a column: an American odd is not a
   quantity that rules up against a column of money, and the two money columns
   are spoken for by what the head calls them. Italic and small so a row still
   reads as one line with a price on it rather than as two things. */
.fb .ledger .odds{margin-left:clamp(5px,1.5vw,11px);font-size:.82em;
  font-style:italic;color:var(--brass);white-space:nowrap}
.fb .ledger tr.bare td.c{font-weight:400}
.fb .ledger tr.pk td.c img,.fb .ledger tr.pk td.c .ph{
  width:clamp(20px,5.6vw,27.5px);height:clamp(20px,5.6vw,27.5px);
  border-radius:50%;background:var(--surface);object-fit:contain;
  vertical-align:middle;margin-right:clamp(5px,1.6vw,9px)}
.fb .ledger tr.pk td.c .ph{display:inline-grid;place-items:center;
  font-size:clamp(9px,1.9vw,10.69px);color:var(--muted)}
/* Middle rather than baseline: a row's text has to sit level with the money
   in the four cells beside it, not with the mark it shares its cell with. */
.fb .ledger tr.pk td.c .d,.fb .ledger tr.pk td.c .nm{vertical-align:middle}
.fb .ledger tr.pk.sj td{padding-top:8px}
.fb .ledger tr.pk.sj td.c{font-size:clamp(11px,2.3vw,13.66px);font-weight:700;
  letter-spacing:.06em}

/* Above the table, beside the count: the one control on the board. */
.fb .ledger .xall{font:inherit;font-size:clamp(9.75px,2vw,11.88px);
  font-weight:700;text-transform:uppercase;letter-spacing:.08em;
  color:var(--ink);background:var(--surface);border:1px solid var(--line);
  border-radius:7px;padding:5px clamp(7px,1.8vw,10px);margin-left:auto;
  cursor:pointer;white-space:nowrap}
.fb .ledger .xall:hover{border-color:var(--brass);color:var(--brass)}

/* ---- the narrow board ----

   Two steps down, and each gives the club column width the wide drawing had
   spent elsewhere.

   The first is the money. width:1% plus nowrap is "as narrow as the number in
   it": the browser gives each of these four its content width and hands the
   whole remainder to the one column that asked for nothing. Nothing moves
   about -- the widest figure in a money column is the season total in the
   foot, which is there whether a club is open or shut -- so the columns still
   rule up; they just stop reserving room they were not using. 840px is where
   4x130px stops leaving "New England Patriots" a line to sit on. */
@media (max-width:840px){
  .fb .ledger td.n,.fb .ledger th.n{width:1%}
  .fb .ledger td.n{font-size:clamp(10.75px,2.4vw,15.44px)}
}

/* The second is the club name itself, and the row it sits in. Below 620px the
   name goes and the mark it sat beside grows to carry the row alone, the head
   loses 8px of its two stuck rows, and every row tightens. Between the two
   steps the table fits a 390px viewport with room to spare -- which is what
   lets the head stay sticky here rather than sitting in a sideways scroller
   the way it used to. */
@media (max-width:620px){
  .fb .ledger{--hrow:30px}
  .fb .ledger th,.fb .ledger td{padding-top:4px;padding-bottom:4px}
  /* Off the screen, not out of the row. A club row whose only visible content
     is a logo with an empty alt would otherwise reach a screen reader as four
     numbers belonging to nobody, so the name is clipped rather than dropped.
     Scoped to `img+.lb`: a market row -- "Awards", "Division markets" -- has
     no mark to be named by, and keeps its words. */
  .fb .ledger tr.tm td.c img+.lb{position:absolute;width:1px;height:1px;
    padding:0;margin:0;overflow:hidden;clip-path:inset(50%);white-space:nowrap}
  .fb .ledger tr.tm td.c img{width:34px;height:34px;vertical-align:-11px;
    margin-right:0}
  .fb .ledger tr.tm td{padding-top:3px;padding-bottom:3px}
  .fb .ledger tr.band td{padding-top:7px;padding-bottom:7px}
}

.fb .note{margin-top:30px;padding:15px 17px;background:var(--surface);
  border:1px solid var(--line);border-left:4px solid var(--brass);
  border-radius:10px;font-size:clamp(13px,2.7vw,16.03px);color:var(--muted)}
.fb .note strong{color:var(--ink)}
.fb .note ul{margin:8px 0 0;padding-left:18px}

/* ---- pending non-futures board -------------------------------------------

   The second board on the page. It reuses every token above and the .conf /
   .div / .picks components wholesale, and adds only what a ticket with legs
   needs. Its section bars are slate rather than red/blue/brass: on this page
   colour says which board you are reading, and AFC/NFC/NFL are spoken for. */
.fb .sect{border-top:2px solid var(--ink);margin-top:52px;padding-top:22px;
  margin-bottom:20px}
.fb .sect h3{font-size:clamp(26.12px,3.8vw,35.62px);line-height:1.06;margin:6px 0 0;
  font-weight:700;letter-spacing:-.01em;text-transform:uppercase}

/* A parlay is ONE bet whose legs must all land, so the legs are drawn strung
   on a rail rather than stacked as a list. Without the rail four legs read as
   four separate tickets priced at four separate odds, which is the single
   thing this card must never say. The rail runs edge to edge through every
   node and stops at the first and last one, so the eye sees a closed chain. */
.fb .tix{columns:3 412px;column-gap:16px}
.fb .tik{display:block;break-inside:avoid;margin:0 0 16px;
  background:var(--surface);border:1px solid var(--line);
  border-radius:12px;box-shadow:var(--shadow);overflow:hidden}
.fb .tik-head{display:flex;align-items:center;gap:4px 9px;flex-wrap:wrap;
  padding:10px 14px;background:var(--head-team);
  border-bottom:1px solid var(--line)}
.fb .tik-head .nm{font-size:14.84px;letter-spacing:.06em;font-weight:700;
  text-transform:uppercase}
/* Stake and return are one phrase off the title -- "1.00u to win 4.06u" --
   because risk and reward are only meaningful against each other. The two
   figures carry the weight; the words between them step back. */
.fb .tik-head .pays{font-size:13.66px;font-weight:600;color:var(--ink)}
.fb .tik-head .pays i{font-style:normal;font-weight:400;color:var(--muted)}
/* The combined price is the only number that belongs to the ticket rather than
   to a leg, so it is the one thing set large and in brass at the top right. */
.fb .tik-head .price{margin-left:auto;font-size:19px;font-weight:700;
  color:var(--brass);letter-spacing:-.01em}
.fb .tag{font-size:11.28px;font-weight:700;text-transform:uppercase;
  letter-spacing:.07em;color:var(--muted);background:var(--surface);
  border:1px solid var(--line);border-radius:999px;padding:2px 8px;
  white-space:nowrap}

.fb .legs{list-style:none;margin:0;padding:8px 14px 10px}
.fb .leg{position:relative;display:flex;align-items:center;gap:9px;
  padding:7px 0 7px 25px;min-height:40px}
.fb .leg::before{content:"";position:absolute;left:5px;top:0;bottom:0;
  width:2px;background:var(--rail)}
.fb .leg:first-child::before{top:50%}
.fb .leg:last-child::before{bottom:50%}
.fb .leg:only-child::before{display:none}
/* The node, centred on the rail. Its ring carries the leg's own result, so a
   part-settled ticket shows which links have already held. */
.fb .leg::after{content:"";position:absolute;left:0;top:50%;margin-top:-6px;
  width:15px;height:15px;border-radius:50%;background:var(--surface);
  border:2px solid var(--brass);box-sizing:border-box}
.fb .leg.win::after{background:var(--win);border-color:var(--win)}
.fb .leg.loss::after{background:var(--loss);border-color:var(--loss)}
.fb .leg.push::after{background:var(--muted);border-color:var(--muted)}
.fb .leg img{width:32.5px;height:32.5px;object-fit:contain;border-radius:50%;
  background:var(--sunk);flex:none}
.fb .leg .ph{width:32.5px;height:32.5px;border-radius:50%;background:var(--sunk);
  flex:none;display:grid;place-items:center;font-size:10.69px;color:var(--muted)}
.fb .leg .d{flex:1;min-width:0;font-size:15.44px;overflow-wrap:anywhere}
.fb .leg .d b{font-weight:700}
.fb .leg .mu{display:block;font-size:12.47px;color:var(--muted);
  letter-spacing:.03em}

/* Singles are filed by the game they are on, which is the only grouping that
   puts the six Barkley rushing tickets and the Eagles spread on one card. */
.fb .gms{columns:2 425px;column-gap:16px}
.fb .gm{break-inside:avoid;margin:0 0 16px;
  background:var(--surface);border:1px solid var(--line);
  border-radius:12px;box-shadow:var(--shadow);overflow:hidden}
.fb .gms .gm:last-child{margin-bottom:0}
.fb .gm-head{display:flex;align-items:baseline;gap:9px;padding:11px 14px;
  background:var(--head-div);border-bottom:1px solid var(--line);flex-wrap:wrap}
.fb .gm-head h5{font-size:16.03px;margin:0;letter-spacing:.09em;font-weight:700;
  text-transform:uppercase}
.fb .gm-head .when{font-size:12.47px;color:var(--muted);letter-spacing:.04em;
  text-transform:uppercase;font-weight:700}
.fb .gm-head .rk{font-size:13.66px;color:var(--muted);margin-left:auto}

/* Tickets whose event has finished but which the book never graded. They are
   not live and must not be totalled with what is, but dropping them silently
   would quietly shrink the book, so they get a muted card of their own. */
.fb .wide>.gm{margin:0}
.fb .dead{opacity:.62}
.fb .dead .pick .col.odds{color:var(--muted)}
.fb .dead .pick{flex-wrap:wrap}
.fb .dead .pick .when{font-size:13.06px;color:var(--muted);flex:none;width:103px}
@media (max-width:560px){.fb .dead .pick .d{flex-basis:100%;order:1}}
.fb .pick .d .tag{margin-right:7px;vertical-align:1px}

/* A block inside a section that is not a grid of cards -- the season-futures
   parlays under NFL, which are .tix and run full width rather than sitting in
   .div columns. Same head-div grey as a division header, because it is at the
   same depth in the board and the greys are what say so. */
.fb .subhead{display:flex;align-items:baseline;gap:4px 10px;flex-wrap:wrap;
  padding:10px 14px;margin:0 0 14px;background:var(--head-div);
  border:1px solid var(--line);border-radius:10px}
.fb .subhead h5{font-size:16.03px;letter-spacing:.11em;font-weight:700;
  text-transform:uppercase}
.fb .subhead .meta{font-size:13.66px;color:var(--muted);margin-left:auto}
.fb .divs+.subhead{margin-top:22px}

/* A week holds multis and game cards both. They are two separate column
   blocks, so they need between them the gap the cards inside them use. */
.fb .tix+.gms{margin-top:16px}
/* The days a week's slate actually runs, said once in its bar rather than
   reconstructed from the kickoff line of every card underneath it. */
.fb .conf-head .span{font-size:14.84px;color:#FFFFFF;opacity:.78;
  letter-spacing:.03em}

/* ---- the strip and the grid ----------------------------------------------

   The book is nineteen pages and every one of them carries the strip, which is
   both the way across and the shape of the season: a week with nothing on it
   keeps its slot, greyed, so a hole in the book is visible from anywhere in
   it. Numbers rather than names, because "Week 11" nineteen times across is a
   paragraph and 1..18 is a ruler. */
.fb .pager{display:flex;flex-wrap:wrap;gap:5px;margin:0 0 26px}
.fb .pager a{display:block;min-width:36px;padding:5px 8px;text-align:center;
  font-size:13.66px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;
  color:var(--ink);background:var(--surface);border:1px solid var(--line);
  border-radius:7px;text-decoration:none;font-variant-numeric:tabular-nums}
.fb .pager a:hover{border-color:var(--brass);color:var(--brass)}
.fb .pager a.zero{color:var(--muted);background:transparent;border-style:dashed}
/* The page you are on is filled rather than outlined -- the one state that has
   to survive being read at a glance from the middle of a row of eighteen. */
.fb .pager a.on{background:var(--ink);border-color:var(--ink);color:#FFFFFF}
.fb .pager a.on:hover{color:#FFFFFF}
.fb .pager a.all,.fb .pager a.lead{letter-spacing:.08em}
.fb .pager a.lead:not(.on){border-color:var(--brass);color:var(--brass)}

/* One cell per slate. The cell is the whole link, and its foot is where a
   settled slate's profit will go -- which is why a pending one says so in
   words rather than leaving the line off, since a line that appears later
   moves every number above it when it does. */
.fb .grid{display:grid;gap:12px;align-items:start;
  grid-template-columns:repeat(auto-fill,minmax(min(268px,100%),1fr))}
.fb .cell{display:block;background:var(--surface);border:1px solid var(--line);
  border-radius:12px;box-shadow:var(--shadow);overflow:hidden;
  color:inherit;text-decoration:none}
.fb .cell:hover{border-color:var(--brass)}
.fb .cell-head{display:flex;align-items:baseline;gap:3px 8px;flex-wrap:wrap;
  padding:9px 13px;background:var(--head-team);
  border-bottom:1px solid var(--line)}
.fb .cell-head .nm{font-size:14.25px;letter-spacing:.08em;font-weight:700}
.fb .cell-head .when{font-size:11.88px;color:var(--muted);margin-left:auto;
  letter-spacing:.03em;white-space:nowrap}
.fb .cell-body{padding:11px 13px 13px}
.fb .cell .v{font-size:27.31px;font-weight:600;letter-spacing:-.01em;line-height:1}
.fb .cell .k{font-size:12.47px;color:var(--muted);margin-top:4px}
.fb .cell .exp{font-size:13.66px;margin-top:8px;color:var(--muted)}
.fb .cell-foot{padding:7px 13px;background:var(--sunk);
  border-top:1px solid var(--line);font-size:11.88px;color:var(--muted);
  letter-spacing:.07em}
/* A week with nothing on it stays in the grid -- the weeks not bet say as much
   about the book as the weeks that are -- but sunk and greyed, so the eye runs
   down the live cells without having to read the dashes. */
.fb .cell.zero{box-shadow:none;background:var(--sunk);border-style:dashed}
.fb .cell.zero .cell-head{background:transparent}
.fb .cell.zero .cell-foot{background:transparent}
.fb .cell.zero .nm,.fb .cell.zero .v{color:var(--muted)}
/* Futures is not a week. It leads the grid and takes the brass, which is the
   colour it already wears as a section on the board. */
.fb .cell.lead{grid-column:span 2}
.fb .cell.lead .cell-head{background:var(--brass);border-bottom-color:var(--brass)}
.fb .cell.lead .cell-head .nm,.fb .cell.lead .cell-head .when{color:#FFFFFF}
@media (max-width:520px){.fb .cell.lead{grid-column:span 1}}
"""


OU_RE = re.compile(r"^(.*\S)\s+([ou]\d+(?:\.\d+)?)$")
YESNO_RE = re.compile(r"^(.*\S)\s+(Yes|No)$")

# An over/under's market is what it counts: "Total Receiving Yards" -> "Rec
# Yards". The "Total" is what makes it an over/under and is already said by the
# o/u prefix on the line beside it, and the long participles are what push these
# labels past the width of a two-up division card. Every one of the 82 lines on
# the board resolves through this, so an unmapped market degrades to the market
# name rather than vanishing.
TOTAL_RE = re.compile(r"^Total\s+")
STAT_ABBR = ((re.compile(r"\bReceiving\b"), "Rec"),
             (re.compile(r"\bRushing\b"), "Rush"),
             (re.compile(r"\bPassing\b"), "Pass"))


def stat_of(pick):
    """The stat an over/under is counting, short enough to sit beside a line."""
    stat = TOTAL_RE.sub("", market_of(pick))
    for pattern, short in STAT_ABBR:
        stat = pattern.sub(short, stat)
    return stat


def split_pick(pick):
    """(subject, detail) -- what the ticket is on, and what it says about it.

    An over/under names its subject and its line in one string ("Nico Collins
    o1249.5") but never the stat, so the row pairs the line with the market it
    counts. Every other market stores only a name in `play` ("Sam Darnold") and
    the whole of what was bet lives in `meta.description`.

    A hand-typed pick has neither shape -- no line to split off and no market
    record -- so it gets no subject and renders as a plain row.
    """
    desc = (pick.get("description") or "").strip()
    line = OU_RE.match(desc)
    if line:
        return line.group(1), f"{stat_of(pick)} {line.group(2)}".strip()

    market = market_of(pick)
    if not market:
        race = hand_market(desc)
        return (race[1], race[0]) if race else (None, desc)
    # "Minnesota Vikings Yes" is the Vikings; the Yes belongs with the market.
    yes_no = YESNO_RE.match(desc)
    if yes_no:
        return yes_no.group(1), f"{market} \u00b7 {yes_no.group(2)}"
    return desc, market


def unit_val(pick):
    u = pick.get("units")
    return float(u) if isinstance(u, (int, float)) else 0.0


def _sum(picks, field):
    return sum(float(p[field]) for p in picks
               if isinstance(p.get(field), (int, float)))


# Nothing on the board is quoted in dollars, so there is no dollar sum here to
# quote it with: `staked` is the risk and `won` is the return, both in units.
def staked(picks):
    return _sum(picks, "units")


def won(picks):
    """Potential profit in units.

    A unit is not a fixed number of dollars across the book -- the size drifts
    with the season -- so each ticket's return is converted at its own
    stake-to-units rate rather than at one rate for the whole page. Rows the
    book priced at nothing carry no return to convert and drop out."""
    total = 0.0
    for pick in picks:
        stake, units, win = (pick.get("stake"), pick.get("units"),
                             pick.get("to_win"))
        if not all(isinstance(v, (int, float)) for v in (stake, units, win)):
            continue
        if stake:
            total += float(win) * float(units) / float(stake)
    return total


def thumb(pick, images, logo=False):
    """The mark for a row: the pick's own art, else optionally its club's.

    `logo` is off by default because on the futures board every row already
    sits inside a card headed by that club's mark, so repeating it down the
    rows adds a column of identical badges and no information. On a parlay leg
    or a game card there is no such header, and the club mark is the fastest
    read of who the leg is on."""
    img = images.get(pick["raw"].get("image") or "", "")
    if not img and logo:
        side = pick["raw"].get("side_id")
        if side in TEAMS:
            img = images.get(f"logo:{TEAMS[side][0]}", "")
    return (f'<img src="{img}" alt="">' if img
            else '<span class="ph" aria-hidden="true">--</span>')


def render_pick(pick, images, sub=False, text=None, logo=False):
    detail = text or split_pick(pick)[1] or pick["description"]
    mark = "" if sub else thumb(pick, images, logo)
    return (f'<li class="pick{" sub" if sub else ""}">{mark}'
            f'<span class="d">{esc(detail)}</span>'
            f'<span class="col u num">{fmt_units(pick["units"])}</span>'
            f'<span class="col odds num">{fmt_odds(pick["odds"])}</span></li>')


# Goes in the header of whatever card directly encloses a list of tickets --
# every .team-head, plus the one .div-head that holds picks itself rather than
# clubs. Naming the columns on each row instead cost 272 words across the board
# to say the same two things.
COL_HEAD = ('<span class="colhead"><span class="col u">Units</span>'
            '<span class="col odds">Odds</span></span>')


def render_market_picks(picks, images):
    """Rows for one league-wide market -- the field, biggest bet first.

    The card is headed by the market, so each row carries only who was backed
    in it. That is the mirror image of a club card, where the header is the
    subject and the rows carry the market."""
    return [render_pick(p, images, text=split_pick(p)[0] or p["description"])
            for p in sorted(picks, key=lambda p: -unit_val(p))]


def pick_blocks(picks, club=None):
    """(the club's own tickets, [(subject, tickets)]) -- the order a card reads.

    Split out of render_picks so the ledger's rows can be built in the same
    order as the list rows, off the same grouping, without either one drifting
    from the other."""
    subjects = defaultdict(list)
    blocks = []
    for pick in picks:
        subject = split_pick(pick)[0]
        if subject is None:
            blocks.append((None, [pick]))
        else:
            subjects[subject].append(pick)
    own = sorted(subjects.pop(club, []), key=lambda p: -unit_val(p))
    blocks += [(name, sorted(group, key=lambda p: -unit_val(p)))
               for name, group in subjects.items()]
    blocks.sort(key=lambda b: (-sum(unit_val(p) for p in b[1]),
                               b[0] or b[1][0]["description"]))
    return own, blocks


def render_picks(picks, images, club=None, logo=False):
    """Rows for one club, gathered by subject and ordered by size of the bet.

    Six Ladd McConkey receiving-yard tickets are one position taken at six
    prices, so they read as one block; a pick with no identifiable subject is
    its own block of one and sorts among the rest on units, which keeps the
    biggest bet at the top of the club whatever shape it was entered in.

    `club` is the name on the card. Tickets whose subject IS the club -- win
    totals, division, playoffs -- lead the card with no header of their own,
    because the card is already headed by that name and repeating it two lines
    down reads as a rendering fault rather than as a group.
    """
    own, blocks = pick_blocks(picks, club)
    out = [render_pick(p, images, sub=True) for p in own]
    for subject, group in blocks:
        if subject is None:
            out.append(render_pick(group[0], images, logo=logo))
            continue
        out.append(f'<li class="subj">{thumb(group[0], images, logo)}'
                   f'<span class="nm condensed">{esc(subject)}</span></li>')
        out += [render_pick(p, images, sub=True) for p in group]
    return out


# ---- the club ledger -------------------------------------------------------
#
# Every club card used to print its own stake in its header. That is 27 numbers
# in 27 places, none of which can be read against another without scrolling, so
# the club headers now carry only a name and the money is stated once, here, as
# one ordered table.
#
# The split into team and player markets is the same one the club cards make:
# a ticket whose subject is the club itself -- win totals, division, playoffs,
# make-the-playoffs -- is a bet on the club, and everything else on the card is
# a bet on somebody who plays for it. A hand-typed ticket with no subject at
# all ("Jets fewest wins") is a bet on the club, since that is what the words
# say and there is no player in them.


def club_split(picks, club):
    """(team-market picks, player-market picks) for one club's card."""
    team, player = [], []
    for pick in picks:
        subject = split_pick(pick)[0]
        (team if subject in (None, club) else player).append(pick)
    return team, player


# The risk columns are heat-mapped, which is the one thing a column of stakes
# cannot say on its own: 27 clubs of 0.5u to 5.6u all read as "some units" until
# the biggest of them is the darkest gold on the board and the smallest is no
# colour at all. The ramp runs between the two extremes actually present rather
# than from zero, so the board always spends its full range, and it is drawn as
# an inset shadow rather than a background so the row's own hover and open
# greys still show through underneath it.
HEAT_RGB = "214, 147, 36"
HEAT_MAX = 0.85
HEAT_CURVE = 0.75


def heat(value, band):
    """The gold wash for one risk cell. "" when there is nothing to shade."""
    lo, hi = band
    if value <= 0 or hi <= lo:
        return ""
    alpha = round(HEAT_MAX * ((value - lo) / (hi - lo)) ** HEAT_CURVE, 3)
    if alpha <= 0:
        return ""
    return f' style="box-shadow:inset 0 0 0 99px rgba({HEAT_RGB},{alpha})"'


def heat_band(by_team, by_div, by_market=None, other=()):
    """(smallest, largest) risk over every cell the heat map covers.

    Only the halves that carry a ticket count: an empty cell is a dash, not a
    zero, and letting it set the floor would shade every real number on the
    board a shade too dark."""
    seen = []
    for abbr, name in TEAMS_BY_ABBR.items():
        team, player = club_split(by_team.get(abbr, []), name)
        seen += [staked(half) for half in (team, player) if half]
    seen += [staked(picks) for picks in by_div.values() if picks]
    for picks in list((by_market or {}).values()) + [[p] for p in other]:
        team, player = club_split(picks, None)
        seen += [staked(half) for half in (team, player) if half]
    seen = [v for v in seen if v > 0]
    return (min(seen), max(seen)) if seen else (0, 0)


def ledger_cells(picks, band=(0, 0)):
    """Risk and to-win for one half of a row, dashed when there is nothing."""
    if not picks:
        return ('<td class="n zip">&mdash;</td><td class="n zip">&mdash;</td>')
    return (f'<td class="n num"{heat(staked(picks), band)}>{unit_str(staked(picks))}</td>'
            f'<td class="n num">{unit_str(won(picks))}</td>')


# A club row is a disclosure: the totals are what it says closed, the club's
# own tickets are what it says open. The tickets are rows of the same table
# rather than a panel inside one cell, so every ticket's units and odds fall in
# the columns the row above counts them in -- team markets under the team
# pair, player markets under the player pair -- and the columns keep ruling up
# however many clubs happen to be open.


def pick_side(pick, club):
    """Which pair of money columns a ticket falls under.

    The same split the club row makes: a ticket whose subject is the club is a
    bet on the club, and everything else is a bet on somebody who plays for it.
    """
    return "team" if split_pick(pick)[0] in (None, club) else "player"


def ledger_pick_cells(pick, side):
    """A ticket's stake and return, in the pair of columns it belongs to.

    Both columns are units, which is what every number on the board is: the
    stake is what the book charged, the unit is what the bet was worth to the
    person placing it. The price is not here at all -- it rides beside the
    description instead, since a two-figure American odd is not a quantity that
    rules up against a column of stakes."""
    units = f'<td class="n num">{fmt_units(pick["units"])}</td>'
    win = f'<td class="n num">{unit_str(won([pick]))}</td>'
    gap = '<td class="n"></td>'
    return units + win + gap + gap if side == "team" else gap + gap + units + win


def ledger_pick_row(pick, side, mark="", text=None, sub=False):
    """One ticket as a row: what it says, what it pays, what it cost."""
    detail = text or split_pick(pick)[1] or pick["description"]
    return (f'<tr class="pk{" sub" if sub else ""}"><td class="c">{mark}'
            f'<span class="d">{esc(detail)}</span>'
            f'<span class="odds num">{fmt_odds(pick["odds"])}</span></td>'
            f'{ledger_pick_cells(pick, side)}</tr>')


def ledger_pick_rows(picks, images, club=None, side=None):
    """One club's tickets as table rows, grouped by subject like its old card.

    `side` forces both halves of a row into one pair of columns, which is what
    a division ticket needs: the subject of a bet on a division's finishing
    order is the division, so all of it is a team market.
    """
    own, blocks = pick_blocks(picks, club)

    def row(pick, sub, mark=""):
        return ledger_pick_row(pick, side or pick_side(pick, club), mark,
                               sub=sub)

    out = [row(p, True) for p in own]
    for subject, group in blocks:
        if subject is None:
            out.append(row(group[0], False, thumb(group[0], images)))
            continue
        out.append(f'<tr class="pk sj"><td class="c">{thumb(group[0], images)}'
                   f'<span class="nm condensed">{esc(subject)}</span></td>'
                   f'<td colspan="4"></td></tr>')
        out += [row(p, True) for p in group]
    return out


def ledger_field_rows(picks, images):
    """Rows for one league-wide market -- the field, biggest bet first.

    The row above is headed by the market, so each ticket carries only who was
    backed in it. That is the mirror image of a club's rows, where the header
    is the subject and the tickets carry the market."""
    return [ledger_pick_row(p, pick_side(p, None), thumb(p, images),
                            text=split_pick(p)[0] or p["description"])
            for p in sorted(picks, key=lambda p: -unit_val(p))]


def ledger_rows(rid, mark, label, team, player, images, club=None,
                other=False, band=(0, 0), field=False):
    """One club as its own <tbody>: the money row, then the tickets it opens.

    A tbody per club is what makes the disclosure one class on one element
    rather than a hidden attribute on every ticket row underneath it."""
    picks = team + player
    row_cls = "tm" + ("" if picks else " zero") + (" oth" if other else "")
    hook = ("" if not picks else
            ' role="button" tabindex="0" aria-expanded="false"'
            f' aria-controls="{rid}"')
    # The label is wrapped rather than bare so the narrow board can drop it
    # for the club mark beside it -- visually only; it stays in the accessible
    # name of the row, which the logo's empty alt cannot carry.
    row = (f'<tr class="{row_cls}"{hook}><td class="c">'
           f'{mark}<span class="lb">{esc(label)}</span></td>'
           f'{ledger_cells(team, band)}{ledger_cells(player, band)}</tr>')
    tickets = "" if not picks else "".join(
        ledger_field_rows(picks, images) if field else
        ledger_pick_rows(picks, images, club, side="team" if other else None))
    return f'<tbody class="grp" id="{rid}">{row}{tickets}</tbody>'


# The only script on the board. Everything else here is baked markup, and this
# is deliberately no more than a disclosure toggle plus the measurement the
# sticky head needs: the rows carry their own state in aria-expanded so the
# sheet, the keyboard and the screen reader all read the same thing, and a row
# with nothing on it carries no hook at all.
LEDGER_JS = """
document.querySelectorAll('.fb .ledger').forEach(function (led) {
  var rows = led.querySelectorAll('tr.tm[aria-controls]');
  var all = led.querySelector('.xall');
  function set(tr, on) {
    tr.parentNode.classList.toggle('on', on);
    tr.classList.toggle('on', on);
    tr.setAttribute('aria-expanded', on ? 'true' : 'false');
  }
  function sync() {
    var open = 0;
    rows.forEach(function (tr) {
      if (tr.getAttribute('aria-expanded') === 'true') open++;
    });
    var every = open === rows.length;
    all.setAttribute('aria-expanded', every ? 'true' : 'false');
    all.textContent = every ? 'Collapse all' : 'Expand all';
  }
  function toggle(tr) { set(tr, tr.getAttribute('aria-expanded') !== 'true'); sync(); }
  led.addEventListener('click', function (e) {
    if (e.target.closest('.xall')) {
      var on = all.getAttribute('aria-expanded') !== 'true';
      rows.forEach(function (tr) { set(tr, on); });
      sync();
      return;
    }
    var tr = e.target.closest('tr.tm[aria-controls]');
    if (tr) toggle(tr);
  });
  led.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    var tr = e.target.closest && e.target.closest('tr.tm[aria-controls]');
    if (!tr) return;
    e.preventDefault();
    toggle(tr);
  });

  // The table head sticks under whatever sticky chrome the page puts above the
  // board -- the site header on the view, nothing at all on the standalone
  // build -- so the offset is measured rather than hard-coded to either one.
  function stick() {
    var top = 0;
    document.querySelectorAll('header').forEach(function (el) {
      var pos = getComputedStyle(el).position;
      if (pos === 'sticky' || pos === 'fixed') {
        top = Math.max(top, el.getBoundingClientRect().height);
      }
    });
    led.style.setProperty('--stick', top + 'px');
  }
  stick();
  window.addEventListener('load', stick);
  window.addEventListener('resize', stick);
});
"""


def ledger_bet_row(pick, images, band):
    """A ticket drawn as a row rather than inside one, because the row IS the
    bet: a hand-typed ticket ("JAX start 1-4") is filed under no club and no
    market, so there is nothing to head it with and nothing to open."""
    picks = [pick]
    team, player = ((picks, []) if pick_side(pick, None) == "team"
                    else ([], picks))
    return (f'<tbody class="grp"><tr class="tm bare"><td class="c">'
            f'{esc(pick.get("description"))}'
            f'<span class="odds num">{fmt_odds(pick["odds"])}</span></td>'
            f'{ledger_cells(team, band)}{ledger_cells(player, band)}'
            '</tr></tbody>')


def render_ledger(by_team, by_div, by_market, other, images):
    """Every club, banded by conference and division, each row an open ticket.

    A club used to be drawn twice on this page: once as a row of money here and
    once as a card of picks under its conference, a screen apart, so neither
    reading could be checked against the other. The rows now open. The money is
    the closed state, the tickets are inside it, and the conference/division
    structure that used to be a grid of cards is carried by banded rows in the
    one table -- red for the AFC and blue for the NFC, the same two colours the
    section bars wore when the sections existed.
    """
    all_team, all_player = [], []
    band = heat_band(by_team, by_div, by_market, other)
    body = []
    for conf, divisions in STRUCTURE.items():
        conf_picks = [p for abbr, picks in by_team.items()
                      if CONF_OF[abbr] == conf for p in picks]
        conf_picks += [p for (c, _), picks in by_div.items()
                       if c == conf for p in picks]
        colour = "var(--afc)" if conf == "AFC" else "var(--nfc)"
        body.append(f'<tbody class="bd"><tr class="band" style="--c:{colour}">'
                    f'<td class="c">{conf}</td>'
                    f'<td class="bmeta num" colspan="4">'
                    f'{unit_str(staked(conf_picks))} at risk &middot; '
                    f'{unit_str(won(conf_picks))} to win</td></tr></tbody>')

        for div, clubs in divisions.items():
            body.append(f'<tbody class="bd"><tr class="dband">'
                        f'<td class="c">{conf} {div}</td>'
                        f'<td colspan="4"></td></tr></tbody>')

            # Biggest book first inside the division, which is the ordering the
            # flat ledger had; the clubs with nothing on them fall to the foot
            # of their own division, where they read as what is NOT bet in it.
            for abbr in sorted(clubs, key=lambda a: (-staked(by_team.get(a, [])),
                                                     TEAMS_BY_ABBR[a])):
                picks = by_team.get(abbr, [])
                name = TEAMS_BY_ABBR[abbr]
                team, player = club_split(picks, name)
                all_team += team
                all_player += player
                logo = images.get(f"logo:{abbr}", "")
                mark = f'<img src="{logo}" alt="">' if logo else ""
                body.append(ledger_rows(f"led-{abbr.lower()}", mark, name,
                                        team, player, images, club=name,
                                        band=band))

            # A ticket on the division itself -- its finishing order, or a
            # field drawn from it -- belongs to the division rather than to
            # whichever club was typed first, so they sit last in it under a
            # row of their own.
            div_bets = by_div.get((conf, div), [])
            if div_bets:
                all_team += div_bets
                body.append(ledger_rows(f"led-{conf}-{div}".lower(), "",
                                        "Division markets", div_bets, [],
                                        images, other=True, band=band))

    # The league-wide markets are the third band, brass rather than red or
    # blue, and they read the same way down: the band is the field, a bucket
    # stands where a division does, and a market stands where a club does --
    # headed by what was bet rather than by who it was on, so its rows carry
    # the names in the field.
    league = [p for picks in by_market.values() for p in picks] + other
    if league:
        body.append('<tbody class="bd"><tr class="band" style="--c:var(--brass)">'
                    '<td class="c">NFL</td>'
                    f'<td class="bmeta num" colspan="4">{unit_str(staked(league))} '
                    f'at risk &middot; {unit_str(won(league))} to win</td>'
                    '</tr></tbody>')

        for bucket in ("Stat Leaders", "Awards", "Other"):
            markets = [(key[1], picks) for key, picks in by_market.items()
                       if key[0] == bucket]
            # Whatever could not be read as a club, a division or a market at
            # all closes the board, under the same head as the markets that
            # were only half readable.
            unfiled = sorted(other, key=lambda p: -unit_val(p)) \
                if bucket == "Other" else []
            if not markets and not unfiled:
                continue
            body.append('<tbody class="bd"><tr class="dband">'
                        f'<td class="c">{bucket}</td>'
                        '<td colspan="4"></td></tr></tbody>')
            markets.sort(key=lambda m: (-staked(m[1]), m[0]))
            for market, picks in markets:
                team, player = club_split(picks, None)
                all_team += team
                all_player += player
                rid = "led-mkt-" + re.sub(r"[^a-z0-9]+", "-", market.lower())
                body.append(ledger_rows(rid, "", market, team, player, images,
                                        band=band, field=True))
            for pick in unfiled:
                team, player = club_split([pick], None)
                all_team += team
                all_player += player
                body.append(ledger_bet_row(pick, images, band))

    return f'''<div class="ledger">
  <div class="div-head"><h5 class="condensed">Exposure</h5>
    <button type="button" class="xall" aria-expanded="false">Expand all</button>
  </div>
  <div class="scroll"><table>
    <thead>
      <tr><th class="c" rowspan="2">Team</th>
        <th class="g" colspan="2">Team markets</th>
        <th class="g" colspan="2">Player markets</th></tr>
      <tr><th class="n g">Risk</th><th class="n">To win</th>
        <th class="n g">Risk</th><th class="n">To win</th></tr>
    </thead>
    {"".join(body)}
    <tfoot><tr><td class="c">All markets</td>
      {ledger_cells(all_team)}{ledger_cells(all_player)}</tr></tfoot>
  </table></div>
</div>
<script>{LEDGER_JS}</script>'''



# ---- the pending non-futures book ------------------------------------------
#
# WHY A PARLAY IS NOT RENDERED AS A LIST OF PICKS
#
# A four-leg parlay is one wager. Drawn as four rows it reads as four wagers at
# four prices, and the +406 it actually pays goes missing. So the legs hang off
# a rail: a single line runs through a node on every leg and stops at the first
# and the last, the ticket's combined price sits alone at the head, and the foot
# says in words that all of them have to land. Nothing in the card offers a
# per-leg stake, because there isn't one.
#
# WHAT COUNTS AS PENDING
#
# `result == "pending"` is Action Network's field and it is not enough on its
# own: a parlay whose leg already lost is decided whatever the field says, and
# the book leaves plenty of finished tickets ungraded for years. A ticket is
# live here only if its event has not ended AND no leg has already lost.
# Everything else is still shown -- in a muted "Ungraded" card, out of the
# totals -- because silently dropping tickets would shrink the book on screen.


def parse_ts(value):
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def when(value, with_time=False, with_year=False):
    """A timestamp in the league's own clock, or "" if it will not parse.

    The year is off by default because every live ticket on the board is on
    this season, and on by request for the ungraded block, where a 2023 teaser
    reading "Mon 30 Oct" looks like next month."""
    dt = parse_ts(value)
    if not dt:
        return ""
    dt = dt.astimezone(EASTERN)
    if with_time:
        return dt.strftime(f"%a %-d %b · %-I:%M %p {TZ_LABEL}")
    if with_year:
        return dt.strftime("%-d %b %Y")
    return dt.strftime("%a %-d %b")


def legs_of(ticket):
    """Every leg of a group pick, from both lists the API splits them across.

    Market legs land in `picks` and hand-entered/futures legs in `custom_picks`;
    a ticket built entirely out of the second reads as "Parlay (0 legs)" if only
    the first is consulted, which is how ten of these went missing."""
    raw = ticket["raw"]
    return (raw.get("picks") or []) + (raw.get("custom_picks") or [])


# ---- the league calendar ---------------------------------------------------
#
# A game bet is filed by the week it plays in, and the week is not something the
# book records: Action Network stamps a kickoff on a ticket and nothing else. So
# it comes from the schedule instead -- data/nfl_schedule_2026.json, the
# committed ESPN pull, which carries a window per week. Matching on game id is
# not an option: ESPN's ids and Action Network's are unrelated numbers.


def load_weeks():
    """The season as [{week, start, end, first, last}], in UTC, contiguous.

    ESPN's own week windows leave a two-day hole between the Tuesday a week
    closes and the Thursday the next one opens, so a game flexed into it would
    belong to no week at all. Each week is therefore stretched to run until the
    next one starts, which files a Tuesday make-up under the week it was moved
    out of. `first`/`last` are the real kickoffs, which is what the slate runs
    between -- the window itself opens on the Wednesday and would misreport it.

    Returns [] if the file is missing; the board still renders, with every game
    bet in one undated block rather than in a week."""
    try:
        with open(SCHEDULE) as f:
            weeks = json.load(f)["weeks"]
    except (OSError, ValueError, KeyError):
        return []

    weeks = sorted(weeks, key=lambda w: w["start"])
    spans = []
    for i, week in enumerate(weeks):
        start = parse_ts(week["start"])
        end = parse_ts(weeks[i + 1]["start"] if i + 1 < len(weeks)
                       else week["end"])
        if not (start and end):
            continue
        kicks = sorted(k for k in (parse_ts(g.get("kickoff"))
                                   for g in week.get("games") or []) if k)
        spans.append({"week": week["week"], "start": start, "end": end,
                      "first": kicks[0] if kicks else start,
                      "last": kicks[-1] if kicks else end})
    return spans


def span_label(week):
    """"Thu 10 - Mon 14 Sep" -- the days a week's slate runs between."""
    first = week["first"].astimezone(EASTERN)
    last = week["last"].astimezone(EASTERN)
    if first.date() == last.date():
        return first.strftime("%a %-d %b")
    head = first.strftime("%a %-d" if first.month == last.month else "%a %-d %b")
    return f"{head} \u2013 {last.strftime('%a %-d %b')}"


# Sort keys for the blocks that are not a numbered week. Preseason leads the
# season, the postseason follows week 18, and anything the calendar does not
# cover at all -- another league, an exhibition -- lands after both.
PRESEASON, POSTSEASON, UNSCHEDULED = 0, 99, 100


def slate_of(ticket, weeks):
    """(order, label, span) -- the block a non-futures ticket is filed under.

    A ticket is filed by when it plays rather than by when it was placed, so
    the stamp is the earliest kickoff among its legs and only falls back to the
    ticket's own when it has none. Anything off the regular-season calendar
    keeps a block of its own rather than being forced into a week it is not in.
    """
    starts = sorted(s for s in (leg.get("starts_at") for leg in legs_of(ticket))
                    if s)
    stamp = parse_ts(starts[0] if starts else ticket.get("starts_at"))
    league = (ticket.get("league") or "nfl").lower()

    if stamp and weeks and league == "nfl":
        for week in weeks:
            if week["start"] <= stamp < week["end"]:
                return week["week"], f"Week {week['week']}", span_label(week)
        if stamp < weeks[0]["start"]:
            return PRESEASON, "Preseason", ""
        return POSTSEASON, "Postseason", ""
    return UNSCHEDULED, "Other", ""


def is_live(ticket, now):
    ends = parse_ts(ticket["raw"].get("ends_at")) or parse_ts(ticket.get("starts_at"))
    if ends and ends < now:
        return False
    return not any(leg.get("result") == "loss" for leg in legs_of(ticket))


def ticket_noun(ticket):
    return "teaser" if ticket.get("_kind") == "teasers" else "parlay"


def league_tag(ticket):
    """A badge naming the league, on the tickets that are not the NFL.

    The futures board above is NFL-only but this one is the whole open book, so
    NFL is the unmarked case and anything else has to say so or it reads as a
    football ticket with a strange matchup."""
    league = (ticket.get("league") or "").upper()
    return f'<span class="tag">{esc(league)}</span>' if league not in ("NFL", "") else ""


def leg_pick(leg):
    """A leg dressed as a pick, so split_pick/market_of/thumb apply unchanged."""
    return {"description": leg.get("play") or "", "odds": leg.get("odds"),
            "units": leg.get("units"), "raw": leg}


def is_season_futures(ticket):
    """True when every leg of a multi was entered in a season-long market.

    Only a leg placed through a futures market carries a market name, so all
    legs carrying one is what makes the whole ticket a bet on the season
    rather than on a game -- and that is what sends it to the futures board
    above instead of into a week down here."""
    legs = legs_of(ticket)
    return bool(legs) and all(market_of(leg_pick(leg)) for leg in legs)


def ticket_tag(ticket, games):
    """What the ticket is on: a season, a single game, or a date.

    One shared game id makes it a same-game parlay and earns the matchup as
    its label."""
    legs = legs_of(ticket)
    if is_season_futures(ticket):
        return "Season futures"
    game_ids = {leg.get("game_id") for leg in legs if leg.get("game_id")}
    if len(game_ids) == 1:
        matchup = games.get(game_ids.pop())
        if matchup:
            return matchup
    starts = sorted(s for s in (leg.get("starts_at") for leg in legs) if s)
    return when(starts[0]) if starts else ""


def render_leg(leg, images, games):
    """One link in the chain: node, mark, and what was bet.

    A leg carries no price. The only price on the card is the ticket's, so the
    text runs the full width of the row rather than being cropped for a column
    of numbers that do not add up to anything."""
    pick = leg_pick(leg)
    subject, detail = split_pick(pick)
    if subject and detail and detail != subject:
        text = f"<b>{esc(subject)}</b> · {esc(detail)}"
    else:
        text = esc(detail or subject or leg.get("play") or "--")

    matchup = games.get(leg.get("game_id"))
    if matchup:
        text += f'<span class="mu">{esc(matchup)}</span>'

    result = leg.get("result") or "pending"
    return (f'<li class="leg {esc(result)}">{thumb(pick, images, logo=True)}'
            f'<span class="d">{text}</span></li>')


def render_ticket(ticket, images, games, show_tag=True):
    """One ticket as a card. `show_tag` is off where the block it sits in
    already says what the tag would -- the season-futures parlays, which are
    under a heading that reads Parlays inside the NFL futures section."""
    legs = legs_of(ticket)
    title = f"{len(legs)}-leg {ticket_noun(ticket)}" if legs else ticket_noun(ticket)
    tease = (ticket["raw"].get("meta") or {}).get("tease")
    if tease and ticket.get("_kind") == "teasers":
        title = f"{len(legs)}-leg {tease}-point teaser"

    tag = ticket_tag(ticket, games) if show_tag else ""

    # Stake and return sit with the title as one phrase, so the whole ticket
    # -- what it is, what it risks to win what, at what price -- is one line.
    return (f'<article class="tik"><div class="tik-head">'
            f'<span class="nm condensed">{esc(title)}</span>'
            f'<span class="pays num">{fmt_units(ticket["units"])}u '
            f'<i>to win</i> {unit_str(won([ticket]))}</span>'
            + league_tag(ticket)
            + (f'<span class="tag">{esc(tag)}</span>' if tag else "")
            + f'<span class="price num">{fmt_odds(ticket["odds"], ratio=False)}</span></div>'
            f'<ul class="legs">'
            + "".join(render_leg(leg, images, games) for leg in legs)
            + "</ul></article>")


def render_game(matchup, picks, images):
    """A card of singles filed under the game they are all bets on."""
    kickoff = when(picks[0].get("starts_at"), with_time=True)
    return ('<div class="gm"><div class="gm-head">'
            f'<h5 class="condensed">{esc(matchup)}</h5>'
            + league_tag(picks[0])
            + (f'<span class="when">{esc(kickoff)}</span>' if kickoff else "")
            + f'<span class="rk num">{unit_str(staked(picks))}</span>{COL_HEAD}</div>'
            '<ul class="picks">'
            + "".join(render_picks(picks, images, logo=True))
            + "</ul></div>")


def render_stale(tickets, images):
    """Finished-but-ungraded tickets, one line each, outside every total."""
    rows = []
    for ticket in sorted(tickets, key=lambda t: t["raw"].get("ends_at") or ""):
        legs = legs_of(ticket)
        label = ticket["description"]
        if legs:
            label = f"{len(legs)}-leg {ticket_noun(ticket)}: " + ", ".join(
                (leg.get("play") or "?") for leg in legs)
        ended = (when(ticket["raw"].get("ends_at"), with_year=True)
                 or when(ticket.get("starts_at"), with_year=True))
        rows.append(f'<li class="pick"><span class="when num">{esc(ended)}</span>'
                    f'<span class="d">{league_tag(ticket)}{esc(label)}</span>'
                    f'<span class="col u num">{fmt_units(ticket["units"])}</span>'
                    f'<span class="col odds num">{fmt_odds(ticket["odds"])}</span></li>')
    return ('<div class="gm dead"><div class="gm-head">'
            '<h5 class="condensed">Event over, never settled</h5>'
            f'{COL_HEAD}</div><ul class="picks">' + "".join(rows) + "</ul></div>")


# ---- the pages -------------------------------------------------------------
#
# ONE PAGE PER SLATE, AND WHY
#
# The book used to be a single page: the futures board, and every open game bet
# beneath it. It is now nineteen. A week is the unit a game bet is placed, read
# and settled in, so it is the unit a page should hold -- and the one page it
# all used to sit on had grown to two megabytes of inlined artwork, every byte
# of which had to arrive before you could read the two tickets on Sunday's
# slate. Splitting along the seam the board was already grouped by costs nothing
# in structure and means a week's page carries a week's images and no more.
#
#   /football/action                 the index: every slate as a cell
#   /football/action/futures         the season book, by conference and field
#   /football/action/week/1 ... /18  one page per week of the schedule
#   /football/action/preseason       the off-calendar slates, each of which
#   /football/action/postseason      exists only while something is on it
#   /football/action/other
#
# Every week of the schedule gets a page whether or not anything is on it. A
# link that 404s because nobody bet that Sunday is worse than a page that says
# so, and the empty weeks are what make the shape of the book legible.

# order -> (slug, strip label) for the blocks that are not a numbered week.
OFF_CALENDAR = {PRESEASON: ("preseason", "Pre"),
                POSTSEASON: ("postseason", "Post"),
                UNSCHEDULED: ("other", "Other")}


def route(slug):
    """The site path a page is served at."""
    if slug == "index":
        return "/football/action"
    if slug.startswith("week-"):
        return f"/football/action/week/{slug[len('week-'):]}"
    return f"/football/action/{slug}"


def offline(slug):
    """The same page in the standalone copy, which is a folder of files."""
    return f"{slug}.html"


def build_slates(live, weeks):
    """Every page of the game book, in calendar order, empty weeks included."""
    pages = {}
    for week in weeks:
        pages[week["week"]] = {
            "slug": f"week-{week['week']}", "label": f"Week {week['week']}",
            "short": str(week["week"]), "span": span_label(week),
            "multis": [], "singles": []}

    for ticket in live:
        order, label, span = slate_of(ticket, weeks)
        slug, short = OFF_CALENDAR.get(order, (f"week-{order}", str(order)))
        page = pages.setdefault(order, {"slug": slug, "label": label,
                                        "short": short, "span": span,
                                        "multis": [], "singles": []})
        page["singles" if ticket["_kind"] == "straight" else "multis"].append(ticket)

    out = []
    for order in sorted(pages):
        page = pages[order]
        page["tickets"] = page["multis"] + page["singles"]
        out.append(page)
    return out


def render_pager(pages, current, href):
    """Every page of the book on one strip, with the one you are on marked.

    Nineteen pages need a way across that is not the back button, and the strip
    doubles as the shape of the season: the weeks carrying nothing are still in
    it, greyed, so a hole in the book is visible from any page in the book."""
    links = ['<a class="all%s" href="%s">All</a>'
             % (" on" if current == "index" else "", href("index"))]
    for page in pages:
        state = " on" if page["slug"] == current else ""
        state += "" if page["tickets"] else " zero"
        state += " lead" if page.get("lead") else ""
        links.append(f'<a class="{state.strip()}" href="{href(page["slug"])}" '
                     f'title="{esc(page["label"])}">{esc(page["short"])}</a>')
    return f'<nav class="pager">{"".join(links)}</nav>'


def render_grid(pages, href):
    """The index proper: one cell per slate, the season as a book of books.

    The foot of a cell is where a settled slate's profit goes. Nothing here is
    settled yet, so it says so in words rather than being left off -- a line
    that appears later moves every number in the cell when it does."""
    cells = []
    for page in pages:
        tickets = page["tickets"]
        classes = ("cell" + (" lead" if page.get("lead") else "")
                   + ("" if tickets else " zero"))
        if tickets:
            body = (f'<div class="v num">{len(tickets)}</div>'
                    f'<div class="k condensed">tickets</div>'
                    f'<div class="exp num">{unit_str(staked(tickets))} at risk '
                    f'&middot; {unit_str(won(tickets))} to win</div>')
            foot = '<div class="cell-foot condensed">All pending</div>'
        else:
            # One line and no foot. Seventeen empty weeks drawn to the height
            # of a live one bury the two slates that carry anything.
            body = '<div class="k condensed">Nothing on it</div>'
            foot = ""
        cells.append(
            f'<a class="{classes}" href="{href(page["slug"])}">'
            '<div class="cell-head">'
            f'<span class="nm condensed">{esc(page["label"])}</span>'
            + (f'<span class="when num">{esc(page["span"])}</span>'
               if page["span"] else "")
            + f'</div><div class="cell-body">{body}</div>{foot}</a>')
    return f'<div class="grid">{"".join(cells)}</div>'


def render_totals(tickets, extra):
    """The three numbers a book of pending tickets is read by.

    Three lines of a table rather than a row of tiles: they are three readings
    of one book, they rule up as such, and a tile apiece was three boxes of
    chrome around nine words.

    `extra` is the note beside the count -- what those tickets are made of,
    which differs on every page and is the one thing the rows cannot work out
    for themselves."""
    each = unit_str(staked(tickets) / len(tickets)) if tickets else "--"
    return f'''<table class="totals">
  <tr><th class="condensed">Tickets</th>
    <td class="v num">{len(tickets)}</td>
    </tr>
  <tr><th class="condensed">At risk</th>
    <td class="v num">{unit_str(staked(tickets))}</td>
    </tr>
  <tr><th class="condensed">Potential profit</th>
    <td class="v num">{unit_str(won(tickets))}</td>
    </tr>
</table>'''


def build_index_html(pages, stale, images, generated, href):
    """/football/action -- the whole open book as a grid of its slates."""
    tickets = [t for page in pages for t in page["tickets"]]
    weeks_live = sum(1 for p in pages if p["tickets"] and not p.get("lead"))

    out = ['<div class="fb">', f'''<div class="mast">
  <div class="eyebrow condensed">Action Network &middot; My Action &middot; everything open</div>
  <h3 class="condensed">The Open Book</h3>
  <div class="asof">{len(tickets)} live tickets across the season book and
    {weeks_live} week{"" if weeks_live == 1 else "s"} of the schedule
    &middot; generated {generated}</div>
</div>''']
    out.append(render_pager(pages, "index", href))
    out.append(render_totals(
        tickets, f"on {weeks_live + 1} of {len(pages)} slates"))
    out.append(render_grid(pages, href))

    if stale:
        out.append('<section class="conf" style="--c:var(--slate)">'
                   f'''<div class="conf-head"><h4 class="condensed">Ungraded</h4>
  <span class="meta num">{len(stale)} tickets &middot;
    {unit_str(staked(stale))} staked &middot; not counted above</span>
</div><div class="wide">''')
        out.append(render_stale(stale, images))
        out.append("</div></section>")
        out.append('<div class="note">Action Network still reports these as '
                   '<strong>pending</strong>, but every one of them is decided: '
                   'the event has finished, or a leg has already lost. They are '
                   'listed so the book on this page matches the book in the app, '
                   'and excluded from every total above so the live exposure is '
                   'the real one. They belong to no live slate, which is why '
                   'they sit here rather than on a week.</div>')

    out.append("</div>")  # .fb
    return "\n".join(out)


def build_slate_html(slate, pages, images, games, generated, href):
    """One week's page: its multis, then its singles filed by game.

    Multis lead because they are the tickets whose shape needs explaining, and
    the singles under them then read as the degenerate one-leg case of the same
    thing rather than as an unrelated second list."""
    tickets = slate["tickets"]
    multis, singles = slate["multis"], slate["singles"]
    count_line = (f'{len(multis)} multi{"" if len(multis) == 1 else "s"} and '
                  f'{len(singles)} single{"" if len(singles) == 1 else "s"} '
                  "still live &middot; ") if tickets else ""

    out = ['<div class="fb">', f'''<div class="mast">
  <div class="eyebrow condensed">Action Network &middot; My Action &middot; pending</div>
  <h3 class="condensed">{esc(slate["label"])}</h3>
  <div class="asof">{esc(slate["span"]) + " &middot; " if slate["span"] else ""}
    {count_line}generated {generated}</div>
</div>''']
    out.append(render_pager(pages, slate["slug"], href))

    if not tickets:
        out.append('<div class="note">Nothing open on this slate. Season-long '
                   'tickets are on the <strong>Futures</strong> page; every '
                   'other week of the schedule has a page of its own, linked '
                   'above.</div>')
        out.append("</div>")
        return "\n".join(out)

    out.append(render_totals(
        tickets, f"{sum(len(legs_of(t)) for t in multis)} legs across "
                 f"{len(multis)} multis"))

    if multis:
        multis = sorted(multis, key=lambda t: (-unit_val(t), -len(legs_of(t))))
        out.append('<div class="tix">')
        out += [render_ticket(t, images, games) for t in multis]
        out.append("</div>")

    if singles:
        by_game = defaultdict(list)
        for pick in singles:
            by_game[pick.get("matchup") or "Other"].append(pick)
        out.append('<div class="gms">')
        for matchup, picks in sorted(
                by_game.items(),
                key=lambda kv: (kv[1][0].get("starts_at") or "", kv[0])):
            out.append(render_game(matchup, picks, images))
        out.append("</div>")

    out.append("</div>")  # .fb
    return "\n".join(out)


def build_futures_html(pending, fut_multis, pages, images, generated, games,
                       href):
    """/football/action/futures -- the season book, conference to club."""
    by_team = defaultdict(list)
    by_div = defaultdict(list)
    by_market = defaultdict(list)   # (bucket, market) -> picks
    other = []
    for pick in pending:
        scope, key = attribute(pick)
        if scope == "team":
            by_team[key].append(pick)
        elif scope == "division":
            by_div[key].append(pick)
        elif scope == "league":
            by_market[key].append(pick)
        else:
            other.append(pick)

    # The page totals what the page shows, parlays included.
    board = pending + fut_multis

    out = ['<div class="fb">', f'''<div class="mast">
  <div class="eyebrow condensed">Baker's Action</div>
  <h3 class="condensed">NFL Futures</h3>
</div>''']
    out.append(render_pager(pages, "futures", href))
    out.append(render_totals(
        board, f"{len(pending)} singles &middot; {len(fut_multis)} parlays"))
    out.append(render_ledger(by_team, by_div, by_market, other, images))

    # Everything a single ticket can say is now said in the one table above,
    # so all that is left down here is the parlays. A parlay is not a row and
    # cannot be made into one: it is ONE wager whose legs must all land, drawn
    # as a card with a rail, and the price at its head is the only one it pays.
    if fut_multis:
        fut_multis = sorted(fut_multis,
                            key=lambda t: (-unit_val(t), -len(legs_of(t))))
        out.append('<section class="conf" style="--c:var(--brass)">')
        out.append(f'''<div class="conf-head">
  <h4 class="condensed">Parlays</h4>
  <span class="meta num">{unit_str(staked(fut_multis))} at risk &middot;
    {unit_str(won(fut_multis))} to win</span>
</div><div class="tix">''')
        out += [render_ticket(t, images, games, show_tag=False)
                for t in fut_multis]
        out.append("</div></section>")

    out.append("</div>")  # .fb
    return "\n".join(out)


# ---- page templates --------------------------------------------------------

CRUMB_ROOT = ('<a href="/">Home</a><span class="separator">/</span>'
              '<a href="/football">Football</a><span class="separator">/</span>')


def crumbs(slug, label):
    if slug == "index":
        return CRUMB_ROOT + "<span>Action</span>"
    return (CRUMB_ROOT + '<a href="/football/action">Action</a>'
            '<span class="separator">/</span>'
            f"<span>{esc(label)}</span>")


VIEW_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
  <link rel="icon" type="image/png" href="/favicon.png">
  <title>%%TITLE%% | Dynast-Z</title>
  <!-- Theme first: theme.js sets <html data-theme> before the first paint,
       theme.css holds every colour token the sheets below spend. The board
       itself is light-only and scopes its own tokens under .fb. -->
  <script src="/scripts/base/theme.js"></script>
  <link rel="stylesheet" href="/styles/base/theme.css">
  <link rel="stylesheet" href="/styles/base/styles.css">
  <link rel="stylesheet" href="/styles/base/hub.css">
  <!-- Vercel Web Analytics. The /_vercel/insights/* routes are injected by
       Vercel at deploy time, so this 404s harmlessly when serving locally. -->
  <script>window.va = window.va || function () { (window.vaq = window.vaq || []).push(arguments); };</script>
  <script defer src="/_vercel/insights/script.js"></script>
  <style>%%CSS%%</style>
</head>
<body class="masters-body">
  <div id="header-mount"></div>
  <div id="nav-drawer-mount"></div>
  <script src="/scripts/base/auth.js"></script>
  <script src="/scripts/base/nav.js"></script>
  <script>initPage();</script>

  <div class="masters-content">
    <div class="masters-breadcrumbs">%%CRUMBS%%</div>

    <h2>%%HEAD%%</h2>

    <!-- GENERATED FILE -- do not hand-edit.
         Rebuild every page with: python3 scripts/render_futures.py

         NO GATE, DELIBERATELY. The board is baked into this committed file and
         Vercel serves it off the public CDN, so a requireAdmin() call here only
         ever hid it from whoever loaded the page in a browser -- the markup was
         already readable by anyone who fetched the URL. Rather than keep a
         check that implied a protection it never provided, the page is open and
         unlisted: the only link to it is the admin-gated card on
         views/home/football.html, so there is no way to click through without
         being an admin, and the URL itself works for anyone who has it.

         If this data ever needs to be actually private, the fix is to stop
         baking it into a committed file and serve it from an admin-verified
         endpoint instead. A client-side check is not that fix. -->
    %%BOARD%%
  </div>
</body>
</html>
"""

STANDALONE_PAGE = """<meta charset="utf-8">
<title>%%TITLE%%</title>
<style>%%CSS%%</style>
<div style="max-width:1180px;margin:0 auto;padding:20px 16px 60px">%%BOARD%%</div>
"""


def wrap(template, board, title, head, crumb):
    return (template.replace("%%CSS%%", CSS).replace("%%BOARD%%", board)
            .replace("%%CRUMBS%%", crumb).replace("%%HEAD%%", head)
            .replace("%%TITLE%%", title))


TEAMS_BY_ABBR = {abbr: name for abbr, name in TEAMS.values()}


def view_path(slug):
    """views/football/action.html for the index, action-<slug>.html for a page."""
    name = "action.html" if slug == "index" else f"action-{slug}.html"
    return os.path.join(VIEW_DIR, name)


def sweep(written):
    """Delete generated pages that no longer belong to the book.

    The set of pages is data-driven -- a postseason page exists only while a
    playoff ticket does -- so without this a slate that empties leaves a stale
    page behind, serving last month's numbers at a live URL."""
    keep = {os.path.abspath(p) for p in written}
    for name in sorted(os.listdir(VIEW_DIR)):
        if not (name == "action.html" or name.startswith("action-")):
            continue
        path = os.path.abspath(os.path.join(VIEW_DIR, name))
        if path not in keep:
            os.remove(path)
            print(f"Removed stale {os.path.relpath(path, ROOT)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--open", action="store_true",
                        help="open the standalone index in the default browser")
    args = parser.parse_args()

    if not os.path.exists(SOURCE):
        print(f"{SOURCE} not found -- run scripts/fetch_action_network.py first.",
              file=sys.stderr)
        return 1

    data = json.load(open(SOURCE))
    pending = [p for p in data["futures"]["pending"] if p.get("league") == "nfl"]
    if not pending:
        print("No pending NFL futures in the export.", file=sys.stderr)
        return 1

    pending.sort(key=lambda p: -(p["stake"] if isinstance(p["stake"], (int, float)) else 0))

    print(f"{len(pending)} pending NFL futures")

    # Everything else still open. `_kind` is stamped here rather than inferred
    # downstream because the export's own bucketing is the only place a teaser
    # is told apart from a parlay -- both carry group_pick_type "parlay" on
    # some rows, and a teaser's tease points live in meta, not in its type.
    now = datetime.now(timezone.utc)
    others = []
    for kind in ("parlays", "teasers", "straight"):
        for pick in data.get(kind, []):
            if pick.get("result") == "pending":
                others.append(dict(pick, _kind=kind))
    live = [t for t in others if is_live(t, now)]
    stale = [t for t in others if not is_live(t, now)]
    print(f"{len(live)} other pending tickets live, "
          f"{len(stale)} decided but ungraded (listed, not totalled)")

    # A parlay every leg of which is a season future is a futures ticket,
    # whatever bucket the book files it in, so it goes on the futures page
    # beside the other markets whose field is the whole league. What is left is
    # the game book, and that is filed by the week it plays in.
    fut_multis, rest = [], []
    for ticket in live:
        wager = (fut_multis if ticket["_kind"] != "straight"
                 and is_season_futures(ticket) else rest)
        wager.append(ticket)

    weeks = load_weeks()
    if weeks:
        print(f"{len(weeks)} weeks of the {SEASON} schedule loaded -- "
              f"{len(fut_multis)} live tickets are season-futures parlays and "
              f"go on the futures page, {len(rest)} into a week")
    else:
        print(f"WARNING: {SCHEDULE} not found -- game bets cannot be grouped "
              f"by week and all land on the 'other' page. Run "
              f"scripts/fetch_nfl_schedule.py --season {SEASON}.",
              file=sys.stderr)

    # game id -> "Away @ Home". Parlay legs keep a game id but the fetcher
    # strips the game record off them, so the label has to be borrowed from a
    # straight bet on the same game. Built off the whole export, settled
    # included, which is what gets the coverage up.
    games = {}
    for bucket in (data["futures"]["pending"], data["futures"]["settled"],
                   data.get("parlays", []), data.get("teasers", []),
                   data.get("straight", [])):
        for pick in bucket:
            gid = pick["raw"].get("game_id")
            if gid and pick.get("matchup"):
                games[gid] = pick["matchup"]

    urls = {p["raw"].get("image") for p in pending if p["raw"].get("image")}
    for ticket in live + stale:
        if ticket["raw"].get("image"):
            urls.add(ticket["raw"]["image"])
        for leg in legs_of(ticket):
            if leg.get("image"):
                urls.add(leg["image"])
    urls.discard(None)
    print(f"Inlining {len(urls)} pick images + 32 team marks ...")
    images = {}
    for url in sorted(urls):
        images[url] = data_uri(url)
    for abbr in TEAMS_BY_ABBR:
        images[f"logo:{abbr}"] = data_uri(LOGOS[abbr])
    missing = sum(1 for u in urls if not images[u])
    if missing:
        print(f"  {missing} image(s) could not be fetched -- placeholder shown")

    scopes = [attribute(p)[0] for p in pending]
    print(f"Attribution: {scopes.count('team')} to a team, "
          f"{scopes.count('division')} to a division, "
          f"{scopes.count('league')} to a league-wide market, "
          f"{scopes.count('other')} to neither")

    # The futures page is a page of the book like any week, so it carries the
    # same record: it leads the strip and the grid, and its span is the season.
    futures = {"slug": "futures", "label": "Futures", "short": "Futures",
               "span": f"{SEASON} season", "lead": True,
               "tickets": pending + fut_multis, "multis": [], "singles": []}
    pages = [futures] + build_slates(rest, weeks)

    generated = now.strftime("%d %b %Y")

    def board_of(page, href):
        if page["slug"] == "futures":
            return build_futures_html(pending, fut_multis, pages, images,
                                      generated, games, href)
        return build_slate_html(page, pages, images, games, generated, href)

    # (slug, browser title, page heading, breadcrumb leaf, board builder).
    jobs = [("index", "Action", "Action Network", "Action",
             lambda href: build_index_html(pages, stale, images, generated,
                                           href))]
    for page in pages:
        title = "NFL Futures" if page["slug"] == "futures" else page["label"]
        # Bound at definition time: the closure is called once per template and
        # a late-binding `page` would render the last slate onto every file.
        jobs.append((page["slug"], title, title, page["label"],
                     (lambda pg: lambda href: board_of(pg, href))(page)))

    # Two copies of the same book: the routed pages under views/, and a folder
    # of plain files that opens off the filesystem. They differ only in how the
    # strip and the grid link, which is what `href` decides.
    os.makedirs(OUT_DIR, exist_ok=True)
    written, sizes = [], []
    for slug, title, head, leaf, board_fn in jobs:
        for path, template, href in (
                (view_path(slug), VIEW_PAGE, route),
                (os.path.join(OUT_DIR, offline(slug)), STANDALONE_PAGE, offline)):
            html = wrap(template, board_fn(href), title, head,
                        crumbs(slug, leaf))
            with open(path, "w") as f:
                f.write(html)
            if template is VIEW_PAGE:
                written.append(path)
                sizes.append(len(html))
    print(f"Wrote {len(written)} pages to {os.path.relpath(VIEW_DIR, ROOT)}/ "
          f"and {os.path.relpath(OUT_DIR, ROOT)}/ -- "
          f"{sum(sizes) / 1024:.0f} KB in all, largest "
          f"{max(sizes) / 1024:.0f} KB")
    sweep(written)

    print("\nNOTE: these pages are committed and CDN-public, and carry no page "
          "gate. They\n      are unlisted, not private -- only the hub card "
          "linking to them is admin-only.\n      Anyone with a URL can read "
          "that page of the book.")

    if args.open:
        subprocess.run(["open", os.path.join(OUT_DIR, "index.html")])
    return 0


if __name__ == "__main__":
    sys.exit(main())
