#!/usr/bin/env python3
"""
Build data/waiver-bids-2025.csv: every FAAB waiver bid placed in the Cut Throat
2025 season, winning and losing alike.

Why this exists
---------------
Sleeper's own UI shows you the claims that *processed*. The interesting half of
a FAAB market is the half that did not: what the player was actually worth to
the room, how close the runner-up came, who was priced out. The transaction
endpoint returns both — a losing claim is a real row with status "failed" — so
this pulls all 17 legs and keeps every bid.

Three things the raw feed gets you wrong if you take it at face value:

  * The high bid does not always win. Sleeper voids a claim before price is
    ever compared if the manager is over budget or has no roster room, so the
    log contains $375 losing to $290. The failure reason is in metadata.notes
    and is normalised into the `fail_reason` column here — 'outbid' is a real
    loss on price, 'over_budget' and 'roster_full' are not.

  * A manager can queue the same player in several claim slots, at the same
    price, as insurance against the roster-full void above. Those are genuinely
    distinct transactions and all are kept; anything counting *bidders* rather
    than *bids* has to collapse them by manager first (/league/waivers does).

  * One transaction can add more than one player. Rows are emitted per added
    player and share a transaction_id.

KNOWN LIMITATION — the `position` and `nfl_team` columns come from the players
endpoint, which only ever describes a player as he is TODAY. They are not the
team he was on when the bid was placed: the 2025 file records A.J. Brown as NE
because that is where he is now, not PHI where he played that season. Nothing
derived from this data is affected — bids, points and rosters all key on
player_id — but do not read nfl_team as history. Fixing it needs a source of
week-by-week team assignments, which Sleeper's stats endpoint does not carry.

The per-roster sums of the `won` rows reconcile exactly against each roster's
settings.waiver_budget_used, which is the check at the bottom of this file.

Usage
-----
    python3 scripts/fetch_waiver_bids.py [--league LEAGUE_ID] [--out PATH]
"""

import argparse
import csv
import datetime
import json
import sys
import urllib.request

LEAGUE_ID = '1264056168385355776'          # Cut Throat, 2025
OUT = 'data/waiver-bids-2025.csv'
API = 'https://api.sleeper.app/v1'
MAX_LEG = 18                               # regular season + the empty tail

# metadata.notes is prose aimed at the manager; the CSV wants a token.
REASONS = {
    'This player was claimed by another owner.': 'outbid',
    'You are over the budget for this transaction.': 'over_budget',
    'Unfortunately, your roster will have too many players after this transaction.': 'roster_full',
}

COLUMNS = ['week', 'date', 'manager', 'team', 'player', 'position', 'nfl_team',
           'bid', 'result', 'fail_reason', 'dropped', 'roster_id', 'transaction_id']


def get(path):
    with urllib.request.urlopen(f'{API}/{path}', timeout=60) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--league', default=LEAGUE_ID)
    ap.add_argument('--out', default=OUT)
    args = ap.parse_args()

    users = {u['user_id']: u for u in get(f'league/{args.league}/users')}
    rosters = get(f'league/{args.league}/rosters')
    owner_of = {r['roster_id']: r.get('owner_id') for r in rosters}
    # ~15 MB, and the only place a player_id becomes a name.
    players = get('players/nfl')

    def who(roster_id):
        u = users.get(owner_of.get(roster_id)) or {}
        name = u.get('display_name') or f'roster {roster_id}'
        return name, (u.get('metadata') or {}).get('team_name') or name

    def player(pid):
        p = players.get(str(pid)) or {}
        full = p.get('full_name') or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
        return full or str(pid), p.get('position') or '', p.get('team') or 'FA'

    rows = []
    for leg in range(1, MAX_LEG + 1):
        for t in get(f'league/{args.league}/transactions/{leg}'):
            if t['type'] != 'waiver':
                continue
            bid = (t.get('settings') or {}).get('waiver_bid')
            if bid is None:                      # a waiver-priority league would land here
                continue
            roster_id = t['roster_ids'][0]
            manager, team = who(roster_id)
            won = t['status'] == 'complete'
            note = (t.get('metadata') or {}).get('notes', '')
            dropped = '; '.join(player(d)[0] for d in (t.get('drops') or {}))
            for pid in (t.get('adds') or {}):
                name, pos, nfl = player(pid)
                rows.append({
                    'week': t['leg'],
                    'date': datetime.datetime.fromtimestamp(t['created'] / 1000).strftime('%Y-%m-%d %H:%M'),
                    'manager': manager, 'team': team,
                    'player': name, 'position': pos, 'nfl_team': nfl,
                    'bid': bid,
                    'result': 'won' if won else 'lost',
                    'fail_reason': '' if won else REASONS.get(note, note),
                    'dropped': dropped,
                    'roster_id': roster_id,
                    'transaction_id': t['transaction_id'],
                    '_ms': t['created'],
                })

    rows.sort(key=lambda r: (r['week'], r['_ms'], -r['bid']))
    with open(args.out, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)

    # Reconcile: spend per roster must equal what Sleeper says each team burned.
    spent = {}
    for r in rows:
        if r['result'] == 'won':
            spent[r['roster_id']] = spent.get(r['roster_id'], 0) + r['bid']
    bad = [(r['roster_id'], spent.get(r['roster_id'], 0), r['settings'].get('waiver_budget_used', 0))
           for r in rosters
           if spent.get(r['roster_id'], 0) != r['settings'].get('waiver_budget_used', 0)]

    won = sum(r['result'] == 'won' for r in rows)
    print(f'{args.out}: {len(rows)} bids, {won} won, ${sum(spent.values()):,} spent')
    if bad:
        print('BUDGET MISMATCH (roster_id, computed, sleeper):', bad, file=sys.stderr)
        return 1
    print('budget reconciles against every roster')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
