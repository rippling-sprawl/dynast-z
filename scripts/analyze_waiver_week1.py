#!/usr/bin/env python3
"""
Build data/waiver-week1-analysis.json: what the week 1 waiver claims in the
Cut Throat 2025 season were actually worth, and whether the manager who won
them lived long enough to spend the value.

Two questions, and they are not the same question
-------------------------------------------------
1. What should the bid have been, given what the player went on to score?
2. Did the buyer survive to collect it?

The second one is the whole point of a chop league. One team is eliminated
every week — 18 down to 2 — so a player bought in week 1 only pays out for as
long as his owner is still alive. A perfectly-priced bid on a player who scores
300 points is worth nothing if you are chopped in week 6.

Pricing: why raw points are not enough
--------------------------------------
The obvious model — split the week's spend in proportion to rest-of-season
points — badly overrates quarterbacks, and in THIS league it overrates them in
a specific and correctable way. The lineup expands as the field shrinks (see
LINEUP below): week 1 starts EIGHT players and exactly ONE quarterback. The
superflex that makes QB points premium does not appear until week 5, and the
second QB slot not until week 13. So in week 1 a quarterback's raw total was
nearly worthless at the margin — every team could start a competent QB for
free, and the 18th-best QB that week still scored 15.9.

So the file carries both:

  fair_pts  — share of raw rest-of-season points. Simple, and what you get if
              you ask the question literally. Flatters quarterbacks.
  fair_vor  — share of points ABOVE replacement, where replacement is the score
              of the last player at that position actually started league-wide
              that week. This is the honest one: it prices scarcity, and it
              follows both the shrinking field and the expanding lineup.

Replacement is measured from what the room actually started, not from what the
rules allow, so the FLEX and superflex land wherever managers really put them.

Delivery: held vs started
-------------------------
ros_pts is what the player scored. held_pts is what he scored while the buyer
still owned him. started_pts is what the buyer actually put in a lineup. With
only eight starting slots in week 1, the gap between the last two is real: a
claim could score into thin air on a bench.

Scoring is computed from the league's own scoring_settings and is checked
against Sleeper's matchup numbers — 2,567 player-weeks, zero mismatches.

Usage
-----
    python3 scripts/analyze_waiver_week1.py [--league ID] [--season 2025]
"""

import argparse
import collections
import json
import os
import sys
import urllib.request

LEAGUE_ID = '1264056168385355776'
SEASON = '2025'
OUT = 'data/waiver-week1-analysis.json'
API = 'https://api.sleeper.app/v1'
POS = ('QB', 'RB', 'WR', 'TE')

# The league's published schedule of lineup expansions. One team is chopped per
# week and the lineup grows to absorb the players that come loose. Week 1 is a
# one-QB league; SF arrives in wk5, a 3rd WR in wk7, a 2nd TE in wk9, a 3rd RB
# in wk11, a 2nd QB in wk13, a 4th FLEX in wk15. `teams` is cross-checked
# against the chop log at the bottom of main().
LINEUP = {
    1:  dict(teams=18, QB=1, RB=2, WR=2, TE=1, SF=0, FLEX=2),
    2:  dict(teams=17, QB=1, RB=2, WR=2, TE=1, SF=0, FLEX=2),
    3:  dict(teams=16, QB=1, RB=2, WR=2, TE=1, SF=0, FLEX=3),
    4:  dict(teams=15, QB=1, RB=2, WR=2, TE=1, SF=0, FLEX=3),
    5:  dict(teams=14, QB=1, RB=2, WR=2, TE=1, SF=1, FLEX=3),
    6:  dict(teams=13, QB=1, RB=2, WR=2, TE=1, SF=1, FLEX=3),
    7:  dict(teams=12, QB=1, RB=2, WR=3, TE=1, SF=1, FLEX=3),
    8:  dict(teams=11, QB=1, RB=2, WR=3, TE=1, SF=1, FLEX=3),
    9:  dict(teams=10, QB=1, RB=2, WR=3, TE=2, SF=1, FLEX=3),
    10: dict(teams=9,  QB=1, RB=2, WR=3, TE=2, SF=1, FLEX=3),
    11: dict(teams=8,  QB=1, RB=3, WR=3, TE=2, SF=1, FLEX=3),
    12: dict(teams=7,  QB=1, RB=3, WR=3, TE=2, SF=1, FLEX=3),
    13: dict(teams=6,  QB=2, RB=3, WR=3, TE=2, SF=1, FLEX=3),
    14: dict(teams=5,  QB=2, RB=3, WR=3, TE=2, SF=1, FLEX=3),
    15: dict(teams=4,  QB=2, RB=3, WR=3, TE=2, SF=1, FLEX=4),
    16: dict(teams=3,  QB=2, RB=3, WR=3, TE=2, SF=1, FLEX=4),
    17: dict(teams=2,  QB=2, RB=3, WR=3, TE=2, SF=1, FLEX=4),
}
WEEKS = sorted(LINEUP)
CACHE = os.environ.get('WAIVER_CACHE')  # optional dir of pre-fetched API JSON


def get(path, name):
    if CACHE:
        p = os.path.join(CACHE, name)
        if os.path.exists(p):
            with open(p) as fh:
                return json.load(fh)
    with urllib.request.urlopen(f'{API}/{path}', timeout=90) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--league', default=LEAGUE_ID)
    ap.add_argument('--season', default=SEASON)
    ap.add_argument('--out', default=OUT)
    args = ap.parse_args()

    league = get(f'league/{args.league}', 'league.json')
    sc_settings = league['scoring_settings']
    users = {u['user_id']: u for u in get(f'league/{args.league}/users', 'users.json')}
    rosters = {r['roster_id']: r for r in get(f'league/{args.league}/rosters', 'rosters.json')}
    players = get('players/nfl', 'players.json')

    def score(st):
        return round(sum(v * st[k] for k, v in sc_settings.items() if k in st), 2)

    def pos_of(pid):
        return (players.get(pid) or {}).get('position')

    # player -> {week: league points}
    pts = collections.defaultdict(dict)
    for w in WEEKS:
        for pid, st in get(f'stats/nfl/regular/{args.season}/{w}', f'stats_{w}.json').items():
            pts[pid][w] = score(st)

    # Ownership and lineups, week by week, plus a check that our scoring is the
    # league's scoring. Sleeper hands back both in the matchup payload.
    owned, started, started_by_pos = {}, {}, {}
    mismatches = 0
    for w in WEEKS:
        o, s, bypos = {}, {}, collections.Counter()
        for e in get(f'league/{args.league}/matchups/{w}', f'mu_{w}.json'):
            for pid, truth in (e.get('players_points') or {}).items():
                if pid in pts and abs(pts[pid].get(w, 0) - truth) > 0.011:
                    mismatches += 1
            for pid in (e.get('players') or []):
                o[pid] = e['roster_id']
            for pid in [x for x in (e.get('starters') or []) if x and x != '0']:
                s[pid] = e['roster_id']
                if pos_of(pid) in POS:
                    bypos[pos_of(pid)] += 1
        owned[w], started[w], started_by_pos[w] = o, s, bypos
    if mismatches:
        print(f'SCORING MISMATCH on {mismatches} player-weeks', file=sys.stderr)
        return 1

    # Replacement level: the last starter at each position, that week.
    repl = {}
    for w in WEEKS:
        repl[w] = {}
        for p in POS:
            scores = sorted((pts[pid][w] for pid in pts
                             if pos_of(pid) == p and w in pts[pid]), reverse=True)
            n = started_by_pos[w].get(p, 0)
            repl[w][p] = scores[n - 1] if 0 < n <= len(scores) else 0.0

    def vor(pid, w):
        v = pts.get(pid, {}).get(w)
        if v is None or pos_of(pid) not in POS:
            return 0.0
        return max(0.0, v - repl[w][pos_of(pid)])

    chop = {rid: r['settings'].get('eliminated') for rid, r in rosters.items()}
    for w in WEEKS:
        alive = sum(1 for e in chop.values() if e is None or e >= w)
        assert alive == LINEUP[w]['teams'], f'week {w}: {alive} alive, LINEUP says {LINEUP[w]["teams"]}'

    def mgr(rid):
        u = users.get(rosters[rid].get('owner_id')) or {}
        return u.get('display_name', f'roster {rid}')

    # Week 1 winning claims. Waivers ran after the week 1 games, so the earning
    # window is weeks 2-17.
    claims = []
    for t in get(f'league/{args.league}/transactions/1', 'tx_1.json'):
        if t['type'] != 'waiver' or t['status'] != 'complete':
            continue
        bid = (t.get('settings') or {}).get('waiver_bid')
        if bid is None:
            continue
        rid = t['roster_ids'][0]
        for pid in (t.get('adds') or {}):
            p = players.get(pid) or {}
            claims.append({
                'pid': pid,
                'player': p.get('full_name') or f"{p.get('first_name','')} {p.get('last_name','')}".strip(),
                'pos': p.get('position') or '?', 'nfl': p.get('team') or 'FA',
                'bid': bid, 'manager': mgr(rid), 'roster_id': rid,
                'chop_week': chop.get(rid),
            })

    for c in claims:
        pid, rid, wk = c['pid'], c['roster_id'], pts.get(c['pid'], {})
        c['ros_pts'] = round(sum(v for w, v in wk.items() if w >= 2), 2)
        c['ros_vor'] = round(sum(vor(pid, w) for w in WEEKS if w >= 2), 2)
        c['held_pts'] = round(sum(v for w, v in wk.items() if w >= 2 and owned[w].get(pid) == rid), 2)
        c['started_pts'] = round(sum(v for w, v in wk.items() if w >= 2 and started[w].get(pid) == rid), 2)
        c['weeks_held'] = sum(1 for w in WEEKS if w >= 2 and owned[w].get(pid) == rid)
        c['weeks_started'] = sum(1 for w in WEEKS if w >= 2 and started[w].get(pid) == rid)

    total_bid = sum(c['bid'] for c in claims)
    for src, dst in (('ros_pts', 'fair_pts'), ('ros_vor', 'fair_vor')):
        tot = sum(c[src] for c in claims)
        for c in claims:
            c[dst] = round(total_bid * c[src] / tot) if tot else 0

    # Rest-of-season positional finish, for context on the raw totals.
    by_pos = collections.defaultdict(list)
    for pid in pts:
        if pos_of(pid) in POS:
            by_pos[pos_of(pid)].append((round(sum(v for w, v in pts[pid].items() if w >= 2), 2), pid))
    rank = {}
    for p, lst in by_pos.items():
        lst.sort(reverse=True)
        for i, (_, pid) in enumerate(lst):
            rank[pid] = f'{p}{i + 1}'
    for c in claims:
        c['pos_rank'] = rank.get(c['pid'], '—')

    claims.sort(key=lambda c: -c['bid'])

    # Season-long: early spend vs how long the manager lasted.
    early, season = collections.Counter(), collections.Counter()
    for w in WEEKS:
        for t in get(f'league/{args.league}/transactions/{w}', f'tx_{w}.json'):
            if t['type'] != 'waiver' or t['status'] != 'complete':
                continue
            bid = (t.get('settings') or {}).get('waiver_bid')
            if bid is None:
                continue
            rid = t['roster_ids'][0]
            season[rid] += bid
            if t['leg'] <= 2:
                early[rid] += bid
    survival = sorted(
        ({'manager': mgr(rid), 'early_spend': early[rid], 'season_spend': season[rid],
          'chop_week': chop.get(rid)} for rid in rosters),
        key=lambda d: -d['early_spend'])

    # --- Price of a point, week by week -------------------------------------
    # What this room paid per point of per-game value-above-replacement that the
    # claim actually went on to deliver. It falls through the season as budgets
    # drain, which is why a week 2 bid and a week 9 bid are not comparable.
    # scripts/waiver_targets.py prices the live season off this table.
    rate = {}
    for wk in WEEKS:
        spend, delivered = 0, 0.0
        for t in get(f'league/{args.league}/transactions/{wk}', f'tx_{wk}.json'):
            if t['type'] != 'waiver' or t['status'] != 'complete':
                continue
            bid = (t.get('settings') or {}).get('waiver_bid')
            if bid is None:
                continue
            for pid in (t.get('adds') or {}):
                spend += bid
                rest = [vor(pid, w) for w in WEEKS if w > wk and w in pts.get(pid, {})]
                if rest:
                    delivered += sum(rest) / len(rest)
        if spend and delivered > 0:
            rate[str(wk)] = {'spend': spend, 'vor_per_game': round(delivered, 2),
                             'dollars_per_point': round(spend / delivered, 1)}

    out = {
        'league': league['name'], 'season': args.season,
        'total_bid': total_bid, 'claims': claims, 'survival': survival,
        'price_rate': rate,
        'lineup': {str(w): dict(LINEUP[w], starters=sum(LINEUP[w][k] for k in ('QB', 'RB', 'WR', 'TE', 'SF', 'FLEX')))
                   for w in WEEKS},
        'replacement': {str(w): {p: round(repl[w][p], 2) for p in POS} for w in WEEKS},
        'started_by_pos': {str(w): dict(started_by_pos[w]) for w in WEEKS},
    }
    with open(args.out, 'w') as fh:
        json.dump(out, fh, indent=1)

    started = sum(c['started_pts'] for c in claims)
    ros = sum(c['ros_pts'] for c in claims)
    print(f'{args.out}: {len(claims)} week 1 claims, ${total_bid} spent, {ros:.0f} ROS pts bought, '
          f'{started:.0f} ({100 * started / ros:.0f}%) actually started')
    print('scoring verified against Sleeper matchups; teams-alive verified against chop log')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
