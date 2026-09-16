#!/usr/bin/env python3
"""
Build data/waiver-targets.json: what one team should bid on this week's waiver
run, for the in-season Cut Throat league.

Run it every week before waivers process. It reads the live league state, so
there is nothing to edit between runs:

    python3 scripts/waiver_targets.py --team "Jed York"

What it is and is not
---------------------
This is a PRICING tool, not a projection system. It does not claim to know who
will score well. It answers a narrower and more answerable question: given what
players have actually done so far, which free agents would improve THIS team's
starting lineup, and what did this specific room historically pay for players of
that calibre at this point in the season?

Both halves matter. A waiver target is only worth what it adds ABOVE the player
it would replace in your lineup, and it is only worth bidding what the market
requires. Chasing a good player at a bad price is how the 2025 season's biggest
claim ($900 on Ja'Marr Chase) returned 107 of 285 points before its buyer was
chopped in week 6 — see scripts/analyze_waiver_week1.py.

How a bid is derived
--------------------
1. Replacement level, per position, per week: the score of the last player at
   that position actually started league-wide. Points below it were free.
2. A free agent's raw VALUE is his per-game average above that replacement.
3. That raw figure is then REGRESSED, because a hot week is mostly noise. How
   much to keep is measured, not guessed: fitting last season's short-sample
   VOR against the same players' rest-of-season VOR gives

       1 game observed -> keep 34% of the edge   (r = 0.61, n = 653)
       2 games         -> keep 46%
       3 games         -> keep 48%
       4+ games        -> keep 50%   (it plateaus there)

   So a receiver who posts a +10 week projects to about +3.4 going forward, not
   +10. Skipping this step is the single biggest way to overpay in week 2, and
   it is what the 2025 room did.
4. Dollars come from the same league's own market: for the prior season's SAME
   week, total spend divided by the total per-game VOR those claims actually
   delivered. That rate falls through the year as budgets drain — $44/point in
   week 1, $31 in week 2, $17 by week 7 — so the anchor tracks the real market
   rather than a fixed table.
5. A weekly cap bounds the whole slate, tighter early where information is
   worst: 6% of remaining budget through week 4, 10% to week 12, 15% after
   (by then it is use-it-or-lose-it). In 2025 five of the last six teams
   standing spent under $61 of $1000 across weeks 1-2, while the two biggest
   early spenders were chopped in weeks 5 and 6. When the cap binds, every bid
   scales down proportionally — the slate keeps its shape instead of the top
   target eating the budget.

A bid is therefore only as big as BOTH the projected edge and the room's
historical price for that edge allow, and never more than the cap.

Roster space is treated as a real constraint. If the roster is full, every
suggestion is paired with a drop, and the number of suggestions never exceeds
the number of droppable players.

Usage
-----
    python3 scripts/waiver_targets.py --team "Jed York"
    python3 scripts/waiver_targets.py --team "Jed York" --week 5 --cap-pct 12
"""

import argparse
import collections
import json
import os
import statistics
import sys
import urllib.request

API = 'https://api.sleeper.app/v1'
LEAGUE = '1340070186379673600'          # Cut Throat 2026
PRIOR_BIDS = 'data/waiver-bids-2025.csv'
PRIOR_RATES = 'data/waiver-week1-analysis.json'   # carries price_rate, built by analyze_waiver_week1.py
OUT = 'data/waiver-targets.json'
POS = ('QB', 'RB', 'WR', 'TE')
FLEX_OK = ('RB', 'WR', 'TE')
CACHE = os.environ.get('WAIVER_CACHE')


def get(path, name=None):
    if CACHE and name:
        p = os.path.join(CACHE, name)
        if os.path.exists(p):
            with open(p) as fh:
                return json.load(fh)
    with urllib.request.urlopen(f'{API}/{path}', timeout=90) as r:
        return json.load(r)


# Share of an observed edge that survives into the rest of the season, by how
# many games it rests on. Measured on the 2025 season of this same league by
# regressing short-sample VOR on rest-of-season VOR; see the module docstring.
KEEP = {1: 0.34, 2: 0.46, 3: 0.48}
KEEP_PLATEAU = 0.50


def keep_share(games):
    return KEEP.get(games, KEEP_PLATEAU) if games else 0.0


def prior_week_prices(path, week):
    """Prior season, same week: the winning-bid spread, for context only."""
    import csv
    if not os.path.exists(path):
        return None
    bids = [int(r['bid']) for r in csv.DictReader(open(path))
            if r['result'] == 'won' and int(r['week']) == week]
    if not bids:
        return None
    bids.sort()
    return {
        'n': len(bids),
        'median': statistics.median(bids),
        'p75': bids[int(len(bids) * 0.75)] if len(bids) > 3 else max(bids),
        'max': max(bids),
        'total': sum(bids),
    }


def week_cap_pct(week):
    """Tighter early, where a claim rests on one game and the budget is whole."""
    return 6.0 if week <= 4 else (10.0 if week <= 12 else 15.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--league', default=LEAGUE)
    ap.add_argument('--team', required=True, help='team name or manager display name')
    ap.add_argument('--week', type=int, default=None, help='defaults to the live NFL week')
    ap.add_argument('--cap-pct', type=float, default=None,
                    help='max %% of remaining FAAB to commit (default: 6 early, 10 mid, 15 late)')
    ap.add_argument('--out', default=OUT)
    args = ap.parse_args()

    league = get(f'league/{args.league}', 'league.json')
    sc_settings = league['scoring_settings']
    season = league['season']
    state = get('state/nfl', 'state.json')
    week = args.week or int(state['week'])
    cap_pct = args.cap_pct if args.cap_pct is not None else week_cap_pct(week)
    played = list(range(1, week))          # weeks with results
    if not played:
        print('week 1 has not been played yet — nothing to price', file=sys.stderr)
        return 1

    users = {u['user_id']: u for u in get(f'league/{args.league}/users', 'users.json')}
    rosters = get(f'league/{args.league}/rosters', 'rosters.json')
    players = get('players/nfl', 'players.json')

    def score(st):
        return round(sum(v * st[k] for k, v in sc_settings.items() if k in st), 2)

    def pos_of(pid):
        return (players.get(pid) or {}).get('position')

    def name_of(pid):
        p = players.get(pid) or {}
        return p.get('full_name') or f"{p.get('first_name','')} {p.get('last_name','')}".strip() or pid

    stats = {w: get(f'stats/nfl/regular/{season}/{w}', f'stats_{w}.json') for w in played}
    matchups = {w: get(f'league/{args.league}/matchups/{w}', f'mu_{w}.json') for w in played}

    pts = collections.defaultdict(dict)
    for w in played:
        for pid, st in stats[w].items():
            pts[pid][w] = score(st)

    # Replacement level per position per week, from what the room actually started.
    repl = {}
    for w in played:
        starts = collections.Counter()
        for e in matchups[w]:
            for pid in [x for x in (e.get('starters') or []) if x and x != '0']:
                if pos_of(pid) in POS:
                    starts[pos_of(pid)] += 1
        repl[w] = {}
        for p in POS:
            s = sorted((pts[pid][w] for pid in pts if pos_of(pid) == p and w in pts[pid]), reverse=True)
            n = starts[p]
            repl[w][p] = s[n - 1] if 0 < n <= len(s) else 0.0

    def value(pid):
        """Per-game points above replacement: observed, and regressed.

        The regressed figure is the one to price off. An edge seen once is
        mostly noise — see KEEP, measured on last season rather than assumed."""
        p = pos_of(pid)
        if p not in POS:
            return 0.0, 0.0, 0
        vals = [max(0.0, pts[pid][w] - repl[w][p]) for w in played if w in pts.get(pid, {})]
        games = sum(1 for w in played if pts.get(pid, {}).get(w, 0) != 0)
        obs = round(statistics.mean(vals), 2) if vals else 0.0
        return obs, round(obs * keep_share(games), 2), games

    def opportunity(pid):
        tot = 0
        for w in played:
            st = stats[w].get(pid) or {}
            tot += st.get('rec_tgt', 0) + st.get('rush_att', 0)
        return round(tot / len(played), 1)

    # --- locate the team ---
    def label(r):
        u = users.get(r.get('owner_id')) or {}
        return ((u.get('metadata') or {}).get('team_name') or u.get('display_name') or ''), u.get('display_name', '')

    target = None
    for r in rosters:
        tn, dn = label(r)
        if args.team.lower() in (tn.lower().strip(), dn.lower().strip()):
            target = r
            break
    if target is None:
        print(f'no team matching {args.team!r}. Teams: '
              + ', '.join(sorted(label(r)[0] for r in rosters)), file=sys.stderr)
        return 1
    rid = target['roster_id']
    tname, tmgr = label(target)

    last = matchups[played[-1]]
    mine = next(e for e in last if e['roster_id'] == rid)
    scores = sorted(((e.get('points') or 0), e['roster_id']) for e in last if (e.get('players') or []))
    my_pts = mine.get('points') or 0
    my_rank = [r for _, r in scores][::-1].index(rid) + 1

    roster_ids = list(mine.get('players') or [])
    starters = [x for x in (mine.get('starters') or []) if x and x != '0']
    bench = [p for p in roster_ids if p not in starters]
    slots = league['roster_positions']
    cap_size = len(slots)
    faab_left = 1000 - target['settings'].get('waiver_budget_used', 0)

    # --- what this team could otherwise start: the bar a claim has to clear ---
    # Own players are judged on the same regressed basis as the targets, so a
    # bench player's hot week does not make him look unbeatable.
    my_vals = {pid: value(pid)[1] for pid in roster_ids}
    weakest = {}
    for p in POS:
        cands = sorted((my_vals[pid] for pid in roster_ids if pos_of(pid) == p))
        need = sum(1 for s in slots if s == p)
        # the value of the last man this team would start at the position
        weakest[p] = cands[-need] if need and len(cands) >= need else 0.0
    flex_pool = sorted((my_vals[pid] for pid in roster_ids if pos_of(pid) in FLEX_OK), reverse=True)
    n_flex = sum(1 for s in slots if s in ('FLEX', 'SUPER_FLEX'))
    n_fixed = sum(1 for s in slots if s in FLEX_OK)
    flex_bar = flex_pool[n_fixed + n_flex - 1] if len(flex_pool) >= n_fixed + n_flex else 0.0

    # --- free agents ---
    rostered = set()
    for e in last:
        rostered |= set(e.get('players') or [])
    fas = []
    for pid in pts:
        p = players.get(pid) or {}
        if pos_of(pid) not in POS or pid in rostered or not p.get('team'):
            continue
        obs, proj, games = value(pid)
        if proj <= 0:
            continue
        bar = min(weakest.get(pos_of(pid), 0.0), flex_bar) if pos_of(pid) in FLEX_OK else weakest.get(pos_of(pid), 0.0)
        upgrade = round(proj - bar, 2)
        if upgrade <= 0:
            continue
        fas.append({
            'pid': pid, 'player': name_of(pid), 'pos': pos_of(pid), 'nfl': p.get('team'),
            'injury': p.get('injury_status'),
            'observed': obs, 'value': proj, 'games': games, 'keep': keep_share(games),
            'opportunity': opportunity(pid),
            'upgrade': upgrade, 'replaces_bar': round(bar, 2),
            'confidence': 'low' if games < 3 else ('medium' if games < 6 else 'high'),
            # Points without touches are touchdowns, and touchdowns do not
            # repeat. Under ~4 touches a game the line is an event, not a role.
            'thin_usage': opportunity(pid) < 4 and obs > 4,
        })
    fas.sort(key=lambda f: -f['upgrade'])

    # --- drops: bench first, worst value first; injured-out players lead ---
    drops = sorted(
        ({'pid': pid, 'player': name_of(pid), 'pos': pos_of(pid),
          'value': my_vals[pid], 'injury': (players.get(pid) or {}).get('injury_status')}
         for pid in bench),
        key=lambda d: ((d['injury'] or '') not in ('Out', 'IR', 'Doubtful'), d['value']))
    roster_full = len(roster_ids) >= cap_size
    room = len(drops) if roster_full else max(len(drops), cap_size - len(roster_ids))

    # --- price ---
    # Dollars per point of per-game VOR, from the prior season's same week.
    anchor = prior_week_prices(PRIOR_BIDS, week)
    rate = None
    if os.path.exists(PRIOR_RATES):
        with open(PRIOR_RATES) as fh:
            rate = (json.load(fh).get('price_rate') or {}).get(str(week))
    dollars_per_point = rate['dollars_per_point'] if rate else 20.0
    cap = max(1, int(faab_left * cap_pct / 100))

    picks = []
    available_drops = list(drops)
    for f in fas[:max(0, room)]:
        pick = dict(f)
        pick['value_price'] = max(1, int(round(f['upgrade'] * dollars_per_point)))
        pick['suggested_bid'] = pick['value_price']
        pick['drop'] = None
        if roster_full:
            # Only a player worth LESS than the incoming one is a real drop.
            # Without this the list happily trades away a useful bench piece to
            # make room for a marginal one.
            cand = next((d for d in available_drops if d['value'] < f['value']), None)
            if cand:
                available_drops.remove(cand)
                pick['drop'] = cand
            else:
                pick['blocked'] = 'no drop worth making'
        picks.append(pick)

    # A pick you cannot make room for is not a recommendation.
    for p in picks:
        p['recommended'] = not p.get('blocked') and not p['thin_usage']

    # When the cap binds, scale the whole slate rather than starving the tail:
    # the ranking is the useful part of the output and it should survive.
    for p in picks:
        if not p['recommended']:
            p['suggested_bid'] = None
    live = [p for p in picks if p['recommended']]
    total = sum(p['suggested_bid'] for p in live)
    if total > cap and total:
        for p in live:
            p['suggested_bid'] = max(1, int(round(p['suggested_bid'] * cap / total)))
        while sum(p['suggested_bid'] for p in live) > cap and any(p['suggested_bid'] > 1 for p in live):
            biggest = max(live, key=lambda p: p['suggested_bid'])
            biggest['suggested_bid'] -= 1
    capped = total > cap

    out = {
        'league': league['name'], 'season': season, 'week': week,
        'generated_for': {'team': tname, 'manager': tmgr, 'roster_id': rid},
        'team_state': {
            'last_week_points': round(my_pts, 2), 'last_week_rank': my_rank,
            'teams_alive': len(scores), 'faab_left': faab_left,
            'roster_size': len(roster_ids), 'roster_cap': cap_size,
            'roster_full': roster_full, 'starters': len(starters),
            'lowest_score_last_week': round(scores[0][0], 2),
        },
        'budget': {'cap': cap, 'cap_pct': cap_pct, 'capped': capped,
                   'committed': sum(p['suggested_bid'] for p in picks if p['recommended']),
                   'dollars_per_point': dollars_per_point},
        'anchor': anchor,
        'picks': picks,
        'drops': drops,
        'avoid': [f for f in fas[max(0, room):max(0, room) + 4]],
        'weakest_startable': {p: round(weakest[p], 2) for p in POS} | {'FLEX': round(flex_bar, 2)},
    }
    with open(args.out, 'w') as fh:
        json.dump(out, fh, indent=1)

    print(f"{args.out}: {tname} — week {week}, ${faab_left} FAAB, "
          f"{len(roster_ids)}/{cap_size} roster{' (FULL)' if roster_full else ''}")
    print(f"  last week {my_pts:.2f} ({my_rank} of {len(scores)}); low score {scores[0][0]:.2f} was chopped")
    if anchor:
        print(f"  prior season wk{week}: median winning bid ${anchor['median']:.0f}, p75 ${anchor['p75']}, "
              f"max ${anchor['max']} | ${dollars_per_point}/pt of delivered VOR")
    print(f"  cap ${cap} ({cap_pct}% of remaining){' — BINDING, slate scaled down' if capped else ''}; "
          f"committing ${out['budget']['committed']}")
    for p in picks:
        d = f" | drop {p['drop']['player']}" if p['drop'] else f" | {p.get('blocked','')}"
        if p['thin_usage']:
            d += ' | THIN USAGE - td-inflated'
        if not p['recommended']:
            d += '  [watch only]'
        amt = f"${p['suggested_bid']}" if p['suggested_bid'] else '  --'
        print(f"  {amt:>5}  {p['player']:<22}{p['pos']:<4}{p['nfl']:<5} "
              f"obs +{p['observed']:<5.1f} -> proj +{p['value']:<5.2f} (keep {p['keep']:.0%}) "
              f"upg +{p['upgrade']:<5.2f} opp={p['opportunity']:<5}{d}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
