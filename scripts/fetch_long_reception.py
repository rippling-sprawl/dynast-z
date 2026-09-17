#!/usr/bin/env python3
"""
Build the longest-reception board behind /football/long-reception:
data/nfl_long_reception_2026.json.

Why this exists
---------------
A sportsbook posts "Longest Reception 25+" as a ladder of milestone prices, and
the honest question a bettor has is whether the ladder is right. Answering it
needs a likelihood that does not come from the ladder, or the answer is just the
book's own number rearranged.

So the likelihood is built from play-by-play instead. Two things decide whether
a receiver breaks a long one: how often he catches it, and how far it goes when
he does. The second is the durable half, and it is estimable even for a player
who has never caught a 40-yarder:

    S(x)        pooled survival of catch yardage, measured across every catch in
                the window. Its tail is heavier than exponential (the implied
                scale drifts from ~8.7 yards at the 10-20 rungs to ~14 at 45-50),
                so it is used empirically rather than assumed.

    alpha       one exponent per receiver: S_player(x) = S(x) ** alpha. Because
                S(Y) ~ Beta(alpha, 1), the MLE is n / -sum(ln S(y)) — which uses
                EVERY catch, not just the rare long ones. That is the whole
                trick: the median pass-catcher has two 40+ catches in three
                seasons, so counting tail events estimates nothing, while the
                shape of his whole distribution estimates it fine.
                Reported to the page as a big-play index, 1/alpha.

    lambda(x)   catches-per-game * S(x)**alpha * defense, both player terms
                shrunk toward position means. P(longest >= x) = 1 - exp(-lambda).

A gamma-mixed Poisson was tested for overdispersion and lost to plain Poisson
out of sample, so plain Poisson is what ships, with one global lambda scale
fit on a held-out season.

Validation
----------
Fit on 2024 alone, predict every 2025 player-game it had never seen. The deciles
are the test that matters and nothing in them is tuned; the aggregate level is
partly fit, since the global scale was chosen on that same season. Both go into
the meta file and onto the page, because a model that shows its own calibration
is the only kind worth betting.

Weeks
-----
A capture is one week's slate, and the file keeps every week it has ever been
handed rather than only the last one. Each week is a frozen snapshot — its
matchups, its prices, and the defense table that priced them — so rebuilding
week 3 cannot move week 2's numbers, even though the play-by-play underneath
has grown by a week in between. A rebuild rewrites only the weeks present in
the capture it is given; every other week is copied through untouched.

Which week a capture belongs to is read off its kickoffs against
data/nfl_schedule_2026.json rather than passed in, so this file and
/football/schedule can never disagree about where a week ends. A capture that
straddles two — a Thursday game posted early — writes a snapshot for each.

Defense
-------
Per-season rates first, THEN the 20/50/30 blend across 2024/2025/2026 — pooling
raw counts instead would hand the current season a weight of a few percent
rather than the 30 it is supposed to carry. Split by receiver position and
shrunk toward the team's overall rate, so a defense can be soft to tight ends
and stingy to outside receivers.

Inputs
------
    nflverse play-by-play, one release per season (cached in /cache):
        https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{season}.csv.gz
    nflverse player index, for names and positions:
        https://github.com/nflverse/nflverse-data/releases/download/players/players.csv
    data/imports/long_reception.json
        a DraftKings Recorder bundle of the longest-reception subcategory. The
        market is not in any odds API — balldontlie carries 18 NFL prop types
        and this is not one of them — so the prices can only arrive by capture.
    balldontlie (optional, needs BALLDONTLIE_API_KEY)
        /games and /odds/player_props, used ONLY to learn which pass-catchers
        are active in the games DraftKings has not priced. Those players get a
        likelihood and no edge.

Usage
-----
    python3 scripts/fetch_long_reception.py
    python3 scripts/fetch_long_reception.py --no-bdl      # skip the unpriced games
    python3 scripts/fetch_long_reception.py --keep-pbp    # leave the CSVs in /cache
    python3 scripts/fetch_long_reception.py --import data/imports/lr_w2.json
                                                          # rebuild one week from a
                                                          # bundle kept aside
"""

from __future__ import annotations

import argparse
import collections
import csv
import datetime
import gzip
import io
import json
import math
import os
import re
import statistics
import subprocess
import sys

SEASONS = ("2024", "2025", "2026")     # the model's history window
SEASON = 2026                          # the season being priced
WEIGHT = {"2024": 0.20, "2025": 0.50, "2026": 0.30}
GRID = [10, 15, 20, 25, 30, 35, 40, 45]

# Shrinkage strengths, in catches and in games. Both are deliberately gentle:
# they exist to stop a two-catch rookie reporting a position average as if it
# were evidence, not to pull established receivers toward the middle.
K_ALPHA, K_RATE = 15.0, 5.0
# A player below this has no usable history. The board flags them and hides them
# by default rather than pretending: ungated, the largest "edge" on the slate
# belongs to a receiver with zero career catches.
GATE_GAMES, GATE_CATCHES = 8, 25

PBP_URL = ("https://github.com/nflverse/nflverse-data/releases/download/pbp/"
           "play_by_play_{season}.csv.gz")
PLAYERS_URL = ("https://github.com/nflverse/nflverse-data/releases/download/"
               "players/players.csv")

FULL = {'ARI': 'Cardinals', 'ATL': 'Falcons', 'BAL': 'Ravens', 'BUF': 'Bills', 'CAR': 'Panthers',
        'CHI': 'Bears', 'CIN': 'Bengals', 'CLE': 'Browns', 'DAL': 'Cowboys', 'DEN': 'Broncos',
        'DET': 'Lions', 'GB': 'Packers', 'HOU': 'Texans', 'IND': 'Colts', 'JAX': 'Jaguars',
        'KC': 'Chiefs', 'LA': 'Rams', 'LAR': 'Rams', 'LAC': 'Chargers', 'LV': 'Raiders',
        'MIA': 'Dolphins', 'MIN': 'Vikings', 'NE': 'Patriots', 'NO': 'Saints', 'NYG': 'Giants',
        'NYJ': 'Jets', 'PHI': 'Eagles', 'PIT': 'Steelers', 'SEA': 'Seahawks', 'SF': '49ers',
        'TB': 'Buccaneers', 'TEN': 'Titans', 'WAS': 'Commanders'}
FIELDS = ('20', '40', 'WR20', 'WR40', 'TE20', 'TE40', 'RB20', 'RB40')


def repo_path(*parts):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", *parts)


def curl_bytes(url):
    """GitHub release assets 302 to a signed S3 URL, so follow redirects."""
    out = subprocess.run(["curl", "-sL", "--fail", url], capture_output=True)
    if out.returncode != 0:
        raise SystemExit(f"fetch failed: {url}\n{out.stderr.decode()[:400]}")
    return out.stdout


def cached(name, url, keep=True):
    path = repo_path("cache", name)
    if os.path.exists(path):
        print(f"  using cached {name}")
        return open(path, "rb").read()
    print(f"  downloading {url}")
    blob = curl_bytes(url)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if keep:
        with open(path, "wb") as f:
            f.write(blob)
    return blob


# ----------------------------------------------------------------- play-by-play

def reduce_pbp(keep_pbp):
    """Three seasons of pbp down to per-player catch lists and per-defense counts.

    Everything downstream reads this, not the ~200MB of CSV it came from.
    """
    csv.field_size_limit(10 ** 7)
    pos, nm = {}, {}
    blob = cached("nflverse_players.csv", PLAYERS_URL)
    for r in csv.DictReader(io.StringIO(blob.decode("utf-8", "replace"))):
        if r.get("gsis_id"):
            pos[r["gsis_id"]] = r.get("position") or "OTH"
            nm[r["gsis_id"]] = r.get("display_name") or ""

    def grp(p):
        return p if p in ("WR", "TE", "RB") else "OTH"

    catches = collections.defaultdict(list)      # (pid, season) -> [yards]
    tgames = collections.defaultdict(set)        # (pid, season) -> {game_id} targeted
    plong = collections.defaultdict(dict)        # (pid, season) -> {game_id: longest}
    dcnt = collections.defaultdict(collections.Counter)
    dgames = collections.defaultdict(set)

    for season in SEASONS:
        raw = cached(f"play_by_play_{season}.csv.gz", PBP_URL.format(season=season),
                     keep=keep_pbp)
        text = gzip.decompress(raw).decode("utf-8", "replace")
        n = 0
        for r in csv.DictReader(io.StringIO(text)):
            if r["season_type"] != "REG":
                continue
            d = FULL.get(r["defteam"], r["defteam"])
            if d:
                dgames[(d, season)].add(r["game_id"])
            pid = r["receiver_player_id"]
            if not pid:
                continue
            if r["pass_attempt"] == "1":
                tgames[(pid, season)].add(r["game_id"])
            if r["complete_pass"] != "1":
                continue
            try:
                y = float(r["receiving_yards"] or r["yards_gained"] or 0)
            except ValueError:
                continue
            catches[(pid, season)].append(y)
            g = plong[(pid, season)]
            g[r["game_id"]] = max(g.get(r["game_id"], -99), y)
            n += 1
            P = grp(pos.get(pid, "OTH"))
            if y >= 20:
                dcnt[(d, season)]["20"] += 1
                dcnt[(d, season)][P + "20"] += 1
            if y >= 40:
                dcnt[(d, season)]["40"] += 1
                dcnt[(d, season)][P + "40"] += 1
        print(f"  {season}: {n:,} catches, {len({k[0] for k in catches if k[1] == season})} receivers")

    return dict(
        players={f"{pid}|{s}": dict(y=sorted(v), g=len(tgames[(pid, s)]),
                                    lng=sorted(plong[(pid, s)].values()),
                                    nm=nm.get(pid, ""), pos=grp(pos.get(pid, "OTH")))
                 for (pid, s), v in catches.items()},
        defense={f"{d}|{s}": {k: int(v) for k, v in c.items()} for (d, s), c in dcnt.items()},
        dgames={f"{d}|{s}": len(v) for (d, s), v in dgames.items()})


# ------------------------------------------------------------------- the model

def pool_survival(D, seasons):
    """Weighted empirical survival of catch yardage, as a 1-yard lookup."""
    buckets, tot = collections.Counter(), 0.0
    for k, v in D["players"].items():
        s = k.split("|")[1]
        if s not in seasons:
            continue
        w = seasons[s]
        for y in v["y"]:
            buckets[int(math.floor(y))] += w
            tot += w
    lo, hi = min(buckets), max(buckets)
    surv, run = {}, 0.0
    for x in range(hi, lo - 1, -1):
        run += buckets.get(x, 0.0)
        surv[x] = run / tot
    # Exponential extrapolation past the longest catch on record, so a 45+ rung
    # for a receiver whose own longest is 44 still gets a number.
    top = [x for x in range(hi - 25, hi + 1) if surv.get(x, 0) > 0]
    th = 12.0
    if len(top) > 5 and surv[top[0]] > surv[top[-1]] > 0:
        th = (top[-1] - top[0]) / math.log(surv[top[0]] / surv[top[-1]])

    def S(x):
        xi = int(math.floor(x))
        if xi <= lo:
            return 1.0
        if xi <= hi:
            return max(surv[xi], 1e-6)
        return max(surv[hi] * math.exp(-(xi - hi) / th), 1e-9)
    return S


def fit_players(D, seasons):
    S = pool_survival(D, seasons)
    raw = {}
    for k, v in D["players"].items():
        pid, s = k.split("|")
        if s not in seasons or not v["g"]:
            continue
        w = seasons[s]
        T = sum(-math.log(S(y)) for y in v["y"])
        r = raw.setdefault(pid, dict(W=0.0, T=0.0, n=0.0, g=0.0, rs=0.0, ws=0.0,
                                     nm=v["nm"], pos=v["pos"], gr=0))
        r["W"] += w * len(v["y"])
        r["T"] += w * T
        r["rs"] += w * (len(v["y"]) / v["g"])     # per-season rate, weighted
        r["ws"] += w
        r["n"] += w * len(v["y"])
        r["g"] += w * v["g"]
        r["gr"] += v["g"]

    byp = collections.defaultdict(lambda: dict(W=0., T=0., n=0., g=0.))
    for v in raw.values():
        p = byp[v["pos"]]
        for f in ("W", "T", "n", "g"):
            p[f] += v[f]
    prior = {p: dict(alpha=(v["W"] / v["T"] if v["T"] > 0 else 1.0),
                     rate=(v["n"] / v["g"] if v["g"] > 0 else 3.0))
             for p, v in byp.items()}

    out = {}
    for pid, v in raw.items():
        pr = prior.get(v["pos"], dict(alpha=1.0, rate=3.0))
        alpha = (v["W"] + K_ALPHA) / (v["T"] + K_ALPHA / pr["alpha"])
        r_raw = v["rs"] / v["ws"] if v["ws"] else pr["rate"]
        g_eff = v["g"] / v["ws"] if v["ws"] else 0.0
        rate = (r_raw * g_eff + K_RATE * pr["rate"]) / (g_eff + K_RATE)
        out[pid] = dict(alpha=alpha, rate=rate, nm=v["nm"], pos=v["pos"],
                        games=v["gr"], catches=int(round(v["n"] / max(seasons.values()))))
    return out, S, prior


def fit_defense(D, seasons):
    """Per-season rates, THEN the weighted blend -- see the module docstring."""
    per, lgs = collections.defaultdict(dict), {}
    for key, g in D["dgames"].items():
        d, s = key.split("|")
        if s not in seasons or not g:
            continue
        c = D["defense"].get(key, {})
        per[d][s] = {f: c.get(f, 0) / g for f in FIELDS}
    for s in seasons:
        tot, n = collections.Counter(), 0
        for d in per:
            if s in per[d]:
                n += 1
                for f, v in per[d][s].items():
                    tot[f] += v
        lgs[s] = {f: (tot[f] / n if n else 0.0) for f in FIELDS}

    out = {}
    for d, byseason in per.items():
        W = sum(seasons[s] for s in byseason)
        rate, lgrate, cnt = {}, {}, collections.Counter()
        for f in FIELDS:
            rate[f] = sum(seasons[s] * byseason[s][f] for s in byseason) / W
            lgrate[f] = sum(seasons[s] * lgs[s][f] for s in byseason) / W
            cnt[f] = sum(D["defense"].get(f"{d}|{s}", {}).get(f, 0) for s in byseason)
        e = dict(rate20=rate["20"], rate40=rate["40"])
        for f in ("20", "40"):
            e["m" + f] = rate[f] / lgrate[f] if lgrate[f] else 1.0
        for P in ("WR", "TE", "RB"):
            for f in ("20", "40"):
                k = P + f
                ratio = rate[k] / lgrate[k] if lgrate[k] else 1.0
                e["m" + k] = (cnt[k] * ratio + 10 * e["m" + f]) / (cnt[k] + 10)
        out[d] = e
    lg = {f: sum(lgs[s][f] * seasons[s] for s in seasons) / sum(seasons.values())
          for f in ("20", "40")}
    return out, lg


def lam(pl, S, x, mult=1.0):
    return pl["rate"] * (S(x) ** pl["alpha"]) * mult


def defense_mult(d, pos, x):
    """20+ multiplier at or below 20, 40+ at or beyond 40, log-interpolated between."""
    if pos not in ("WR", "TE", "RB"):
        pos = "WR"
    m20, m40 = d["m" + pos + "20"], d["m" + pos + "40"]
    if x <= 20:
        return m20
    if x >= 40:
        return m40
    w = (x - 20) / 20.0
    return math.exp((1 - w) * math.log(max(m20, 1e-6)) + w * math.log(max(m40, 1e-6)))


def backtest(D):
    """Fit 2024, predict 2025. Returns (calibration, global lambda scale)."""
    tr, S, _ = fit_players(D, {"2024": 1.0})
    ev = []
    for k, v in D["players"].items():
        pid, s = k.split("|")
        if s == "2025" and pid in tr:
            ev.extend((tr[pid], L) for L in v["lng"])

    def logloss(c, xs=(10, 15, 20, 25, 30, 40)):
        t, n = 0.0, 0
        for pl, L in ev:
            for x in xs:
                p = min(max(1 - math.exp(-lam(pl, S, x) * c), 1e-6), 1 - 1e-6)
                t += -(math.log(p) if L >= x else math.log(1 - p))
                n += 1
        return t / n

    cal = min((round(0.90 + 0.02 * i, 2) for i in range(16)), key=logloss)
    bands = []
    for x in (10, 15, 20, 25, 30, 40):
        bands.append(dict(x=x,
                          pred=round(statistics.mean(1 - math.exp(-lam(pl, S, x) * cal) for pl, _ in ev), 4),
                          act=round(statistics.mean(1 if L >= x else 0 for _, L in ev), 4)))
    rows = sorted((1 - math.exp(-lam(pl, S, 20) * cal), 1 if L >= 20 else 0) for pl, L in ev)
    B, dec = len(rows) // 10, []
    for i in range(10):
        ch = rows[i * B:(i + 1) * B if i < 9 else len(rows)]
        dec.append(dict(d=i + 1,
                        pred=round(statistics.mean(r[0] for r in ch), 4),
                        act=round(statistics.mean(r[1] for r in ch), 4), n=len(ch)))
    return dict(bands=bands, deciles=dec, n=len(ev),
                players=len({id(p) for p, _ in ev}), cal=cal), cal


# ------------------------------------------------------------------ the prices

ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?")


def to_utc(s):
    """DraftKings stamps seven fractional digits, the schedule stamps no seconds
    at all, and fromisoformat wants exactly one shape. Read the fields instead."""
    m = ISO.match(s or "")
    if not m:
        return None
    f = [int(g or 0) for g in m.groups()]
    return datetime.datetime(f[0], f[1], f[2], f[3], f[4], f[5],
                             tzinfo=datetime.timezone.utc)


def week_windows():
    """[start, end) per week, straight from the committed schedule.

    From there rather than inferred from the kickoffs in hand, so that a week
    boundary means the same thing here as on /football/schedule — which picks
    "this week" out of these same windows, as does the board.
    """
    sched = json.load(open(repo_path("data", f"nfl_schedule_{SEASON}.json")))
    return [dict(week=w["week"], start=w["start"], end=w["end"]) for w in sched["weeks"]]


def week_of(windows, iso):
    """The week a kickoff falls in, or None if it falls outside the season."""
    d = to_utc(iso)
    if d is None:
        return None
    for w in windows:
        if to_utc(w["start"]) <= d < to_utc(w["end"]):
            return w["week"]
    return None


SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b")


def norm(s):
    s = s.lower().replace(".", "").replace("'", "").replace("-", " ")
    return " ".join(SUFFIX.sub("", s).split())


def read_capture(path):
    """A DraftKings Recorder bundle -> (captured_at, [{name, team, opp, lng, game, lines}]).

    The capture time rides along because it is the only provenance a frozen week
    keeps: the bundle itself is a drop spot that the next week overwrites.
    """
    bundle = json.load(open(path))
    events, markets, selections = {}, {}, collections.defaultdict(list)
    for cap in bundle.get("captures", []):
        body = cap.get("body") or {}
        for e in body.get("events", []):
            events[e["id"]] = e
        for m in body.get("markets", []):
            markets[m["id"]] = m
        for s in body.get("selections", []):
            selections[s["marketId"]].append(s)

    out = []
    for mid, m in markets.items():
        e = events.get(m.get("eventId"))
        if not e or not selections.get(mid):
            continue
        sides = {p["venueRole"]: p["metadata"]["rosettaTeamName"] for p in e["participants"]}
        venue = "Home" if "|8:Home|" in (m.get("correlatedId") or "") else "Away"
        team = sides.get(venue)
        opp = sides.get("Away" if venue == "Home" else "Home")
        first = selections[mid][0]
        part = (first.get("participants") or [{}])[0]
        stat = part.get("statistic") or {}
        name = re.sub(r"\s+Longest Reception$", "", m["name"])
        lines = sorted((s["milestoneValue"], float(s["trueOdds"])) for s in selections[mid])
        out.append(dict(n=part.get("name") or name, tm=team, op=opp, v=venue,
                        lng=stat.get("value"),
                        g=f"{sides.get('Away')} @ {sides.get('Home')}",
                        ko=e.get("startEventDate", "").replace(".0000000Z", "Z"),
                        L=lines))
    ts = bundle.get("capturedAt")
    captured = (datetime.datetime.fromtimestamp(ts / 1000, datetime.timezone.utc)
                .replace(microsecond=0).isoformat() if ts else None)
    return captured, out


def unpriced_games(priced_games, week):
    """Pass-catchers in that week's games nobody posted this market for, via balldontlie.

    Returns [] when the key is missing -- the board simply covers fewer games.
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import bdl_common as b
        if not b.api_key(required=False):
            print("  no BALLDONTLIE_API_KEY -- skipping the unpriced games")
            return [], []
    except Exception as exc:
        print(f"  balldontlie unavailable ({exc}) -- skipping the unpriced games")
        return [], []

    games = list(b.paginate("/games", {"seasons[]": [SEASON], "weeks[]": [week]}, quiet=True))
    players = {str(p["id"]): p for p in b.paginate("/players/active", None, quiet=True)}
    PASS = {"Wide Receiver": "WR", "Tight End": "TE", "Running Back": "RB", "Fullback": "RB"}
    rows, metas = [], []
    for g in games:
        v, h = g["visitor_team"], g["home_team"]
        label = f"{v['name']} @ {h['name']}"
        if label in priced_games:
            continue
        metas.append(dict(g=label, ko=g["date"].replace(".000Z", "Z"),
                          away=v["name"], home=h["name"], nomkt=True))
        seen = set()
        for r in b.paginate("/odds/player_props", {"game_id": g["id"]}, quiet=True):
            pid = str(r["player_id"])
            if pid in seen:
                continue
            p = players.get(pid)
            if not p or p.get("position") not in PASS:
                continue
            seen.add(pid)
            abbr = (p.get("team") or {}).get("abbreviation")
            if abbr == h["abbreviation"]:
                tm, op, ven = h["name"], v["name"], "Home"
            elif abbr == v["abbreviation"]:
                tm, op, ven = v["name"], h["name"], "Away"
            else:
                continue
            rows.append(dict(n=f"{p['first_name']} {p['last_name']}", tm=tm, op=op, v=ven,
                             lng=None, g=label, ko=metas[-1]["ko"], L=[],
                             pos=PASS[p["position"]]))
    return rows, metas


# -------------------------------------------------------------------- the weeks

def price_rows(priced, extra, PL, PRIOR, S, DEF, CAL, idx):
    """One week's players, each with a likelihood at every rung on the grid.

    `priced` came from the book, `extra` from balldontlie — they differ only in
    whether there is a ladder to have an edge against, so they are priced by the
    same pass.
    """
    rows = []
    for r in priced + extra:
        cands = idx.get(norm(r["n"]), [])
        pl = PL[max(cands, key=lambda q: PL[q]["games"])] if cands else None
        pos = (pl or {}).get("pos") or r.get("pos") or "WR"
        if pos not in ("WR", "TE", "RB"):
            pos = r.get("pos") if r.get("pos") in ("WR", "TE", "RB") else "WR"
        if not pl:
            pr = PRIOR.get(pos, dict(alpha=1.0, rate=3.0))
            pl = dict(alpha=pr["alpha"], rate=pr["rate"], games=0, catches=0)
        d = DEF[r["op"]]
        P = {str(x): round(1 - math.exp(-lam(pl, S, x, defense_mult(d, pos, x)) * CAL), 4)
             for x in GRID}
        rows.append(dict(n=r["n"], tm=r["tm"], op=r["op"], v=r["v"], lng=r["lng"], g=r["g"],
                         L=r["L"], P=P, pos=pos, alpha=round(pl["alpha"], 3),
                         rate=round(pl["rate"], 2), games=pl["games"],
                         catches=pl["catches"], nomkt=not r["L"]))
    return rows


def kept_weeks(path, windows):
    """Whatever the last build left behind, keyed by week.

    Read back and written out untouched — that copy is the whole of the freeze.
    A week's numbers are the model as it stood when that week was priced, and
    re-deriving them from today's play-by-play would silently rewrite history
    every Tuesday.
    """
    if not os.path.exists(path):
        return {}
    try:
        doc = json.load(open(path))
    except ValueError as exc:
        print(f"  existing board unreadable ({exc}); starting fresh")
        return {}
    weeks = doc.get("weeks")
    if not isinstance(weeks, list):
        # The one-week shape this file had before it carried weeks at all.
        if not doc.get("rows"):
            return {}
        weeks = [dict(week=doc.get("week"), captured=None, games=doc.get("games", []),
                      rows=doc["rows"], teams=doc.get("teams", {}))]
    win = {w["week"]: w for w in windows}
    out = {}
    for w in weeks:
        n = w.get("week")
        if n is None:
            continue
        w.setdefault("start", win.get(n, {}).get("start"))
        w.setdefault("end", win.get(n, {}).get("end"))
        out[n] = w
    return out


# ------------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--import", dest="bundle", metavar="PATH",
                    help="a capture other than data/imports/long_reception.json")
    ap.add_argument("--no-bdl", action="store_true", help="skip the unpriced games")
    ap.add_argument("--keep-pbp", action="store_true", help="leave the season CSVs in /cache")
    args = ap.parse_args()

    print("Reducing play-by-play ...")
    D = reduce_pbp(args.keep_pbp)

    print("\nBacktesting (fit 2024, predict 2025) ...")
    bt, CAL = backtest(D)
    print(f"  global lambda scale {CAL}; 20+ decile 1 {bt['deciles'][0]['act']:.1%} "
          f"-> decile 10 {bt['deciles'][9]['act']:.1%} over {bt['n']:,} player-games")

    PL, S, PRIOR = fit_players(D, WEIGHT)
    DEF, LG = fit_defense(D, WEIGHT)
    idx = collections.defaultdict(list)
    for pid, v in PL.items():
        idx[norm(v["nm"])].append(pid)

    print("\nReading the DraftKings capture ...")
    bundle = args.bundle or repo_path("data", "imports", "long_reception.json")
    captured, priced = read_capture(bundle)
    windows = week_windows()
    byweek = collections.defaultdict(list)
    for r in priced:
        w = week_of(windows, r["ko"])
        if w is None:
            print(f"  {r['g']} kicks outside every week window -- skipped")
            continue
        byweek[w].append(r)
    if not byweek:
        raise SystemExit(f"no priced games in {bundle}")
    print(f"  {len(priced)} players, {sum(len(r['L']) for r in priced)} priced lines, "
          f"week {', '.join(str(w) for w in sorted(byweek))}")

    # The defense table as it stands right now. Every week built by this run
    # carries its own copy, so the multipliers a past week was priced under stay
    # readable next to the prices they moved.
    teams_now = {t: dict(m20=round(v["m20"], 4), m40=round(v["m40"], 4),
                         rate20=round(v["rate20"], 3), rate40=round(v["rate40"], 3),
                         **{"m" + P + f: round(v["m" + P + f], 3)
                            for P in ("WR", "TE", "RB") for f in ("20", "40")})
                 for t, v in DEF.items()}
    win = {w["week"]: w for w in windows}

    fresh = {}
    for wk in sorted(byweek):
        slate = byweek[wk]
        games = {}
        for r in slate:
            games.setdefault(r["g"], dict(g=r["g"], ko=r["ko"], nomkt=False,
                                          away=r["g"].split(" @ ")[0],
                                          home=r["g"].split(" @ ")[1]))
        extra, extra_games = ([], []) if args.no_bdl else unpriced_games(set(games), wk)
        if extra:
            print(f"  week {wk}: balldontlie adds {len(extra)} pass-catchers across "
                  f"{len(extra_games)} unpriced games")
        rows = price_rows(slate, extra, PL, PRIOR, S, DEF, CAL, idx)
        fresh[wk] = dict(
            week=wk, start=win[wk]["start"], end=win[wk]["end"], captured=captured,
            games=sorted(list(games.values()) + extra_games, key=lambda x: x["ko"]),
            rows=rows, teams=teams_now)

    out = repo_path("data", f"nfl_long_reception_{SEASON}.json")
    board = kept_weeks(out, windows)
    held = sorted(w for w in board if w not in fresh)
    board.update(fresh)
    weeks = [board[k] for k in sorted(board)]
    if held:
        print(f"  week {', '.join(str(w) for w in held)} carried through unchanged")

    # Full name -> the abbreviation to print, so a dense table can say
    # "DAL vs WSH" without every consumer keeping its own copy of the mapping.
    #
    # Taken from data/nfl_schedule_2026.json rather than derived from FULL,
    # because that file is what the team picker and every other football
    # surface spell teams from, and play-by-play does not always agree with it
    # -- pbp writes Washington WAS and the Rams both LA and LAR, the site says
    # WSH and LAR. Two pages naming the same team differently is a bug a reader
    # notices before we do. FULL only fills a gap if the schedule ever lacks one.
    abbr = {}
    for a, n in FULL.items():
        if len(a) > len(abbr.get(n, "")):
            abbr[n] = a
    try:
        sched = json.load(open(repo_path("data", f"nfl_schedule_{SEASON}.json")))
        for t in sched.get("teams", []):
            if t.get("short") and t.get("abbr"):
                abbr[t["short"]] = t["abbr"]
    except (OSError, ValueError) as exc:
        print(f"  schedule abbreviations unavailable ({exc}); using play-by-play spellings")
    doc = dict(
        season=SEASON, grid=GRID, gate=[GATE_GAMES, GATE_CATCHES], cal=CAL,
        abbr=abbr,
        lg20=round(LG["20"], 3), lg40=round(LG["40"], 3),
        backtest=bt, weeks=weeks)

    with open(out, "w") as f:
        json.dump(doc, f, separators=(",", ":"))

    def gated(rows):
        return sum(1 for r in rows if r["games"] >= GATE_GAMES and r["catches"] >= GATE_CATCHES)

    meta = dict(
        sources=dict(
            onField=[PBP_URL.format(season=s) for s in SEASONS],
            players=PLAYERS_URL,
            prices="data/imports/long_reception.json (DraftKings Recorder bundle)",
            rosters="https://api.balldontlie.io/nfl/v1 (/games, /players/active, /odds/player_props)"),
        season=SEASON, latest_week=weeks[-1]["week"],
        weeks=[dict(week=w["week"], captured=w.get("captured"),
                    games=len(w["games"]),
                    priced_games=sum(1 for g in w["games"] if not g["nomkt"]),
                    players=len(w["rows"]), gated_players=gated(w["rows"]),
                    priced_players=sum(1 for r in w["rows"] if not r["nomkt"]),
                    lines=sum(len(r["L"]) for r in w["rows"]),
                    rebuilt=w["week"] in fresh)
               for w in weeks],
        history_seasons=[int(s) for s in SEASONS], season_weights=WEIGHT,
        catch_count=sum(len(v["y"]) for v in D["players"].values()),
        receiver_count=len(PL),
        lambda_scale=CAL, sample_gate=dict(games=GATE_GAMES, catches=GATE_CATCHES),
        backtest=dict(n=bt["n"], players=bt["players"],
                      decile_1=bt["deciles"][0]["act"], decile_10=bt["deciles"][9]["act"]),
        league=dict(explosive20PerGame=round(LG["20"], 3),
                    explosive40PerGame=round(LG["40"], 3)),
        size_bytes=os.path.getsize(out),
        fetched_at=datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
        fetched_ts=int(datetime.datetime.now(datetime.timezone.utc).timestamp()))
    with open(repo_path("data", f"nfl_long_reception_{SEASON}_meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
        f.write("\n")
    print(f"\nwrote data/nfl_long_reception_{SEASON}.json "
          f"({meta['size_bytes'] / 1000:.0f} KB) — {len(weeks)} week"
          f"{'s' if len(weeks) != 1 else ''}, "
          + ", ".join(f"w{w['week']} {w['players']} players/{w['lines']} lines"
                      for w in meta["weeks"]))


if __name__ == "__main__":
    main()
