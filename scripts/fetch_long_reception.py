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

    S_pos(x)    survival of catch yardage, measured empirically across every
                catch in the window and measured SEPARATELY for WR, TE and RB.
                Its tail is heavier than exponential (the implied scale drifts
                from ~8.7 yards at the 10-20 rungs to ~14 at 45-50), so it is
                used empirically rather than assumed.

                One curve for all three positions was the model's worst error.
                A back is not a short receiver: his bulk is far shorter (S(10)
                .29 against a receiver's .50) while his 40-yard tail matches a
                tight end's, because a back's long ones are screens that break
                rather than routes run deep. No single exponent on a shared
                curve holds both ends, and the end it dropped was the tail --
                see Validation. Everyone who is not WR/TE/RB keeps the league
                curve.

    alpha       one exponent per receiver, against his own position's curve:
                S_player(x) = S_pos(x) ** alpha. Because S(Y) ~ Beta(alpha, 1),
                the MLE is n / -sum(ln S_pos(y)) — which uses EVERY catch, not
                just the rare long ones. That is the whole trick: the median
                pass-catcher has two 40+ catches in three seasons, so counting
                tail events estimates nothing, while the shape of his whole
                distribution estimates it fine. Reported to the page as a
                big-play index, 1/alpha — now read within position, so a back
                at 1.0 is an ordinary back rather than an ordinary receiver.

    ADOT        average depth of target, and the prior alpha is shrunk toward.
                Measured over targets rather than catches, which is the point:
                a receiver's catch list can only describe balls he caught, so
                the deep threat who ran twelve go routes and caught three looks
                to it like a man with three catches. His air yards remember the
                other nine. Pooled across positions the slope is -0.075 to
                -0.088 of log alpha per yard on the two fits available, stable
                where a per-position fit is not, so one pooled number is used.

                It is a PRIOR and not a correction. Applied on top of a
                receiver's own alpha it loses monotonically, because his catch
                yardage already carries his depth and the tilt double-counts
                it. Shrunk toward, it speaks loudest for the receiver whose own
                catch list says least — which is the deep threat with two
                catches, exactly the case alpha alone reads worst.

    lambda(x)   catches-per-game * S_pos(x)**alpha * defense, both player terms
                shrunk toward position means. P(longest >= x) = 1 - exp(-lambda).

                The catches-per-game half is a question about this Sunday, not
                about three seasons: two catches is two chances at a long one
                and eight is eight, and which it will be turns on a depth
                chart, an injury report and a game script that no history
                carries. So where a receptions line is posted, it sets most of
                that term — see Volume.

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

Calibration is also reported per position, which is what caught the shared
curve. Predicted/actual on that held-out season, before -> after splitting it:

    RB 20+   0.76 -> 0.98        WR 40+   1.20 -> 1.07
    RB 25+   0.52 -> 0.83        TE 40+   1.80 -> 1.09
    RB 30+   0.44 -> 0.82

Weighted by the rungs this market actually posts, mean |log(pred/act)| falls
0.048 -> 0.036, and log-loss 0.4700 -> 0.4673. Every position lands inside 7%
at every rung through 20 -- though "through 20" undersells what this market
asks: of 597 lines in the first capture, 39% sit at 25+ and 9% at 35+, so the
tail is not a rounding error here.

Shrinkage and ADOT, on the same held-out season and scored at the rungs in the
proportions the book posts them:

                                    log-loss   mean |log(p/a)|   40+ by position
    K_ALPHA 15, flat prior           0.50647       0.0223       WR 1.07 TE 1.09 RB .44
    K_ALPHA 80, flat prior           0.50436       0.0305       WR 1.01 TE 0.98 RB .39
    K_ALPHA 80, ADOT prior           0.50358       0.0262       WR 1.06 TE 1.05 RB .41

Heavier shrinkage is the larger and the sounder half: it is worth 0.002 of
log-loss here and 0.005 on the reverse fit, and it follows from the carryover
coefficient rather than from a sweep. What it costs is the tail, which it
flattens -- aggregate |log(pred/act)| nearly doubles. The ADOT prior is what
buys most of that back, because depth is exactly the thing a flat prior throws
away and a tail is made of.

ADOT's own contribution is small and its sign is not stable: +0.0008 of
log-loss on this split, -0.0025 on the reverse. It is kept on the mechanism
rather than the number. Regress 2025 alpha on 2024 alpha and 2024 ADOT together
and ADOT carries the larger coefficient of the two, which says depth is the
more durable half of shape; and the receiver it can say the most about is the
one with a handful of catches and a deep route tree, who is precisely the
receiver alpha alone reads worst. Where that shows up is thin players, whose
log-loss improves 0.48845 -> 0.48574 while everyone else's barely moves.

Both changes together, on the first week priced under them: the median line's
likelihood moves 2.3 points, the 90th percentile 7.5, and 61 of 597 lines cross
from one side of zero edge to the other.

What survives is the back's deep tail: 25+ runs 0.83 of actual and 30+ 0.82,
so the rare back priced that deep -- three lines in the first capture, all of
them McCaffrey and Bijan -- reads light, and a negative edge there is likelier
to be the model than the price. It is left alone deliberately. Fattening that
tail was tried three ways (blending the position curve toward the league one,
integrating the Gamma posterior for alpha instead of plugging in its mean, a
per-position lambda scale) and each bought the back's tail by breaking the
tight end's, which was calibrated: TE 40+ went 1.09 -> 1.78 for a log-loss
gain of 0.0003. A shared curve is exactly the trade this model just stopped
making, so it is not worth remaking in the other direction.

Volume
------
How far a catch goes is the model's own; how many catches there are is taken
largely from the receptions market, which knows things play-by-play cannot.
Held against week-1 actuals the posted line beat the three-season rate on every
measure — RMSE 1.98 against 2.09, correlation .51 against .42, bias +0.10
against -0.12 — and a 70/30 blend toward the line edges both. (Measured against
a rate fit on 2024-25 only. Compared against the shipped rate, which carries a
30% weight on the season being predicted, history wins easily and entirely by
having seen the answer.)

Only the two-way over/under sets the number. It is the one quote whose vig can
be removed honestly, both sides being posted, and the line is solved rather
than read: 4.5 at an even price means P(5 or more) = 1/2, and the mean of a
count that clears five half the time is about 4.7, not 4.5. The milestone
ladder is kept only to catch the feed filing a yardage line under receptions —
its own overround is not flat across rungs, running ~1.10 below the line and
under 0.90 above it, so de-vigging it with a single number reads a mean a full
catch high. That was the first attempt and the bias is what killed it.

What this does NOT borrow is the longest-reception ladder itself. A different
market sets the volume, the model still sets the shape, and the price this page
has an edge against touches neither. A player with no posted receptions line
keeps the historical rate, as everyone did before.

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

# Shrinkage strengths, in catches and in games.
#
# K_ALPHA is heavy on purpose, and it was not always. Regress a receiver's
# 2025 alpha on his 2024 one and the carryover coefficient is only 0.28: a
# single season of catch yardage is far weaker evidence about next year's
# shape than treating it as nearly final implies. At the old K_ALPHA of 15 an
# established receiver kept ~93% of his own estimate; at 80 he keeps ~70%, and
# the rest comes from the prior below. Held out both ways -- fit 2024 predict
# 2025, and the reverse -- that is worth 0.002 to 0.005 of log-loss, the
# largest single gain since the position curves were split.
K_ALPHA, K_RATE = 80.0, 5.0
# Targets' worth of air yards before a receiver's own ADOT outweighs his
# position's. Gentle: ADOT settles quickly, which is the point of using it.
K_ADOT = 25.0
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
    air = collections.defaultdict(lambda: [0.0, 0])   # (pid, season) -> [sum air yards, targets]
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
                # Air yards ride on the TARGET, not the catch, which is the whole
                # reason they are worth carrying: a deep threat's incompletions
                # are evidence about his routes that his catch list cannot hold.
                try:
                    a = float(r["air_yards"])
                except (TypeError, ValueError):
                    a = None
                if a is not None:
                    v = air[(pid, season)]
                    v[0] += a
                    v[1] += 1
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
                                    nm=nm.get(pid, ""), pos=grp(pos.get(pid, "OTH")),
                                    ays=air[(pid, s)][0], ayn=air[(pid, s)][1])
                 for (pid, s), v in catches.items()},
        defense={f"{d}|{s}": {k: int(v) for k, v in c.items()} for (d, s), c in dcnt.items()},
        dgames={f"{d}|{s}": len(v) for (d, s), v in dgames.items()})


# ------------------------------------------------------------------- the model

MIN_POS_CATCHES = 500     # below this a position borrows the league curve


def pool_survival(D, seasons, pos=None):
    """Weighted empirical survival of catch yardage, as a 1-yard lookup.

    With `pos`, only that position's catches are counted -- see survival_curves.
    """
    buckets, tot = collections.Counter(), 0.0
    for k, v in D["players"].items():
        s = k.split("|")[1]
        if s not in seasons or (pos is not None and v["pos"] != pos):
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


def survival_curves(D, seasons):
    """One catch-yardage curve per position, plus the league curve as fallback.

    A single league curve was the model's biggest calibration error. Position
    does not merely scale that curve, it reshapes it: a back's catches are far
    shorter through the bulk (S(10) is .29 against a receiver's .50) and yet by
    40 yards his survival has caught the tight end's, because the long ones are
    screens that break rather than routes run deep. One exponent on a shared
    curve cannot hold both facts at once, and what it did instead was miss the
    back's tail -- fit 2024, predict 2025, and 20+ came in at .76 of actual,
    40+ at .22, while the tight end's 40+ ran 1.8x hot.

    Measured per position, every rung this market actually posts lands inside
    7% out of sample. Positions thinner than MIN_POS_CATCHES and everyone who
    is not a WR/TE/RB keep the league curve.
    """
    allS = pool_survival(D, seasons)
    n = collections.Counter()
    for k, v in D["players"].items():
        if k.split("|")[1] in seasons:
            n[v["pos"]] += len(v["y"])
    out = {p: (pool_survival(D, seasons, p) if n[p] >= MIN_POS_CATCHES else allS)
           for p in ("WR", "TE", "RB")}
    out["ALL"] = allS
    return out


def curve(S, pl):
    return S.get(pl.get("pos"), S["ALL"])


def adot_table(D, seasons):
    """Weighted ADOT per receiver, shrunk toward his position's, plus those means.

    Measured over TARGETS. That is the point of it: a receiver's catch list can
    only describe balls he caught, so a deep threat who ran twelve go routes and
    caught three of them looks, to the catch list alone, like a man with three
    catches. His air yards remember the other nine.
    """
    raw = collections.defaultdict(lambda: [0.0, 0.0, "OTH"])
    for k, v in D["players"].items():
        s = k.split("|")[1]
        if s not in seasons or not v.get("ayn"):
            continue
        w = seasons[s]
        r = raw[k.split("|")[0]]
        r[0] += w * v["ays"]
        r[1] += w * v["ayn"]
        r[2] = v["pos"]
    byp = collections.defaultdict(lambda: [0.0, 0.0])
    for a, n, p in raw.values():
        byp[p][0] += a
        byp[p][1] += n
    pos_mean = {p: (a / n if n else 0.0) for p, (a, n) in byp.items()}
    return ({pid: (a + K_ADOT * pos_mean.get(p, 0.0)) / (n + K_ADOT)
             for pid, (a, n, p) in raw.items()}, pos_mean)


# Minimum weighted catches, and minimum receivers, before the ADOT slope below
# is fit at all. Under either, it is left at zero and the prior is the flat
# position mean the model used before.
SLOPE_MIN_CATCHES, SLOPE_MIN_PLAYERS = 25.0, 20


def adot_slope(raw, prior, AD, pos_mean):
    """d log(alpha) / d ADOT, pooled across positions, weighted by catches.

    Pooled rather than one per position on purpose. Fit per position the slope
    is right in sign every time but wobbles badly in size where the sample is
    thin -- backs came out at -0.015 fitting 2024 and -0.090 fitting 2025, a
    six-fold swing on the same quantity. Pooled it is -0.075 and -0.088 on those
    same two fits, which is a number worth believing, and the three positions
    disagree about it by less than the noise in any one of them.

    Deliberately NOT a correction applied on top of a receiver's own alpha. Tried
    that -- alpha *= exp(g * (adot - mean)) -- and it loses monotonically in g,
    because a receiver's catch yardage already carries his depth and the tilt
    double-counts it. ADOT earns its place as a PRIOR, where it speaks loudest
    for the receiver whose own catch list says least.
    """
    sw = sx = sy = sxx = sxy = 0.0
    n = 0
    for pid, v in raw.items():
        if v["pos"] not in ("WR", "TE", "RB") or v["W"] < SLOPE_MIN_CATCHES or v["T"] <= 0:
            continue
        if pid not in AD:
            continue
        base = prior.get(v["pos"], {}).get("alpha")
        if not base:
            continue
        x = AD[pid] - pos_mean.get(v["pos"], 0.0)
        y = math.log(v["W"] / v["T"]) - math.log(base)
        w = v["W"]
        sw += w
        sx += w * x
        sy += w * y
        sxx += w * x * x
        sxy += w * x * y
        n += 1
    if n < SLOPE_MIN_PLAYERS or sw <= 0:
        return 0.0
    den = sxx - sx * sx / sw
    return (sxy - sx * sy / sw) / den if den > 1e-9 else 0.0


def fit_players(D, seasons):
    S = survival_curves(D, seasons)
    AD, ADPOS = adot_table(D, seasons)
    raw = {}
    for k, v in D["players"].items():
        pid, s = k.split("|")
        if s not in seasons or not v["g"]:
            continue
        w = seasons[s]
        T = sum(-math.log(curve(S, v)(y)) for y in v["y"])
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

    # The prior a thin receiver is shrunk toward is no longer his position's
    # average shape but his position's average shape AT HIS DEPTH.
    slope = adot_slope(raw, prior, AD, ADPOS)

    out = {}
    for pid, v in raw.items():
        pr = prior.get(v["pos"], dict(alpha=1.0, rate=3.0))
        pa = pr["alpha"]
        if slope and pid in AD and v["pos"] in ADPOS:
            pa *= math.exp(slope * (AD[pid] - ADPOS[v["pos"]]))
        alpha = (v["W"] + K_ALPHA) / (v["T"] + K_ALPHA / pa)
        r_raw = v["rs"] / v["ws"] if v["ws"] else pr["rate"]
        g_eff = v["g"] / v["ws"] if v["ws"] else 0.0
        rate = (r_raw * g_eff + K_RATE * pr["rate"]) / (g_eff + K_RATE)
        out[pid] = dict(alpha=alpha, rate=rate, nm=v["nm"], pos=v["pos"],
                        games=v["gr"], catches=int(round(v["n"] / max(seasons.values()))),
                        adot=AD.get(pid), apos=ADPOS.get(v["pos"]))
    return out, S, prior, dict(slope=slope, pos=ADPOS)


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
    """S is the curve set from survival_curves; the player's position picks one."""
    return pl["rate"] * (curve(S, pl)(x) ** pl["alpha"]) * mult


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
    tr, S, _, _ = fit_players(D, {"2024": 1.0})
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
    # The same bands split by position. This is where a shared curve showed its
    # error and it is where a regression would show up again, so it ships with
    # the board rather than living in a one-off script.
    bypos = {}
    for pos in ("WR", "TE", "RB"):
        sub = [(pl, L) for pl, L in ev if pl["pos"] == pos]
        if not sub:
            continue
        bypos[pos] = dict(n=len(sub), bands=[
            dict(x=x,
                 pred=round(statistics.mean(1 - math.exp(-lam(pl, S, x) * cal) for pl, _ in sub), 4),
                 act=round(statistics.mean(1 if L >= x else 0 for _, L in sub), 4))
            for x in (10, 15, 20, 25, 30, 40)])
    return dict(bands=bands, deciles=dec, n=len(ev),
                players=len({id(p) for p, _ in ev}), cal=cal, bypos=bypos), cal


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


# ------------------------------------------------- the receptions market

# Receptions are NOT Poisson -- game script correlates targets within a game, so
# the count is overdispersed. A negative binomial at this size fits the posted
# ladders to a median 7% in log space; Poisson leaves a visible tail residual.
NB_SIZE = 20.0
# The feed occasionally files a yardage line under prop_type "receptions" --
# one week-1 game carried lines of 16.5, 22.5 and 25.5 "receptions". No book
# posts a receptions line in double digits, so this is a lie detector, not a
# judgement call.
MAX_REC_LINE = 11.0
# How much of a receiver's catch rate comes from the market when the market has
# an opinion. Fit against week-1 actuals: the posted line beats the model's own
# three-season rate outright (RMSE 1.98 against 2.09, correlation .51 against
# .42, and essentially no bias against the model's -0.12), and 0.7 is where the
# blend's error bottoms out -- a shade better than taking the line whole, since
# the history still damps a stale or thin quote.
MKT_RATE_W = 0.70


def implied_prob(american):
    o = float(american)
    return 100.0 / (o + 100.0) if o > 0 else (-o) / ((-o) + 100.0)


def nb_survival(mu, size, k):
    """P(N >= k) for a negative binomial with this mean and size."""
    if k <= 0:
        return 1.0
    p = size / (size + mu)
    term = p ** size
    cum = term
    for i in range(k - 1):
        term *= (size + i) / (i + 1.0) * (1.0 - p)
        cum += term
    return min(max(1.0 - cum, 1e-12), 1.0)


def mean_from_line(line, p_over, size=NB_SIZE):
    """The mean receptions consistent with a de-vigged two-way line.

    A line of 4.5 at an even price does not mean four and a half catches; it
    means P(5 or more) = 1/2, and the mean of a right-skewed count that clears
    five half the time is nearer 4.7. Solving rather than reading the line off
    is the difference, and across a slate it is the difference between an
    unbiased volume estimate and one a full catch high.
    """
    k = int(math.ceil(line))
    lo, hi = 0.02, 22.0
    for _ in range(50):
        mid = (lo + hi) / 2.0
        if nb_survival(mid, size, k) < p_over:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def receptions_mean(quotes):
    """One receiver's posted receptions market -> his implied mean, or None.

    Only the two-way over/under is used to set the number, because it is the
    only quote here whose vig can be removed honestly: both sides are posted,
    so normalising the pair to one is exact. The milestone ladder is one-sided
    and its overround is not flat across rungs -- measured against the two-way
    line it runs about 1.10 below the line and falls under 0.90 above it, so
    dividing the ladder by a single number and fitting the result reads a mean
    a full catch too high. The ladder is kept only to sanity-check the line.
    """
    ou = [q for q in quotes.get("ou", []) if 0.02 < q[1] < 0.98]
    if not ou:
        return None
    # The main line is the one priced nearest a coin flip; alternates sit wide.
    line, p_over = min(ou, key=lambda q: abs(q[1] - 0.5))
    lad = quotes.get("lad") or {}
    if lad:
        # A real receptions line sits inside its own ladder. A yardage line
        # filed as receptions does not, and this is where it gets caught.
        k = int(math.ceil(line))
        near = [q for r, q in lad.items() if abs(r - k) <= 1]
        if near and max(near) < 0.10:
            return None
    return mean_from_line(line, p_over)


def week_context(priced_games, week):
    """Everything balldontlie is asked for, in one pass over the week's games.

    Two things come back. The unpriced games' pass-catchers, so the board covers
    the whole slate rather than only what DraftKings posted -- that is what this
    used to do alone. And every receiver's posted RECEPTIONS market, across all
    the games including the priced ones, which is the volume half of the
    likelihood: how many chances at a long one a receiver is actually going to
    get this Sunday, rather than how many he averaged over three seasons.

    Returns ([], [], {}) when the key is missing -- the board then covers fewer
    games and prices volume entirely off history, exactly as it did before.
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import bdl_common as b
        if not b.api_key(required=False):
            print("  no BALLDONTLIE_API_KEY -- history-only volume, priced games only")
            return [], [], {}
    except Exception as exc:
        print(f"  balldontlie unavailable ({exc}) -- history-only volume")
        return [], [], {}

    games = list(b.paginate("/games", {"seasons[]": [SEASON], "weeks[]": [week]}, quiet=True))
    players = {str(p["id"]): p for p in b.paginate("/players/active", None, quiet=True)}
    PASS = {"Wide Receiver": "WR", "Tight End": "TE", "Running Back": "RB", "Fullback": "RB"}
    rows, metas, rec = [], [], {}
    for g in games:
        v, h = g["visitor_team"], g["home_team"]
        label = f"{v['name']} @ {h['name']}"
        unpriced = label not in priced_games
        if unpriced:
            metas.append(dict(g=label, ko=g["date"].replace(".000Z", "Z"),
                              away=v["name"], home=h["name"], nomkt=True))
        seen, quotes = set(), collections.defaultdict(lambda: dict(ou=[], lad={}))
        for r in b.paginate("/odds/player_props", {"game_id": g["id"]}, quiet=True):
            pid = str(r["player_id"])
            p = players.get(pid)
            if r.get("prop_type") == "receptions" and r.get("vendor") == "draftkings":
                m = r.get("market") or {}
                try:
                    lv = float(r.get("line_value"))
                except (TypeError, ValueError):
                    lv = None
                if lv is not None and lv <= MAX_REC_LINE:
                    q = quotes[pid]
                    if m.get("type") == "over_under":
                        po = implied_prob(m["over_odds"])
                        pu = implied_prob(m["under_odds"])
                        q["ou"].append((lv, po / (po + pu)))
                    elif m.get("type") == "milestone":
                        q["lad"][int(round(lv))] = implied_prob(m["odds"])
            if not unpriced or pid in seen or not p or p.get("position") not in PASS:
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
        for pid, q in quotes.items():
            mu = receptions_mean(q)
            p = players.get(pid)
            if mu is not None and p:
                rec[norm(f"{p['first_name']} {p['last_name']}")] = round(mu, 3)
    return rows, metas, rec


# -------------------------------------------------------------------- the weeks

def price_rows(priced, extra, PL, PRIOR, S, DEF, CAL, idx, rec=None):
    """One week's players, each with a likelihood at every rung on the grid.

    `priced` came from the book, `extra` from balldontlie — they differ only in
    whether there is a ladder to have an edge against, so they are priced by the
    same pass.

    Two numbers make a likelihood here and they come from different places. How
    FAR a catch goes is the model's own, measured off play-by-play and shrunk
    toward a prior that now knows how deep the receiver is thrown to. How MANY
    catches he gets is a question about this Sunday -- about a depth chart, an
    injury report and a game script -- and on that the receptions market is
    simply better informed than a three-season average can be, so where a
    receptions line is posted it carries most of the weight.

    Note what is NOT borrowed: the longest-reception ladder this page has an
    edge against never touches any of it. A different market sets the volume,
    the model still sets the shape, and the price being judged is judged by
    neither.
    """
    rows = []
    for r in priced + extra:
        key = norm(r["n"])
        cands = idx.get(key, [])
        pl = PL[max(cands, key=lambda q: PL[q]["games"])] if cands else None
        pos = (pl or {}).get("pos") or r.get("pos") or "WR"
        if pos not in ("WR", "TE", "RB"):
            pos = r.get("pos") if r.get("pos") in ("WR", "TE", "RB") else "WR"
        if not pl:
            pr = PRIOR.get(pos, dict(alpha=1.0, rate=3.0))
            pl = dict(alpha=pr["alpha"], rate=pr["rate"], games=0, catches=0)
        # `pos` is what the defense split and the curve both read, so pin it on
        # the record too: a back with no play-by-play history should still be
        # priced off the backs' curve, not the league's.
        pl = dict(pl, pos=pos)
        hist = pl["rate"]
        mrate = (rec or {}).get(key)
        # A player with no history at all has nothing to blend: the market line
        # is then the only thing anyone knows about his volume, so take it whole.
        w = MKT_RATE_W if pl["catches"] else 1.0
        rate = hist * (1 - w) + mrate * w if mrate is not None else hist
        pl = dict(pl, rate=rate)
        d = DEF[r["op"]]
        P = {str(x): round(1 - math.exp(-lam(pl, S, x, defense_mult(d, pos, x)) * CAL), 4)
             for x in GRID}
        rows.append(dict(n=r["n"], tm=r["tm"], op=r["op"], v=r["v"], lng=r["lng"], g=r["g"],
                         L=r["L"], P=P, pos=pos, alpha=round(pl["alpha"], 3),
                         rate=round(rate, 2), hrate=round(hist, 2),
                         mrate=(round(mrate, 2) if mrate is not None else None),
                         adot=(round(pl["adot"], 1) if pl.get("adot") is not None else None),
                         games=pl["games"], catches=pl["catches"], nomkt=not r["L"]))
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
    print("  predicted/actual by position: "
          + " | ".join(f"{p} " + " ".join(f"{b['x']}+ {b['pred'] / max(b['act'], 1e-9):.2f}"
                                          for b in v["bands"] if b["act"])
                       for p, v in bt["bypos"].items()))

    PL, S, PRIOR, ADOT = fit_players(D, WEIGHT)
    DEF, LG = fit_defense(D, WEIGHT)
    print(f"\n  alpha shrunk with K={K_ALPHA:.0f} toward a prior tilted "
          f"{ADOT['slope']:+.4f} per yard of ADOT; position ADOT "
          + ", ".join(f"{p} {ADOT['pos'][p]:.1f}" for p in ("WR", "TE", "RB") if p in ADOT["pos"]))
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
        extra, extra_games, rec = ([], [], {}) if args.no_bdl else week_context(set(games), wk)
        if extra:
            print(f"  week {wk}: balldontlie adds {len(extra)} pass-catchers across "
                  f"{len(extra_games)} unpriced games")
        rows = price_rows(slate, extra, PL, PRIOR, S, DEF, CAL, idx, rec)
        priced_vol = sum(1 for r in rows if r["mrate"] is not None)
        if priced_vol:
            moved = [r for r in rows if r["mrate"] is not None and r["hrate"]]
            lift = (statistics.median(r["rate"] / r["hrate"] for r in moved) if moved else 1.0)
            print(f"  week {wk}: {priced_vol} of {len(rows)} players carry a posted "
                  f"receptions line (median volume x{lift:.2f})")
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
        target_count=sum(v["ayn"] for v in D["players"].values()),
        receiver_count=len(PL),
        lambda_scale=CAL, sample_gate=dict(games=GATE_GAMES, catches=GATE_CATCHES),
        depth=dict(k_alpha=K_ALPHA, k_adot=K_ADOT,
                   adot_slope=round(ADOT["slope"], 5),
                   position_adot={p: round(v, 2) for p, v in ADOT["pos"].items()
                                  if p in ("WR", "TE", "RB")}),
        volume=dict(market_weight=MKT_RATE_W, nb_size=NB_SIZE,
                    priced=sum(1 for w in weeks if w["week"] in fresh
                               for r in w["rows"] if r.get("mrate") is not None),
                    source="balldontlie /odds/player_props, DraftKings receptions"),
        backtest=dict(n=bt["n"], players=bt["players"],
                      decile_1=bt["deciles"][0]["act"], decile_10=bt["deciles"][9]["act"],
                      by_position={p: dict(n=v["n"], bands=v["bands"])
                                   for p, v in bt["bypos"].items()}),
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
