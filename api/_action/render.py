"""The Action Network betting book, rendered from a pregenerated page model.

This is the render half of what used to be scripts/render_futures.py. That
script read a 28 MB Action Network export and wrote twenty committed HTML files;
it now writes a small JSON page model per slate and pushes it, and this module
turns one of those models into a page at request time.

WHY IT LIVES UNDER api/

Vercel does not bundle scripts/** with a serverless function -- /api/odds-ingest
is dead in production for exactly that reason, and
docs/prompts/odds-supabase-migration.md already prescribes the fix: co-locate
the library under api/ and import it without sys.path games. So everything
api/action.py needs at request time is here or beside it, and nothing it needs
lives outside this directory. scripts/build_action.py imports this module the
other way round, which is safe because that script only ever runs locally.

WHAT IS SHARED AND WHY

The team tables and attribute() are here rather than in the build script because
the renderer needs them anyway -- thumb() resolves a club mark off side_id and
the ledger is banded by STRUCTURE -- and a second copy in the builder would be a
second thing to keep in step. Attribution is a pure function of a pick, so
running it at render time costs nothing and keeps one definition of which club a
ticket belongs to.

WHAT CHANGED FROM THE GENERATED PAGES

Two things, both forced by rendering one page instead of writing all twenty at
once. The pager and the grid used to walk every page's ticket list to size its
cell; they now read a precomputed `nav` array, so a week's payload carries that
week's tickets and nobody else's. And `images` maps an image key to a URL under
/assets/action/ rather than to an inlined data: URI -- the artwork is committed,
content-addressed and cached immutable, so it no longer rides along with data
that changes daily. scripts/build_action.py --standalone passes data: URIs
through the same dict, which is what still lets the offline copy open under a
strict CSP.
"""
import os
import re
from collections import defaultdict
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
    EASTERN, TZ_LABEL = ZoneInfo("America/New_York"), "ET"
except Exception:                                   # no tzdata on the host
    EASTERN, TZ_LABEL = timezone.utc, "UTC"

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

TEAMS_BY_ABBR = {abbr: name for abbr, name in TEAMS.values()}

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

def ticket_noun(ticket):
    return "teaser" if ticket.get("_kind") == "teasers" else "parlay"


def league_tag(ticket):
    """A badge naming the league, on the tickets that are not the NFL.

    The futures board above is NFL-only but this one is the whole open book, so
    NFL is the unmarked case and anything else has to say so or it reads as a
    football ticket with a strange matchup."""
    league = (ticket.get("league") or "").upper()
    return f'<span class="tag">{esc(league)}</span>' if league not in ("NFL", "") else ""


# The game-id -> matchup map arrives as JSON, and JSON object keys are always
# strings while a leg's game_id is an int -- so every lookup into `games` has to
# str() the id. Getting this wrong is silent: the matchup label simply stops
# appearing on parlay legs and the page still renders.
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
        matchup = games.get(str(game_ids.pop()))
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

    matchup = games.get(str(leg.get("game_id")))
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

def route(slug):
    """The site path a page is served at."""
    if slug == "index":
        return "/football/action"
    if slug.startswith("week-"):
        return f"/football/action/week/{slug[len('week-'):]}"
    return f"/football/action/{slug}"

CRUMB_ROOT = '<a href="/football">Football</a><span class="separator">/</span>'


def crumbs(slug, label):
    if slug == "index":
        return CRUMB_ROOT + "<span>Baker&rsquo;s Action</span>"
    return (CRUMB_ROOT + '<a href="/football/action">Baker&rsquo;s Action</a>'
            '<span class="separator">/</span>'
            f"<span>{esc(label)}</span>")

# ---- the pages -------------------------------------------------------------
#
# The book is a page per slate: the index, the futures board, and one page per
# week of the schedule. Every week gets a page whether or not anything is on it,
# because a link that 404s because nobody bet that Sunday is worse than a page
# that says so, and the empty weeks are what make the shape of the book legible.
#
# A page no longer knows about the other pages' tickets. `nav` is the strip and
# the grid in precomputed form -- one entry per page carrying its count and its
# two totals -- which is what lets week 3 be rendered without loading week 12.


def render_pager(nav, current, href):
    """Every page of the book on one strip, with the one you are on marked.

    Nineteen pages need a way across that is not the back button, and the strip
    doubles as the shape of the season: the weeks carrying nothing are still in
    it, greyed, so a hole in the book is visible from any page in the book."""
    links = ['<a class="all%s" href="%s">All</a>'
             % (" on" if current == "index" else "", href("index"))]
    for page in nav:
        state = " on" if page["slug"] == current else ""
        state += "" if page["count"] else " zero"
        state += " lead" if page.get("lead") else ""
        links.append(f'<a class="{state.strip()}" href="{href(page["slug"])}" '
                     f'title="{esc(page["label"])}">{esc(page["short"])}</a>')
    return f'<nav class="pager">{"".join(links)}</nav>'


def render_grid(nav, href):
    """The index proper: one cell per slate, the season as a book of books.

    The foot of a cell is where a settled slate's profit goes. Nothing here is
    settled yet, so it says so in words rather than being left off -- a line
    that appears later moves every number in the cell when it does."""
    cells = []
    for page in nav:
        count = page["count"]
        classes = ("cell" + (" lead" if page.get("lead") else "")
                   + ("" if count else " zero"))
        if count:
            body = (f'<div class="v num">{count}</div>'
                    f'<div class="k condensed">tickets</div>'
                    f'<div class="exp num">{unit_str(page["risk"])} at risk '
                    f'&middot; {unit_str(page["win"])} to win</div>')
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


def render_totals(count, risk, win):
    """The three numbers a book of pending tickets is read by.

    Three lines of a table rather than a row of tiles: they are three readings
    of one book, they rule up as such, and a tile apiece was three boxes of
    chrome around nine words."""
    return f'''<table class="totals">
  <tr><th class="condensed">Tickets</th>
    <td class="v num">{count}</td>
    </tr>
  <tr><th class="condensed">At risk</th>
    <td class="v num">{unit_str(risk)}</td>
    </tr>
  <tr><th class="condensed">Potential profit</th>
    <td class="v num">{unit_str(win)}</td>
    </tr>
</table>'''


def build_index_html(page, href):
    """/football/action -- the whole open book as a grid of its slates."""
    nav, stale = page["nav"], page["stale"]
    images, totals = page["images"], page["totals"]
    weeks_live = page["weeks_live"]

    out = ['<div class="fb">', f'''<div class="mast">
  <div class="eyebrow condensed">Action Network &middot; My Action &middot; everything open</div>
  <h3 class="condensed">The Open Book</h3>
  <div class="asof">{totals["count"]} live tickets across the season book and
    {weeks_live} week{"" if weeks_live == 1 else "s"} of the schedule
    &middot; generated {page["generated"]}</div>
</div>''']
    out.append(render_pager(nav, "index", href))
    out.append(render_totals(totals["count"], totals["risk"], totals["win"]))
    out.append(render_grid(nav, href))

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


def build_slate_html(page, href):
    """One week's page: its multis, then its singles filed by game.

    Multis lead because they are the tickets whose shape needs explaining, and
    the singles under them then read as the degenerate one-leg case of the same
    thing rather than as an unrelated second list."""
    images, games = page["images"], page["games"]
    multis, singles = page["multis"], page["singles"]
    tickets = multis + singles
    count_line = (f'{len(multis)} multi{"" if len(multis) == 1 else "s"} and '
                  f'{len(singles)} single{"" if len(singles) == 1 else "s"} '
                  "still live &middot; ") if tickets else ""

    out = ['<div class="fb">', f'''<div class="mast">
  <div class="eyebrow condensed">Action Network &middot; My Action &middot; pending</div>
  <h3 class="condensed">{esc(page["label"])}</h3>
  <div class="asof">{esc(page["span"]) + " &middot; " if page["span"] else ""}
    {count_line}generated {page["generated"]}</div>
</div>''']
    out.append(render_pager(page["nav"], page["slug"], href))

    if not tickets:
        out.append('<div class="note">Nothing open on this slate. Season-long '
                   'tickets are on the <strong>Futures</strong> page; every '
                   'other week of the schedule has a page of its own, linked '
                   'above.</div>')
        out.append("</div>")
        return "\n".join(out)

    out.append(render_totals(len(tickets), staked(tickets), won(tickets)))

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


def build_futures_html(page, href):
    """/football/action/futures -- the season book, conference to club."""
    pending, fut_multis = page["pending"], page["fut_multis"]
    images, games = page["images"], page["games"]

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

    out = ['<div class="fb">', '''<div class="mast">
  <div class="eyebrow condensed">Baker\'s Action</div>
  <h3 class="condensed">NFL Futures</h3>
</div>''']
    out.append(render_pager(page["nav"], "futures", href))
    out.append(render_totals(len(board), staked(board), won(board)))
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
#
# There are three templates and they are the three build_*_html functions above:
# a grid of slates, a week of the game book, and the season board. What differs
# between the pages is the board, and that is where the difference lives.
#
# The chrome around a board does NOT differ -- the same head, the same nav
# mounts, the same breadcrumb strip, with four substitutions -- so it is one
# shell file rather than three identical copies, which is the whole complaint
# about the twenty generated pages restated one level up. page.html is the
# routed page; standalone.html is the self-contained copy that opens off the
# filesystem and publishes as an Artifact.
#
# They are files rather than triple-quoted constants so build.py's cache-busting
# can reach the asset URLs in their <head>, and they sit inside api/ so they are
# bundled with the function that reads them.

TPL_DIR = os.path.dirname(os.path.abspath(__file__))

_TEMPLATES = {}


def load_template(name):
    """The named template, read once per warm instance."""
    if name not in _TEMPLATES:
        with open(os.path.join(TPL_DIR, f"{name}.html")) as f:
            _TEMPLATES[name] = f.read()
    return _TEMPLATES[name]


def wrap(template, board, title, head, crumb):
    return (template.replace("%%BOARD%%", board)
            .replace("%%CRUMBS%%", crumb).replace("%%HEAD%%", head)
            .replace("%%TITLE%%", title))


BOARDS = {"index": build_index_html,
          "slate": build_slate_html,
          "futures": build_futures_html}


def asset_images(shas):
    """{image key: /assets/action/<sha>.png} for the committed artwork.

    An empty sha stays an empty string, which is what thumb() reads as "no art
    for this row" and draws the placeholder for. That is the graceful degrade
    for a headshot whose file has not been committed and pushed yet."""
    return {key: (f"/assets/action/{sha}.png" if sha else "")
            for key, sha in (shas or {}).items()}


def render_page(page, href=route, template=None):
    """A page model -> a whole HTML document.

    `page["images"]` must already map image keys to <img src> values; use
    asset_images() for the site, or an inliner for the standalone copy."""
    board = BOARDS[page["kind"]](page, href)
    tpl = template if template is not None else load_template("page")
    return wrap(tpl, board, page["title"], page["head"],
                crumbs(page["slug"], page["label"]))
