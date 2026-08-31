#!/usr/bin/env python3
"""Render pending NFL futures from cache/an_picks.json as a standalone HTML board.

Reads the export written by fetch_action_network.py, keeps the pending NFL
futures, groups them conference -> division -> team, and writes a self-contained
page to cache/futures_board.html.

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
    python3 scripts/render_futures.py --open     # also open it in a browser
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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "cache", "an_picks.json")
OUT = os.path.join(ROOT, "cache", "futures_board.html")
VIEW = os.path.join(ROOT, "views", "football", "futures.html")
IMG_CACHE = os.path.join(ROOT, "cache", "an_images")
IMG_PX = 72

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

# Club marks, read off /web/v1/scoreboard/nfl. Hardcoded rather than derived
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

# Tokens that identify a club unambiguously in a hand-typed description. Word
# boundaries are enforced at match time, so "NE" cannot fire inside "NFC".
TEAM_TOKENS = {
    "ATL": "ATL", "FALCONS": "ATL", "WSH": "WAS", "WAS": "WAS",
    "COMMANDERS": "WAS", "JETS": "NYJ", "NYJ": "NYJ", "EAGLES": "PHI",
    "PHI": "PHI", "COWBOYS": "DAL", "DAL": "DAL", "BUCS": "TB",
    "BUCCANEERS": "TB", "SAINTS": "NO", "BEARS": "CHI", "CHI": "CHI",
    "LIONS": "DET", "DET": "DET", "PACKERS": "GB", "VIKINGS": "MIN",
    "GIANTS": "NYG", "RAMS": "LA", "49ERS": "SF", "SEAHAWKS": "SEA",
    "CARDINALS": "ARI", "PANTHERS": "CAR", "BILLS": "BUF", "DOLPHINS": "MIA",
    "PATRIOTS": "NE", "RAVENS": "BAL", "BENGALS": "CIN", "BROWNS": "CLE",
    "STEELERS": "PIT", "TEXANS": "HOU", "COLTS": "IND", "JAGUARS": "JAC",
    "TITANS": "TEN", "BRONCOS": "DEN", "CHIEFS": "KC", "CHARGERS": "LAC",
    "RAIDERS": "LV",
}


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
    for token in re.findall(r"[A-Za-z0-9']+", (text or "").upper()):
        abbr = TEAM_TOKENS.get(token)
        if abbr and abbr not in found:
            found.append(abbr)
    return found


# Markets whose field is the whole league rather than one roster. Matched on
# the market name because that is the only place the distinction is recorded:
# "Most Receiving Yards" is a race, "Total Receiving Yards" is a player prop,
# and nothing else in the payload tells them apart.
LEADER_RE = re.compile(r"^Most\b")
AWARD_RE = re.compile(r"\b(?:MVP|of the Year)$")


def league_bucket(pick):
    """'Stat Leaders', 'Awards', or None if the ticket belongs to a club."""
    market = market_of(pick)
    if LEADER_RE.match(market):
        return "Stat Leaders"
    if AWARD_RE.search(market):
        return "Awards"
    return None


def attribute(pick):
    """(scope, key) where scope is 'league', 'team', 'division' or 'other'."""
    bucket = league_bucket(pick)
    if bucket:
        return "league", (bucket, market_of(pick))

    side = pick["raw"].get("side_id")
    if side in TEAMS:
        return "team", TEAMS[side][0]

    named = teams_in_text(pick.get("description"))
    if len(named) == 1:
        return "team", named[0]
    if len(named) > 1:
        divisions = {(CONF_OF[a], DIV_OF[a]) for a in named}
        # Two clubs from one division is a bet on that division's order.
        if len(divisions) == 1:
            return "division", divisions.pop()
        return "team", named[0]
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

def fmt_odds(odds):
    """American odds, except that four-figure longshots read as a ratio.

    "+15000" is six glyphs of noise in a narrow column and nobody parses it as
    a price; "150:1" is the same number said the way the payout is spoken."""
    try:
        n = int(odds)
    except (TypeError, ValueError):
        return "--"
    if n >= 10000:
        return f"{n / 100:g}:1"
    return f"+{n}" if n > 0 else str(n)


def fmt_units(units):
    try:
        u = float(units)
    except (TypeError, ValueError):
        return "--"
    return f"{u:.2f}"


def money(amount):
    return f"${amount:,.0f}"


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
  --shadow:0 1px 2px rgba(17,22,28,.06),0 8px 20px -12px rgba(17,22,28,.18);
  background:var(--ground); color:var(--ink);
  font-family:"Helvetica Neue",Helvetica,Arial,sans-serif;
  font-size:15px; line-height:1.5; -webkit-font-smoothing:antialiased;
  border:1px solid var(--line); border-radius:14px;
  padding:26px 22px 34px; margin-top:18px;
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
.fb .eyebrow{font-size:11px;color:var(--muted)}
.fb .mast h3{font-size:clamp(26px,4vw,38px);line-height:1.04;margin:6px 0 0;
  font-weight:700;letter-spacing:-.01em;text-transform:uppercase;text-wrap:balance}
.fb .asof{font-size:12.5px;color:var(--muted);margin-top:7px}

.fb .totals{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
  gap:1px;background:var(--line);border:1px solid var(--line);
  border-radius:10px;overflow:hidden;margin-bottom:28px}
.fb .tot{background:var(--surface);padding:13px 15px}
.fb .tot .k{font-size:10.5px;color:var(--muted)}
.fb .tot .v{font-size:23px;margin-top:4px;font-weight:600;letter-spacing:-.01em}
.fb .tot .s{font-size:11.5px;color:var(--muted);margin-top:2px}

.fb .conf{margin-top:34px}
/* The conference accent fills the bar rather than tinting the type, which puts
   the strongest value on the board at its top level and leaves the greys below
   to carry division/club/pick depth on their own. */
.fb .conf-head{display:flex;align-items:baseline;gap:12px;
  background:var(--c);color:#FFFFFF;border-radius:10px;
  padding:11px 16px;margin-bottom:15px}
.fb .conf-head h4{font-size:24px;margin:0;color:#FFFFFF;letter-spacing:.07em;
  font-weight:700;text-transform:uppercase}
.fb .conf-head .meta{font-size:12.5px;color:#FFFFFF;margin-left:auto}

.fb .divs{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));
  gap:16px;align-items:start}
@media (min-width:900px){.fb .divs{grid-template-columns:repeat(2,1fr)}}
.fb .div{background:var(--surface);border:1px solid var(--line);
  border-radius:12px;box-shadow:var(--shadow);overflow:hidden}
.fb .div-head{display:flex;align-items:baseline;gap:8px;padding:11px 14px;
  background:var(--head-div);border-bottom:1px solid var(--line)}
.fb .div-head h5{font-size:13.5px;margin:0;letter-spacing:.11em;font-weight:700;
  text-transform:uppercase}

.fb .team{border-bottom:1px solid var(--line)}
.fb .team:last-child{border-bottom:0}
.fb .team-head{display:flex;align-items:center;gap:10px;padding:9px 14px;
  background:var(--head-team);border-bottom:1px solid var(--line)}
.fb .team-head img{width:22px;height:22px;object-fit:contain;flex:none}
.fb .team-head .nm{font-size:12.5px;letter-spacing:.06em;font-weight:600;
  text-transform:uppercase}
.fb .team-head .rk{font-size:11.5px;color:var(--muted);margin-left:auto}

.fb .picks{list-style:none;margin:0;padding:6px 14px 10px}
.fb .picks>.pick:first-child{border-top:0}
.fb .pick,.fb .subj{display:flex;align-items:center;gap:10px}
.fb .pick{padding:6px 0;border-top:1px dashed var(--line)}
.fb .pick img,.fb .subj img{width:26px;height:26px;object-fit:contain;
  border-radius:50%;background:var(--sunk);flex:none}
.fb .pick .ph,.fb .subj .ph{width:26px;height:26px;border-radius:50%;
  background:var(--sunk);flex:none;display:grid;place-items:center;
  font-size:9px;color:var(--muted)}
.fb .pick .d,.fb .cols .d{flex:1;min-width:0;font-size:13.5px}

/* A subject owns its headshot and its name; the tickets beneath it carry only
   what differs between them, indented to the width of the mark they share. */
.fb .subj{padding:10px 0 4px;border-top:1px solid var(--line)}
.fb .subj:first-child{border-top:0}
.fb .subj .nm{font-size:12px;font-weight:700;letter-spacing:.06em}
.fb .subj+.pick{border-top:0}
.fb .pick.sub{padding-left:36px}

/* Units and odds are fixed-width so every ticket on the board rules up into
   two columns, whatever the length of the line to its left. */
.fb .col{flex:none;font-size:12px;text-align:right}
.fb .col.u{width:54px}
.fb .col.odds{width:54px}
.fb .pick .col.odds{padding:2px 7px;color:var(--brass)}

/* The columns are named in the card's own header, so the list underneath is
   nothing but tickets. .colhead pairs them at the same width and gap the rows
   use, and both headers pad to 14px like .picks, so the two rule up. The odds
   cell repeats the row's own 7px padding so the label sits over the prices
   rather than over the column's outer edge. */
.fb .colhead{display:flex;flex:none;gap:10px;margin-left:6px}
.fb .div-head .colhead{margin-left:auto}
.fb .colhead .col{font-size:9px;color:var(--muted);font-weight:700;
  text-transform:uppercase;letter-spacing:.08em}
.fb .colhead .col.odds{padding:2px 7px}

.fb .note{margin-top:30px;padding:15px 17px;background:var(--surface);
  border:1px solid var(--line);border-left:4px solid var(--brass);
  border-radius:10px;font-size:13.5px;color:var(--muted)}
.fb .note strong{color:var(--ink)}
.fb .note ul{margin:8px 0 0;padding-left:18px}
@media (max-width:560px){.fb{padding:18px 13px 26px}}
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
        return None, desc
    # "Minnesota Vikings Yes" is the Vikings; the Yes belongs with the market.
    yes_no = YESNO_RE.match(desc)
    if yes_no:
        return yes_no.group(1), f"{market} \u00b7 {yes_no.group(2)}"
    return desc, market


def unit_val(pick):
    u = pick.get("units")
    return float(u) if isinstance(u, (int, float)) else 0.0


def thumb(pick, images):
    img = images.get(pick["raw"].get("image") or "", "")
    return (f'<img src="{img}" alt="">' if img
            else '<span class="ph" aria-hidden="true">--</span>')


def render_pick(pick, images, sub=False, text=None):
    detail = text or split_pick(pick)[1] or pick["description"]
    mark = "" if sub else thumb(pick, images)
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


def render_picks(picks, images, club=None):
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

    out = [render_pick(p, images, sub=True) for p in own]
    for subject, group in blocks:
        if subject is None:
            out.append(render_pick(group[0], images))
            continue
        out.append(f'<li class="subj">{thumb(group[0], images)}'
                   f'<span class="nm condensed">{esc(subject)}</span></li>')
        out += [render_pick(p, images, sub=True) for p in group]
    return out


def build_html(pending, images, generated):
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

    def risk(picks):
        return sum(float(p["stake"]) for p in picks
                   if isinstance(p["stake"], (int, float)))

    def towin(picks):
        return sum(float(p["to_win"]) for p in picks
                   if isinstance(p["to_win"], (int, float)))

    def units(picks):
        return sum(float(p["units"]) for p in picks
                   if isinstance(p["units"], (int, float)))

    total_risk, total_win, total_units = risk(pending), towin(pending), units(pending)
    probs = [p["implied_probability"] for p in pending
             if p["implied_probability"] is not None]

    out = ['<div class="fb">']

    out.append(f'''<div class="mast">
  <div class="eyebrow condensed">Action Network &middot; My Action &middot; pending futures</div>
  <h3 class="condensed">NFL Futures Board</h3>
  <div class="asof">{len(pending)} live tickets by conference, division and club,
    league-wide markets by field &middot; generated {generated}</div>
</div>''')

    out.append(f'''<section class="totals">
  <div class="tot"><div class="k condensed">Tickets</div>
    <div class="v num">{len(pending)}</div>
    <div class="s">{len(by_team)} clubs represented</div></div>
  <div class="tot"><div class="k condensed">At risk</div>
    <div class="v num">{money(total_risk)}</div>
    <div class="s num">{total_units:g} units staked</div></div>
  <div class="tot"><div class="k condensed">Potential profit</div>
    <div class="v num">{money(total_win)}</div>
    <div class="s num">{money(total_risk + total_win)} returned</div></div>
  <div class="tot"><div class="k condensed">Mean implied</div>
    <div class="v num">{sum(probs) / len(probs) * 100:.1f}%</div>
    <div class="s num">{sum(probs):.1f} expected winners</div></div>
</section>''')

    for conf, divisions in STRUCTURE.items():
        conf_picks = [p for abbr, picks in by_team.items()
                      if CONF_OF[abbr] == conf for p in picks]
        conf_picks += [p for (c, _), picks in by_div.items()
                       if c == conf for p in picks]
        if not conf_picks:
            continue
        colour = "var(--afc)" if conf == "AFC" else "var(--nfc)"
        out.append(f'<section class="conf" style="--c:{colour}">')
        out.append(f'''<div class="conf-head">
  <h4 class="condensed">{conf}</h4>
  <span class="meta num">{len(conf_picks)} tickets &middot;
    {money(risk(conf_picks))} at risk &middot;
    {money(towin(conf_picks))} to win</span>
</div><div class="divs">''')

        for div, clubs in divisions.items():
            div_bets = by_div.get((conf, div), [])
            club_picks = {a: by_team.get(a, []) for a in clubs}
            count = len(div_bets) + sum(len(v) for v in club_picks.values())
            if not count:
                continue
            out.append('<div class="div"><div class="div-head">'
                       f'<h5 class="condensed">{conf} {div}</h5></div>')

            for abbr in clubs:
                picks = club_picks[abbr]
                if not picks:
                    continue
                logo = images.get(f"logo:{abbr}", "")
                mark = (f'<img src="{logo}" alt="">' if logo else "")
                out.append(f'''<div class="team"><div class="team-head">{mark}
  <span class="nm condensed">{esc(TEAMS_BY_ABBR[abbr])}</span>
  <span class="rk num">{money(risk(picks))}</span>{COL_HEAD}
</div><ul class="picks">''')
                out += render_picks(picks, images, TEAMS_BY_ABBR[abbr])
                out.append("</ul></div>")

            # Tickets on the division's finishing order sit last, under the same
            # header treatment as a club: they belong to the division, not to
            # whichever club happened to be typed first.
            if div_bets:
                out.append('<div class="team"><div class="team-head">'
                           '<span class="nm condensed">Other</span>'
                           f'<span class="rk num">{money(risk(div_bets))}</span>'
                           f'{COL_HEAD}</div><ul class="picks">')
                out += render_picks(div_bets, images)
                out.append("</ul></div>")
            out.append("</div>")
        out.append("</div></section>")

    league = [p for picks in by_market.values() for p in picks] + other
    if league:
        out.append('<section class="conf" style="--c:var(--brass)">')
        out.append(f'''<div class="conf-head">
  <h4 class="condensed">NFL</h4>
  <span class="meta num">{len(league)} tickets &middot;
    {money(risk(league))} at risk &middot;
    {money(towin(league))} to win</span>
</div><div class="divs">''')

        for bucket in ("Stat Leaders", "Awards"):
            markets = [(key[1], picks) for key, picks in by_market.items()
                       if key[0] == bucket]
            if not markets:
                continue
            out.append('<div class="div"><div class="div-head">'
                       f'<h5 class="condensed">{bucket}</h5></div>')
            markets.sort(key=lambda m: (-units(m[1]), m[0]))
            for market, picks in markets:
                out.append('<div class="team"><div class="team-head">'
                           f'<span class="nm condensed">{esc(market)}</span>'
                           f'<span class="rk num">{money(risk(picks))}</span>'
                           f'{COL_HEAD}</div><ul class="picks">')
                out += render_market_picks(picks, images)
                out.append("</ul></div>")
            out.append("</div>")

        # Hand-typed tickets that name no club and sit in no market record.
        if other:
            out.append('<div class="div"><div class="div-head">'
                       f'<h5 class="condensed">Other</h5>{COL_HEAD}</div>'
                       '<ul class="picks">')
            out += render_picks(other, images)
            out.append("</ul></div>")
        out.append("</div></section>")

    out.append("</div>")  # .fb
    return "\n".join(out)


VIEW_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
  <link rel="icon" type="image/png" href="/favicon.png">
  <title>NFL Futures | Dynast-Z</title>
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
    <div class="masters-breadcrumbs">
      <a href="/">Home</a><span class="separator">/</span><a href="/football">Football</a><span class="separator">/</span><span>Futures</span>
    </div>

    <h2>NFL Futures</h2>

    <!-- GENERATED FILE -- do not hand-edit.
         Rebuild with: python3 scripts/render_futures.py

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

STANDALONE_PAGE = """<title>Pending NFL Futures</title>
<style>%%CSS%%</style>
<div style="max-width:1180px;margin:0 auto;padding:20px 16px 60px">%%BOARD%%</div>
"""


def wrap(template, board):
    return template.replace("%%CSS%%", CSS).replace("%%BOARD%%", board)


TEAMS_BY_ABBR = {abbr: name for abbr, name in TEAMS.values()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--open", action="store_true",
                        help="open the page in the default browser when done")
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

    urls = {p["raw"].get("image") for p in pending if p["raw"].get("image")}
    print(f"Inlining {len(urls)} pick images + 32 club marks ...")
    images = {}
    for url in sorted(urls):
        images[url] = data_uri(url)
    for abbr in TEAMS_BY_ABBR:
        images[f"logo:{abbr}"] = data_uri(LOGOS[abbr])
    missing = sum(1 for u in urls if not images[u])
    if missing:
        print(f"  {missing} image(s) could not be fetched -- placeholder shown")

    scopes = [attribute(p)[0] for p in pending]
    print(f"Attribution: {scopes.count('team')} to a club, "
          f"{scopes.count('division')} to a division, "
          f"{scopes.count('league')} to a league-wide market, "
          f"{scopes.count('other')} to neither")

    generated = datetime.now(timezone.utc).strftime("%d %b %Y")
    board = build_html(pending, images, generated)

    for path, template in ((OUT, STANDALONE_PAGE), (VIEW, VIEW_PAGE)):
        page = wrap(template, board)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(page)
        print(f"Wrote {os.path.abspath(path)} ({len(page) / 1024:.0f} KB)")

    print("\nNOTE: views/football/futures.html is committed and CDN-public, and "
          "carries no page\n      gate. It is unlisted, not private -- only the "
          "hub card linking to it is\n      admin-only. Anyone with the URL can "
          "read the board.")

    if args.open:
        subprocess.run(["open", OUT])
    return 0


if __name__ == "__main__":
    sys.exit(main())
