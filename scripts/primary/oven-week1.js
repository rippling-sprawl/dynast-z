/* Baker's Oven — Week 1 projections (window.OvenWeek1).
 *
 * Every team in the league, its drafted lineup priced against Sleeper's Week 1
 * projections under this league's own scoring, sorted by total. The question it
 * answers is the one a draft room argues about the moment the last pick is in:
 * whose roster actually scores the most next Sunday.
 *
 * The board runs highest-first, except in a chopped league (`settings.type` 3),
 * where losing the week is what costs you the season — there it runs
 * lowest-first, so the team on the block leads the page. See choppedOrder().
 *
 * Where the numbers come from
 * ---------------------------
 * Sleeper's projection endpoint returns a RAW STAT LINE per player, not a point
 * total — the same shape as the stats endpoint scripts/fetch_nfl_weekly.py
 * pulls, and the same vocabulary as a league's scoring_settings. That is the
 * whole reason this view can exist honestly: the three point totals Sleeper
 * ships alongside (pts_ppr / pts_half_ppr / pts_std) are three fixed formats and
 * none of them is your league, but the stat line dotted with your scoring table
 * IS. OvenWeekly.score() already performs exactly that product.
 *
 * Nothing here needs the 5 MB player database. A draft pick carries the name,
 * position and NFL team in its metadata and the Sleeper id as `player_id`,
 * which is all it takes to price a player and find his opponent.
 *
 * The filters
 * -----------
 * Rounds and positions are include-lists, both fully checked at rest. Unchecking
 * one does not hide those players — it takes them out of the lineup and out of
 * the total, and renders them faded under the starters. That is the point:
 * "what does this roster score without its quarterbacks" and "who won rounds
 * 1-3" are questions about the same board, and a filter that hid the answer's
 * inputs would only show you the arithmetic you asked for and not the players
 * it removed.
 */
(function (global) {
  'use strict';

  var C = global.OVEN;
  var D = global.document;

  function esc(s) { return global.OvenBoard.esc(s); }

  // Positional reading order, for the filter row and the bench tail. Anything a
  // league declares that isn't in here sorts after it, alphabetically.
  var POS_ORDER = ['QB', 'RB', 'WR', 'TE', 'K', 'DEF'];

  var state = {
    ctx: null,          // { league, teams, ... } from OvenDraft.loadLeague
    myRosterId: null,
    players: [],        // every drafted player, flat, already priced
    rounds: [],         // rounds that actually have picks, ascending
    positions: [],      // positions that actually have picks, in POS_ORDER
    onRound: {},        // round  -> bool, the include-list
    onPos: {},          // pos    -> bool, the include-list
    els: {},
  };

  /* ---------- data ---------- */

  /* Default fetch caching, deliberately not `cache: 'no-store'`. This is ~580 KB
   * and Sleeper serves it with s-maxage=600; a projection for a game that hasn't
   * been played does not move minute to minute, and a reload inside that window
   * should cost nothing. Contrast OvenDraft.api(), which IS no-store because
   * picks move every eight seconds. */
  function loadProjections(season, week) {
    var url = C.SLEEPER_PROJ
      .replace('{season}', String(season))
      .replace('{week}', String(week));
    return fetch(url).then(function (r) {
      if (!r.ok) throw new Error('Sleeper projections unavailable (' + r.status + ')');
      return r.json();
    });
  }

  function loadSchedule() {
    return fetch(C.SCHEDULE_DATA).then(function (r) {
      return r.ok ? r.json() : null;
    }).catch(function () { return null; });
  }

  function alias(abbr) { return C.SCHEDULE_ALIAS[abbr] || abbr; }

  /* {TEAM: {opp, home}} for one week, in Sleeper's spelling.
   *
   * Both sides of every game go through the alias map, not just the key — a
   * Washington opponent has to read WAS on the row of the team playing them too,
   * or half the fix is invisible. */
  function weekOpponents(schedule, week) {
    var out = {};
    if (!schedule || !schedule.weeks) return out;
    var wk = schedule.weeks.filter(function (w) { return w.week === week; })[0];
    if (!wk) return out;
    (wk.games || []).forEach(function (g) {
      var away = alias(g.away), home = alias(g.home);
      out[away] = { opp: home, home: false };
      out[home] = { opp: away, home: true };
    });
    return out;
  }

  function oppLabel(team, opps) {
    var o = team ? opps[team] : null;
    return o ? (o.home ? 'vs ' + o.opp : '@ ' + o.opp) : '';
  }

  function pickName(p) {
    var m = p.metadata || {};
    var nm = ((m.first_name || '') + ' ' + (m.last_name || '')).trim();
    return nm || 'Pick ' + p.pick_no;
  }

  /* Every pick in the draft, priced, with the roster that owns it.
   *
   * `roster_id` on a pick is the authority when Sleeper sets it; mock drafts and
   * some pre-draft keeper rows leave it null, so the pick plan — which already
   * honours traded picks — is the fallback. Same rule the drawer's Team view
   * uses, for the same reason.
   *
   * `gp` is what separates "no opinion" from "opinion of zero", and the
   * distinction is most of the file's honesty. Sleeper returns an entry for all
   * ~9400 players but only ~980 of them carry a projected line; the other 8400
   * hold nothing but an ADP, and scoring one of those would produce a confident
   * 0.0 for every undrafted rookie on the board. Verified against the live
   * payload: no entry without `gp` carries a single scorable stat, and every
   * entry with it does — including the IDP-only lines, which score in a league
   * that starts them and legitimately score 0 in one that doesn't.
   *
   * So a player with no `gp` gets `pts: null`, renders as an em dash, and says
   * nobody has an opinion. A player with `gp` and no points under these rules
   * gets 0.0, which is an opinion. Both add nothing to a total. */
  function buildPlayers(ctx, picks, plan, proj, opps, teamsCount) {
    var planOwner = {};
    (plan || []).forEach(function (p) { planOwner[p.pick_no] = p.owner; });
    var scoring = (ctx.league && ctx.league.scoring_settings) || {};

    return (picks || []).map(function (p) {
      var m = p.metadata || {};
      var line = p.player_id != null ? proj[String(p.player_id)] : null;
      var team = m.team || '';
      return {
        rosterId: p.roster_id != null ? p.roster_id : planOwner[p.pick_no],
        pickNo: p.pick_no,
        round: p.round || Math.ceil(p.pick_no / (teamsCount || 1)),
        isKeeper: !!p.is_keeper,
        name: pickName(p),
        pos: global.OvenBoard.normPos(m.position),
        team: team,
        opp: oppLabel(team, opps),
        pts: line && line.gp ? global.OvenWeekly.score(line, scoring) : null,
      };
    }).filter(function (pl) { return pl.rosterId != null; });
  }

  /* ---------- the model, re-run on every filter change ---------- */

  function included(pl) {
    return state.onRound[pl.round] !== false && state.onPos[pl.pos || 'OTHER'] !== false;
  }

  /* One team's lineup under the current filters.
   *
   * Projection-descending into the most specific open slot — see
   * OVEN.fillLineup, which the drawer's Team view shares. The order is what
   * differs and it is the whole model: this view asks what the roster SCORES, so
   * the best eligible leftover takes the flex. Filling in draft order instead
   * would sit a 7-point RB2 in front of a 17-point third receiver.
   *
   * A keeper with no pick round still filters as whatever round Sleeper filed
   * him under, which is the round he cost. */
  function buildTeam(team, rosterPositions) {
    var mine = state.players.filter(function (pl) { return pl.rosterId === team.roster_id; });
    var take = mine.filter(included).sort(function (a, b) {
      return (b.pts == null ? -1 : b.pts) - (a.pts == null ? -1 : a.pts);
    });

    var fill = C.fillLineup(rosterPositions, take);
    var starters = fill ? fill.starters : [];
    var total = 0;
    starters.forEach(function (sl) { if (sl.player && sl.player.pts) total += sl.player.pts; });

    // Everyone the total doesn't count, newest pick last: the bench overflow the
    // lineup couldn't hold, then whoever the filters took out. Both are faded,
    // because both are the same fact — not in this number.
    var starting = {};
    starters.forEach(function (sl) { if (sl.player) starting[sl.player.pickNo] = true; });
    var out = mine.filter(function (pl) { return !starting[pl.pickNo]; })
      .sort(function (a, b) { return a.pickNo - b.pickNo; });

    return {
      team: team,
      starters: starters,
      out: out,
      counted: starters.filter(function (sl) { return sl.player; }).length,
      slots: starters.length,
      total: total,
    };
  }

  /* Which end of the board matters, taken from the league's own format.
   *
   * A chopped league eliminates its lowest score every week, so the card you
   * open the page to read is the one in last — the board runs uphill and the
   * team in trouble is the first thing on it. Every other format is asking who
   * won the draft, and that team goes first.
   *
   * Unknown type falls in with the majority: descending is the answer to the
   * question this page is normally asked. */
  function choppedOrder() {
    var t = C.leagueType(state.ctx && state.ctx.league);
    return !!t && t.code === C.LEAGUE_TYPE_CHOPPED;
  }

  function buildTeams() {
    var ctx = state.ctx;
    var rosterPositions = (ctx.league && ctx.league.roster_positions) || [];
    var dir = choppedOrder() ? 1 : -1;
    return ctx.teams.map(function (t) { return buildTeam(t, rosterPositions); })
      // Ties break on roster id, always in the same direction, so a re-render
      // can't shuffle two equal teams past each other.
      .sort(function (a, b) { return dir * (a.total - b.total) || (a.team.roster_id - b.team.roster_id); });
  }

  /* ---------- render ---------- */

  function fmt(n) { return n == null ? '—' : n.toFixed(1); }

  function statTile(label, value) {
    return '<div><div class="oven-stat-label">' + label + '</div>' +
      '<div class="oven-stat-value mono">' + value + '</div></div>';
  }

  function renderStats(teams) {
    var totals = teams.map(function (t) { return t.total; });
    var lo = Math.min.apply(null, totals), hi = Math.max.apply(null, totals);
    var counted = teams.reduce(function (n, t) { return n + t.counted; }, 0);
    var avg = totals.reduce(function (a, b) { return a + b; }, 0) / (totals.length || 1);

    state.els.stats.innerHTML =
      statTile('Teams', teams.length) +
      statTile('Starters priced', counted) +
      statTile('Avg total', fmt(avg)) +
      statTile('High', fmt(hi)) +
      statTile('Low', fmt(lo)) +
      statTile('Spread', fmt(hi - lo));
  }

  function ptsChip(pl) {
    return '<span class="oven-tp-chip oven-w1-pts">' + esc(fmt(pl.pts)) + '</span>';
  }

  function posBadge(pos) {
    return '<span class="player-pos pos-' + esc(pos || 'OTHER') + '">' +
      esc(pos || '—') + '</span>';
  }

  /* The opponent replaces the NFL team the drawer prints here, because on this
   * view it is the more useful half of the same fact — "vs BAL" already implies
   * IND, and the game is the reason for the number beside it.
   *
   * Its own column rather than a tail on the name line, which is where it
   * started: the name line ellipsizes, and at three cards across it was eating
   * the opponent off the end of every long name. The name is the part that can
   * survive being cut short — you still recognise "De'Zhaun Stribling…" — and
   * "vs …" is nothing at all. */
  function nameCell(pl) {
    return '<div class="oven-tp-main"><div class="oven-tp-name">' +
      '<span class="oven-tp-name-text">' + esc(pl.name) + '</span>' +
    '</div></div>';
  }

  function oppCell(pl) {
    return '<span class="oven-w1-opp">' + esc(pl.opp || '') + '</span>';
  }

  function slotRow(slotPos, pl) {
    if (!pl) {
      return '<div class="oven-tp-row compact oven-tm-row is-empty">' +
        '<div class="oven-tm-slot">' + esc(C.SLOT_LABEL[slotPos] || slotPos) + '</div>' +
        '<div class="oven-tp-main"><div class="oven-tp-name oven-tm-open">Open</div></div>' +
        '<span class="oven-w1-opp"></span>' +
        '<span class="oven-tp-chip oven-w1-pts">—</span>' +
      '</div>';
    }
    return '<div class="oven-tp-row compact oven-tm-row">' +
      '<div class="oven-tm-slot">' + esc(C.SLOT_LABEL[slotPos] || slotPos) + '</div>' +
      posBadge(pl.pos) + nameCell(pl) + oppCell(pl) + ptsChip(pl) +
    '</div>';
  }

  // Not counted, so it says WHY instead of where: the round it cost, which is
  // also the thing the round filter is addressed to.
  function outRow(pl) {
    return '<div class="oven-tp-row compact oven-tm-row oven-w1-out' +
      (included(pl) ? '' : ' is-cut') + '">' +
      '<div class="oven-tm-slot">' + (pl.isKeeper ? 'KEPT' : 'R' + pl.round) + '</div>' +
      posBadge(pl.pos) + nameCell(pl) + oppCell(pl) + ptsChip(pl) +
    '</div>';
  }

  function card(t, rank, lo, span) {
    // 0 at the coldest lineup, 1 at the hottest, and the pill mixes frost into
    // flame by that much. The Oven has two hue axes and this is the warm one —
    // see the palette note at the top of bakers-oven.css. color-mix over the
    // tokens rather than a computed hex, so the theme toggle carries it for free.
    var heat = span > 0 ? (t.total - lo) / span : 1;

    return '<article class="oven-w1-card' +
        (t.team.roster_id === state.myRosterId ? ' is-me' : '') + '">' +
      '<header class="oven-w1-head">' +
        '<span class="oven-w1-rank">' + rank + '</span>' +
        '<span class="oven-team-name">' + esc(t.team.teamName) + '</span>' +
        '<span class="oven-w1-total" style="--w1-heat:' + heat.toFixed(3) + '">' +
          esc(fmt(t.total)) + '</span>' +
      '</header>' +
      '<div class="oven-w1-rows">' +
        (t.slots
          ? t.starters.map(function (sl) { return slotRow(sl.pos, sl.player); }).join('')
          : '<div class="oven-tp-none">This league declares no starting slots.</div>') +
        (t.out.length
          ? '<div class="oven-tp-group">Not counted' +
              '<span class="oven-tm-note">' + t.out.length + '</span></div>' +
            t.out.map(outRow).join('')
          : '') +
      '</div>' +
    '</article>';
  }

  function render() {
    var teams = buildTeams();
    // Sleeper always returns rosters for a real league, so this is a guard
    // against a fixture rather than a state the page reaches — but Math.min of
    // nothing is Infinity, and "Infinity" in the High tile is a worse failure
    // than an empty grid.
    if (!teams.length) {
      state.els.stats.innerHTML = '';
      state.els.grid.innerHTML = '<div class="oven-tp-none">No teams in this league.</div>';
      return;
    }
    renderStats(teams);

    var totals = teams.map(function (t) { return t.total; });
    var lo = Math.min.apply(null, totals), span = Math.max.apply(null, totals) - lo;

    // Rank 1 is the highest total whichever way the list runs — it is a
    // standing, not a position in the grid. In a chopped league the board goes
    // uphill and the numeral counts down beside it; everywhere else the two
    // read together from 1.
    var up = choppedOrder();
    state.els.grid.innerHTML = teams.map(function (t, i) {
      return card(t, up ? teams.length - i : i + 1, lo, span);
    }).join('');
  }

  /* ---------- filters ---------- */

  function chip(attr, value, label, on) {
    return '<button type="button" class="oven-chip' + (on ? ' active' : '') + '" ' +
      'data-' + attr + '="' + esc(value) + '" aria-pressed="' + (on ? 'true' : 'false') + '">' +
      esc(label) + '</button>';
  }

  function allOn(map, list) {
    return list.every(function (k) { return map[k] !== false; });
  }

  function renderFilters() {
    // "All" is a chip rather than a reset link so the row has one vocabulary,
    // and it lights up only when nothing is excluded — which makes it a readout
    // of whether a filter is on as well as the way to clear it.
    state.els.filters.innerHTML =
      '<div class="oven-filter-row">' +
        '<span class="oven-filter-label">Rounds</span>' +
        chip('round', 'all', 'All', allOn(state.onRound, state.rounds)) +
        state.rounds.map(function (r) {
          return chip('round', String(r), String(r), state.onRound[r] !== false);
        }).join('') +
      '</div>' +
      '<div class="oven-filter-row">' +
        '<span class="oven-filter-label">Positions</span>' +
        chip('pos', 'all', 'All', allOn(state.onPos, state.positions)) +
        state.positions.map(function (p) {
          return chip('pos', p, p, state.onPos[p] !== false);
        }).join('') +
      '</div>';
  }

  function toggle(map, list, value) {
    if (value === 'all') {
      // Already whole? Then All is the only chip with nothing to do — leave it,
      // rather than inverting into an empty board nobody asked for.
      if (allOn(map, list)) return;
      list.forEach(function (k) { map[k] = true; });
      return;
    }
    map[value] = map[value] === false;
  }

  function wireFilters() {
    // Delegated, so re-rendering the rows never needs the chips re-bound.
    state.els.filters.addEventListener('click', function (e) {
      var btn = e.target.closest('.oven-chip');
      if (!btn) return;
      var r = btn.getAttribute('data-round'), p = btn.getAttribute('data-pos');
      if (r != null) toggle(state.onRound, state.rounds, r === 'all' ? 'all' : Number(r));
      else if (p != null) toggle(state.onPos, state.positions, p);
      else return;
      renderFilters();
      render();
    });
  }

  /* ---------- boot ---------- */

  function mount(opts) {
    state.ctx = opts.ctx;
    state.myRosterId = opts.myRosterId != null ? opts.myRosterId : null;
    state.els = {
      stats: D.getElementById(opts.statsId),
      filters: D.getElementById(opts.filtersId),
      grid: D.getElementById(opts.gridId),
    };

    var teamsCount = (opts.draft && opts.draft.settings && opts.draft.settings.teams) ||
      state.ctx.teams.length;
    state.players = buildPlayers(state.ctx, opts.picks, opts.plan, opts.proj, opts.opps, teamsCount);

    // The filter rows offer what the draft actually contains, not what it could
    // contain. A league scheduled for 18 rounds that has run five has three
    // chips of round nobody can use, and a K chip on a league that rosters no
    // kicker is a control wired to nothing.
    var seenR = {}, seenP = {};
    state.players.forEach(function (pl) {
      seenR[pl.round] = true;
      seenP[pl.pos || 'OTHER'] = true;
    });
    state.rounds = Object.keys(seenR).map(Number).sort(function (a, b) { return a - b; });
    state.positions = POS_ORDER.filter(function (p) { return seenP[p]; })
      .concat(Object.keys(seenP).filter(function (p) { return POS_ORDER.indexOf(p) === -1; }).sort());

    renderFilters();
    wireFilters();
    render();
  }

  global.OvenWeek1 = {
    mount: mount,
    // The model, callable without the page — same courtesy OvenTargets extends
    // to project() and team(), and the same reason: this arithmetic is worth
    // checking against a fixture in a console.
    loadProjections: loadProjections,
    loadSchedule: loadSchedule,
    weekOpponents: weekOpponents,
    buildPlayers: buildPlayers,
    state: state,
  };
})(window);
