/* The Baker's Oven — Targets & Projections (window.OvenTargets).
 *
 * A mountable right-edge drawer, not a page. It injects its own tab, panel and
 * event wiring into <body>, reads everything it needs through one accessor the
 * host view supplies, and persists only a list of player keys — so the same
 * component drops into the index, the big board, or anything later that can
 * describe a board and a draft:
 *
 *   OvenTargets.mount({ getState: function () { return {
 *     rows, drafted, picks, plan, teamsCount, rounds, myRosterId, rosterPositions
 *   }; } });
 *   OvenTargets.refresh();   // after any poll
 *
 * Three sub-views:
 *   targets     — the queue, grouped by position, in my rank order
 *   projections — rounds 1..N, keepers and made picks filled in, future rounds
 *                 simulated forward
 *   team        — my lineup as the league defines it (roster_positions), filled
 *                 from what I've actually kept and drafted
 *
 * The projection model, stated plainly because every number in that view rests
 * on it: other teams draft to consensus (FantasyPros ECR), so between my picks
 * the top N of the market-ordered pool disappear. At each of my picks I take the
 * best player left on MY board, where "best" is my rank pulled forward by the
 * CSV grade and by having queued him. That choice is then removed from the pool,
 * so round 5 is projected against a board where I already took rounds 1-4 —
 * that look-ahead is the whole reason the view exists.
 *
 * On top of the rank-ordered rows, every pick carries a positional floor: QB,
 * RB, WR and TE each show their best remaining player, so no pick can render as
 * an undifferentiated wall of RB/WR with the QB or TE fallback invisible.
 */
(function (global) {
  'use strict';

  var C = global.OVEN;
  // Everything goes through the injected global — this module is mounted by
  // several views and is easier to exercise headless when it never reaches for
  // a bare `document`.
  var D = global.document;

  var POS_ORDER = ['QB', 'RB', 'WR', 'TE', 'K', 'DEF'];

  // Positions the projection guarantees a row for. K and DEF are out: they go in
  // the last two rounds regardless of who's left, so a "best kicker available"
  // row is noise at every pick that isn't one of those two.
  var FLOOR_POS = ['QB', 'RB', 'WR', 'TE'];

  /* Which players a lineup slot accepts, keyed by Sleeper's `roster_positions`
   * vocabulary. A single-position slot is its own eligibility list, so an
   * unrecognized slot ('DL', a league-specific label) still behaves sanely by
   * only accepting its own name. Slot specificity is `elig.length` — that is
   * what makes a QB land at QB rather than in the SUPER_FLEX beside it. */
  var SLOT_ELIGIBLE = {
    QB: ['QB'], RB: ['RB'], WR: ['WR'], TE: ['TE'], K: ['K'], DEF: ['DEF'],
    FLEX: ['RB', 'WR', 'TE'],
    WRRB_FLEX: ['RB', 'WR'],
    REC_FLEX: ['WR', 'TE'],
    SUPER_FLEX: ['QB', 'RB', 'WR', 'TE'],
    IDP_FLEX: ['DL', 'LB', 'DB'],
  };

  // Sleeper's slot names are wide enough to break the label column; these are
  // the only ones that need shortening.
  var SLOT_LABEL = { SUPER_FLEX: 'SFLEX', WRRB_FLEX: 'W/R', REC_FLEX: 'W/T', IDP_FLEX: 'IDP' };

  // Reserve slots exist on the roster but are never drafted into — showing an
  // always-empty IR row would read as a lineup hole.
  var RESERVE_SLOTS = { IR: true, TAXI: true };

  var state = {
    mounted: false,
    open: false,
    view: 'targets',
    keys: [],          // board keys, insertion order
    getState: null,
    els: {},
    // Resolved at mount from opts.leagueId. The queue is per-league: a stored
    // key only resolves against the CSV imported for that league, and the
    // projection is built from that league's round plan.
    syncKey: C.TARGETS_SYNC_KEY,
    storageKey: null,
  };

  function esc(s) { return global.OvenBoard.esc(s); }

  /* ---------- the queue ---------- */

  function has(key) { return state.keys.indexOf(key) !== -1; }

  function persist() {
    var payload = { keys: state.keys, updatedAt: Date.now() };
    if (typeof global.saveWithSync === 'function') {
      global.saveWithSync(C.SYNC_SPORT, state.syncKey, state.storageKey, payload);
    } else {
      try { global.localStorage.setItem(state.storageKey, JSON.stringify(payload)); } catch (e) { /* private mode */ }
    }
  }

  function add(key) {
    if (!key || has(key)) return false;
    state.keys.push(key);
    persist();
    markBoard();
    render();
    return true;
  }

  function remove(key) {
    var i = state.keys.indexOf(key);
    if (i === -1) return false;
    state.keys.splice(i, 1);
    persist();
    markBoard();
    render();
    return true;
  }

  function toggle(key) { return has(key) ? (remove(key), false) : (add(key), true); }

  function clear() {
    if (!state.keys.length) return;
    state.keys = [];
    persist();
    markBoard();
    render();
  }

  /* ---------- host state ---------- */

  function snapshot() { return normalize((state.getState && state.getState()) || {}); }

  function normalize(s) {
    return {
      rows: s.rows || [],
      drafted: s.drafted || {},
      picks: s.picks || [],
      plan: s.plan || [],
      teamsCount: s.teamsCount || 12,
      rounds: s.rounds || 16,
      myRosterId: s.myRosterId,
      // Sleeper's league.roster_positions, verbatim. The lineup is the league's
      // to define — never a default guessed from the draft's round count.
      rosterPositions: s.rosterPositions || [],
    };
  }

  function rowsByKey(rows) {
    var m = {};
    rows.forEach(function (r) { m[r.key] = r; });
    return m;
  }

  /* ---------- projection math ---------- */

  // Who the room takes. Consensus, not my board — the league is not drafting
  // off my sheet, and using my order here would make every target look safe.
  function marketRank(r) {
    if (r.fpRank != null) return r.fpRank;
    return r.myRank == null ? 9999 : r.myRank;
  }

  // Who I take. My rank, pulled forward by an explicit grade and by having
  // queued him — the two places I've already recorded an opinion.
  function adjRank(r) {
    var base = r.myRank == null ? 9999 : r.myRank;
    var grade = (C.GRADE_HEAT[r.grade] || 0) * C.PROJ_GRADE_WEIGHT;
    return base - grade - (has(r.key) ? C.PROJ_TARGET_BONUS : 0);
  }

  function byMarket(a, b) {
    return (marketRank(a) - marketRank(b)) ||
      ((a.myRank == null ? 9999 : a.myRank) - (b.myRank == null ? 9999 : b.myRank));
  }
  function byAdj(a, b) { return adjRank(a) - adjRank(b); }

  /* Walk my remaining picks in order, consuming the pool as the room drafts.
   * Returns per-pick projections plus, for each queued player, the window of
   * rounds he survives to — which is what the targets view reports back. */
  function buildProjection(s) {
    var filled = {};
    (s.picks || []).forEach(function (p) { filled[p.pick_no] = p; });

    var total = s.teamsCount * s.rounds;
    var onTheClock = total + 1;
    for (var n = 1; n <= total; n++) { if (!filled[n]) { onTheClock = n; break; } }

    var mine = (s.plan || [])
      .filter(function (p) { return p.owner === s.myRosterId; })
      .sort(function (a, b) { return a.pick_no - b.pick_no; });

    var upcoming = mine.filter(function (p) { return !filled[p.pick_no] && p.pick_no >= onTheClock; });

    // Unfilled picks belonging to everyone else ahead of each of my turns.
    var gaps = [], cursor = onTheClock;
    upcoming.forEach(function (p) {
      var cnt = 0;
      for (var i = cursor; i < p.pick_no; i++) if (!filled[i]) cnt++;
      gaps.push(cnt);
      cursor = p.pick_no + 1;
    });

    var pool = s.rows.filter(function (r) { return !s.drafted[r.key]; }).sort(byMarket);

    var byPick = {};
    var windows = {};   // key -> { first, last, take } in rounds

    upcoming.forEach(function (p, i) {
      pool = pool.slice(gaps[i]);                 // the room drafts to consensus

      var boardOrder = pool.slice().sort(byAdj);
      var chosen = boardOrder[0] || null;

      var seen = {}, entries = [];
      boardOrder.slice(0, C.PROJ_PROJECTED_SHOWN).forEach(function (r) {
        seen[r.key] = { row: r, proj: true, tgt: has(r.key) };
        entries.push(seen[r.key]);
      });
      boardOrder.filter(function (r) { return has(r.key); })
        .slice(0, C.PROJ_MAX_ENTRIES)
        .forEach(function (r) {
          if (seen[r.key]) { seen[r.key].tgt = true; return; }
          seen[r.key] = { row: r, proj: false, tgt: true };
          entries.push(seen[r.key]);
        });

      entries.sort(function (a, b) { return byAdj(a.row, b.row); });
      entries = entries.slice(0, C.PROJ_MAX_ENTRIES);

      /* Positional floor. Rank order alone can hand you six receivers and no
       * answer to "what if the room runs QBs before this pick?" — so every
       * FLOOR_POS with a body left on the board contributes its best remaining
       * player here, added past the entry ceiling rather than displacing the
       * rank-order picks. They sort in by adjusted rank, so a filler at QB40
       * lands at the bottom of the pick where it reads as the fallback it is. */
      var bestAtPos = {};
      boardOrder.forEach(function (r) {
        if (r.pos && FLOOR_POS.indexOf(r.pos) !== -1 && !bestAtPos[r.pos]) bestAtPos[r.pos] = r;
      });
      var covered = {};
      entries.forEach(function (e) { if (e.row.pos) covered[e.row.pos] = true; });
      Object.keys(bestAtPos).forEach(function (pos) {
        if (covered[pos]) return;   // covered means no duplicate key is possible
        entries.push({ row: bestAtPos[pos], proj: false, tgt: has(bestAtPos[pos].key), floor: true });
      });

      entries.forEach(function (e) { e.best = e.row.pos ? bestAtPos[e.row.pos] === e.row : false; });
      entries.sort(function (a, b) { return byAdj(a.row, b.row); });

      byPick[p.pick_no] = {
        pick: p, entries: entries, chosen: chosen,
        gone: gaps[i], left: pool.length,
      };

      pool.forEach(function (r) {
        if (!has(r.key)) return;
        var w = windows[r.key] || (windows[r.key] = {});
        if (w.first == null) w.first = p.round;
        w.last = p.round;
      });
      if (chosen && has(chosen.key)) {
        (windows[chosen.key] || (windows[chosen.key] = {})).take = p.round;
      }

      if (chosen) pool = pool.filter(function (r) { return r.key !== chosen.key; });
    });

    return {
      byPick: byPick, windows: windows, mine: mine,
      filled: filled, onTheClock: onTheClock, upcoming: upcoming,
    };
  }

  /* ---------- shared row bits ---------- */

  // The board owns the grade badge markup (a heart for `like`, a red X for
  // `fade`, on a row that also recedes), and this drawer is its only caller —
  // all three views below use it.
  //
  // The big board doesn't. Its rows carry a grade CONTROL that already shows the
  // grade, so a badge there would say it twice; this drawer is read-only over
  // the board and the badge is the only thing carrying the grade at all. The two
  // surfaces differing is the design, not drift — see gradeChip() in
  // oven-board.js.
  function gradeChip(r) { return global.OvenBoard.gradeChip(r); }

  function fadedCls(r) { return r && r.grade === 'fade' ? ' faded' : ''; }

  /* Position and team ride the name line — the same two elements as the big
   * board, so a player looks the same in the drawer as he does on the board.
   * The badge carries the positional rank because "RB7" already says "RB". */
  function posBadge(pos, posRank) {
    return '<span class="player-pos pos-' + esc(pos || 'OTHER') + '">' +
      esc(posRank || pos || '—') + '</span>';
  }

  function teamTag(team) {
    return team ? '<span class="oven-tp-team">' + esc(team) + '</span>' : '';
  }

  // Same reason as the board's .oven-name-text: the crossed-off rule has to
  // target the name alone, and text-decoration can't be undone by a child.
  function nameText(name) {
    return '<span class="oven-tp-name-text">' + esc(name) + '</span>';
  }

  function pickName(p) {
    var m = p.metadata || {};
    var nm = ((m.first_name || '') + ' ' + (m.last_name || '')).trim();
    return nm || 'Pick ' + p.pick_no;
  }

  /* ---------- view 1: targets ---------- */

  function windowChip(row, s, proj) {
    var pick = s.drafted[row.key];
    if (pick) {
      return '<span class="oven-tp-chip gone">gone ' +
        esc(global.OvenDraft.roundPickLabel(pick.pick_no, s.teamsCount)) + '</span>';
    }
    var w = proj.windows[row.key];
    if (!proj.upcoming.length) return '';
    if (!w) return '<span class="oven-tp-chip hot">out of reach</span>';
    if (w.take != null) return '<span class="oven-tp-chip hot">yours R' + w.take + '</span>';
    if (w.last === w.first) return '<span class="oven-tp-chip warn">R' + w.first + ' only</span>';
    return '<span class="oven-tp-chip">R' + w.first + '–R' + w.last + '</span>';
  }

  function targetRowHTML(r, s, proj) {
    var drafted = !!s.drafted[r.key];
    return '<div class="oven-tp-row' + (drafted ? ' is-gone' : '') + fadedCls(r) +
      '" data-key="' + esc(r.key) + '">' +
      '<div class="oven-tp-rk">' + (r.myRank == null ? '—' : r.myRank) + '</div>' +
      posBadge(r.pos, r.myPosRank) +
      '<div class="oven-tp-main">' +
        '<div class="oven-tp-name">' + nameText(r.name) + teamTag(r.team) + gradeChip(r) + '</div>' +
      '</div>' +
      windowChip(r, s, proj) +
      '<button class="oven-tp-x" type="button" data-drop="' + esc(r.key) + '" ' +
        'aria-label="Remove ' + esc(r.name) + ' from targets">&times;</button>' +
    '</div>';
  }

  function renderTargets(s, proj) {
    var map = rowsByKey(s.rows);
    var rows = state.keys.map(function (k) { return map[k]; }).filter(Boolean);

    if (!rows.length) {
      return '<div class="oven-tp-empty">' +
        '<strong>No targets yet.</strong>' +
        '<p>Tap the <span class="oven-tp-kbd">+</span> at the end of a player’s row on the big ' +
        'board. Targets are grouped by position and ordered by your rank.</p>' +
        (state.keys.length ? '<p>' + state.keys.length + ' saved target(s) aren’t on the current board.</p>' : '') +
      '</div>';
    }

    var groups = {};
    rows.forEach(function (r) {
      var pos = r.pos || 'OTHER';
      (groups[pos] || (groups[pos] = [])).push(r);
    });

    var order = POS_ORDER.filter(function (p) { return groups[p]; })
      .concat(Object.keys(groups).filter(function (p) { return POS_ORDER.indexOf(p) === -1; }).sort());

    var html = [];
    order.forEach(function (pos) {
      var list = groups[pos].sort(function (a, b) {
        return (a.myRank == null ? 9999 : a.myRank) - (b.myRank == null ? 9999 : b.myRank);
      });
      html.push('<div class="oven-tp-group">' + esc(pos) + '</div>');
      list.forEach(function (r) { html.push(targetRowHTML(r, s, proj)); });
    });
    return html.join('');
  }

  /* ---------- view 2: projections ---------- */

  function projEntryHTML(e, s) {
    var chips = '';
    if (e.proj) chips += '<span class="oven-tp-chip proj">proj</span>';
    if (e.best) chips += '<span class="oven-tp-chip pos">top ' + esc(e.row.pos) + '</span>';
    // Same emoji-needs-a-name rule as the grade badge.
    if (e.tgt) chips += '<span class="oven-tp-chip tgt" role="img" aria-label="target" ' +
      'title="target">🎯</span>';

    return '<div class="oven-tp-row compact' + (e.tgt ? ' is-target' : '') +
      (e.floor ? ' is-floor' : '') + fadedCls(e.row) + '" data-key="' + esc(e.row.key) + '">' +
      '<div class="oven-tp-rk">' + (e.row.myRank == null ? '—' : e.row.myRank) + '</div>' +
      posBadge(e.row.pos, e.row.myPosRank) +
      '<div class="oven-tp-main">' +
        '<div class="oven-tp-name">' + nameText(e.row.name) + teamTag(e.row.team) + gradeChip(e.row) + '</div>' +
      '</div>' +
      '<div class="oven-tp-chips">' + chips + '</div>' +
    '</div>';
  }

  function madePickHTML(p, s) {
    var m = p.metadata || {};
    var kind = p.is_keeper ? 'kept' : 'picked';
    return '<div class="oven-tp-row filled">' +
      '<div class="oven-tp-rk">' + esc(global.OvenDraft.roundPickLabel(p.pick_no, s.teamsCount)) + '</div>' +
      // A made pick only carries Sleeper metadata — bare position, no pos rank.
      posBadge(global.OvenBoard.normPos(m.position), null) +
      '<div class="oven-tp-main">' +
        '<div class="oven-tp-name">' + nameText(pickName(p)) + teamTag(m.team) + '</div>' +
      '</div>' +
      '<span class="oven-tp-chip ' + kind + '">' + kind + '</span>' +
    '</div>';
  }

  function renderProjections(s, proj) {
    if (!proj.mine.length) {
      return '<div class="oven-tp-empty"><strong>No draft plan yet.</strong>' +
        '<p>Round projections need the league draft order. They’ll fill in once the draft is loaded.</p></div>';
    }

    var html = [];
    for (var r = 1; r <= s.rounds; r++) {
      var lo = (r - 1) * s.teamsCount + 1, hi = r * s.teamsCount;
      var made = 0;
      for (var n = lo; n <= hi; n++) if (proj.filled[n]) made++;

      var mine = proj.mine.filter(function (p) { return p.round === r; });
      var isNow = proj.onTheClock >= lo && proj.onTheClock <= hi;
      var isDone = made === s.teamsCount;

      var body = [];
      if (!mine.length) {
        body.push('<div class="oven-tp-none">No pick this round — traded away.</div>');
      } else {
        mine.forEach(function (p) {
          var done = proj.filled[p.pick_no];
          if (done) { body.push(madePickHTML(done, s)); return; }
          var pr = proj.byPick[p.pick_no];
          body.push('<div class="oven-tp-slot">' +
            '<span class="oven-tp-slot-pick">' + esc(global.OvenDraft.roundPickLabel(p.pick_no, s.teamsCount)) + '</span>' +
            '<span class="oven-tp-slot-line"></span>' +
            '<span class="oven-tp-slot-meta">' + (pr ? pr.gone + ' off before you' : 'projected') + '</span>' +
          '</div>');
          if (!pr || !pr.entries.length) {
            body.push('<div class="oven-tp-none">Nothing left on your board this deep.</div>');
          } else {
            pr.entries.forEach(function (e) { body.push(projEntryHTML(e, s)); });
          }
        });
      }

      html.push('<div class="oven-tp-round' + (isNow ? ' is-now' : (isDone ? ' is-done' : '')) + '">' +
        '<div class="oven-tp-round-head">' +
          '<span class="oven-tp-round-no">Round ' + r + '</span>' +
        '</div>' + body.join('') +
      '</div>');
    }
    return html.join('');
  }

  /* ---------- view 3: team ---------- */

  function slotLabel(pos) { return SLOT_LABEL[pos] || pos; }

  /* Every pick that ended up on my roster, keepers first and then in draft
   * order — which is exactly the fill order the lineup wants.
   *
   * `roster_id` on a pick is the authority when Sleeper sets it; mock drafts
   * and some pre-draft keeper rows leave it null, so the pick plan (which
   * already honors traded picks) is the fallback. */
  function myPicks(s) {
    var planOwner = {};
    (s.plan || []).forEach(function (p) { planOwner[p.pick_no] = p.owner; });

    return (s.picks || []).filter(function (p) {
      var owner = p.roster_id != null ? p.roster_id : planOwner[p.pick_no];
      return owner != null && owner === s.myRosterId;
    }).sort(function (a, b) {
      return ((a.is_keeper ? 0 : 1) - (b.is_keeper ? 0 : 1)) || (a.pick_no - b.pick_no);
    });
  }

  /* Fill the league's lineup from my picks.
   *
   * Greedy, one player at a time in keeper-then-draft order, into the most
   * specific empty slot he's eligible for. Specificity is what stops the first
   * RB drafted from landing in FLEX and leaving RB2 to spill onto the bench —
   * the flex slots are deliberately filled last, by whoever is left over. */
  function buildTeam(s) {
    var starters = [], benchSlots = 0, declared = false;

    (s.rosterPositions || []).forEach(function (raw) {
      var v = String(raw || '').toUpperCase();
      if (!v) return;
      declared = true;
      if (v === 'BN') { benchSlots++; return; }
      if (RESERVE_SLOTS[v]) return;
      starters.push({ pos: v, elig: SLOT_ELIGIBLE[v] || [v], player: null });
    });
    if (!declared) return null;

    // The board row, when the player is on it, so a rostered player carries the
    // same grade badge and personal rank he wears everywhere else. A keeper
    // need not be on my CSV at all, hence the null-tolerant lookup.
    var map = rowsByKey(s.rows), rowByPick = {};
    Object.keys(s.drafted).forEach(function (k) {
      var p = s.drafted[k];
      if (p && p.pick_no != null) rowByPick[p.pick_no] = map[k];
    });

    var bench = [];
    myPicks(s).forEach(function (p) {
      var m = p.metadata || {};
      var player = {
        pick: p,
        row: rowByPick[p.pick_no] || null,
        name: pickName(p),
        pos: global.OvenBoard.normPos(m.position),
        team: m.team || '',
      };

      var best = -1;
      starters.forEach(function (sl, i) {
        if (sl.player || sl.elig.indexOf(player.pos) === -1) return;
        if (best === -1 || sl.elig.length < starters[best].elig.length) best = i;
      });

      if (best !== -1) starters[best].player = player;
      else bench.push(player);
    });

    return { starters: starters, bench: bench, benchSlots: benchSlots };
  }

  function teamSlotHTML(slotPos, player, s) {
    if (!player) {
      return '<div class="oven-tp-row compact oven-tm-row is-empty">' +
        '<div class="oven-tm-slot">' + esc(slotLabel(slotPos)) + '</div>' +
        '<div class="oven-tp-main"><div class="oven-tp-name oven-tm-open">Open</div></div>' +
      '</div>';
    }

    var r = player.row;
    var chip = player.pick.is_keeper
      ? '<span class="oven-tp-chip kept">kept</span>'
      : '<span class="oven-tp-chip">' +
          esc(global.OvenDraft.roundPickLabel(player.pick.pick_no, s.teamsCount)) + '</span>';

    return '<div class="oven-tp-row compact oven-tm-row">' +
      '<div class="oven-tm-slot">' + esc(slotLabel(slotPos)) + '</div>' +
      posBadge(player.pos, r ? r.myPosRank : null) +
      '<div class="oven-tp-main">' +
        '<div class="oven-tp-name">' + nameText(player.name) + teamTag(player.team) +
          (r ? gradeChip(r) : '') + '</div>' +
      '</div>' +
      chip +
    '</div>';
  }

  function renderTeam(s) {
    var t = buildTeam(s);
    if (!t) {
      return '<div class="oven-tp-empty"><strong>No roster settings.</strong>' +
        '<p>The lineup comes from the league’s own starting positions. They’ll fill in ' +
        'once the league loads.</p></div>';
    }

    var html = [];
    var filled = t.starters.filter(function (sl) { return sl.player; }).length;

    html.push('<div class="oven-tp-group">Starters' +
      '<span class="oven-tm-note">' + filled + ' of ' + t.starters.length + '</span></div>');
    if (!t.starters.length) {
      html.push('<div class="oven-tp-none">This league starts no one — every slot is bench.</div>');
    }
    t.starters.forEach(function (sl) { html.push(teamSlotHTML(sl.pos, sl.player, s)); });

    // Overflow past the declared bench still renders: a lineup that quietly
    // dropped a player you drafted would be worse than one that runs long.
    var benchRows = Math.max(t.benchSlots, t.bench.length);
    if (benchRows) {
      html.push('<div class="oven-tp-group">Bench' +
        '<span class="oven-tm-note">' + t.bench.length + ' of ' + t.benchSlots + '</span></div>');
      for (var i = 0; i < benchRows; i++) {
        html.push(teamSlotHTML('BN', t.bench[i] || null, s));
      }
    }

    return html.join('');
  }

  /* ---------- shell ---------- */

  function render() {
    if (!state.mounted) return;
    var s = snapshot();
    var proj = buildProjection(s);

    var map = rowsByKey(s.rows);
    var live = state.keys.filter(function (k) { return map[k] && !s.drafted[k]; }).length;
    state.els.count.textContent = live;
    state.els.count.hidden = !live;
    state.els.tabCount.textContent = live;
    state.els.tabCount.hidden = !live;

    state.els.body.innerHTML = state.view === 'targets' ? renderTargets(s, proj)
      : state.view === 'team' ? renderTeam(s)
      : renderProjections(s, proj);
    state.els.body.scrollTop = 0;

    state.els.foot.innerHTML = state.view === 'targets'
      ? (state.keys.length
          ? '<button class="oven-tp-link" type="button" id="oven-tp-clear">Clear all</button>' +
            '<span>Add with + on the board.</span>'
          : '<span>Add with + on the board.</span>')
      : state.view === 'team'
        ? '<span>Your league’s starting lineup, filled with your keepers first and then ' +
          'your picks in draft order. Each player takes the tightest slot he fits; the ' +
          'flex spots go to whoever is left.</span>'
        : '<span>Assumes the room drafts to consensus and you take your projected ' +
          'player each round. Grades and targets pull a player forward. Every pick also ' +
          'lists the best QB, RB, WR and TE left.</span>';

    var clr = D.getElementById('oven-tp-clear');
    if (clr) clr.addEventListener('click', clear);
  }

  function setView(v) {
    state.view = v;
    state.els.nav.querySelectorAll('[data-view]').forEach(function (a) {
      a.classList.toggle('active', a.getAttribute('data-view') === v);
    });
    render();
  }

  function open() {
    if (state.open) return;
    state.open = true;
    D.body.classList.add('oven-tp-open');
    state.els.panel.setAttribute('aria-hidden', 'false');
    state.els.tab.setAttribute('aria-expanded', 'true');
    render();
  }

  function close() {
    state.open = false;
    D.body.classList.remove('oven-tp-open');
    state.els.panel.setAttribute('aria-hidden', 'true');
    state.els.tab.setAttribute('aria-expanded', 'false');
  }

  function togglePanel() { state.open ? close() : open(); }

  /* Reflect the queue back onto whatever board is on the page, so the panel and
   * the big board never disagree about what's targeted. */
  function markBoard() {
    var rows = D.querySelectorAll('.oven-row[data-key]');
    for (var i = 0; i < rows.length; i++) {
      var on = has(rows[i].getAttribute('data-key'));
      rows[i].classList.toggle('is-target', on);
      var pin = rows[i].querySelector('.oven-pin');
      if (pin) {
        pin.textContent = on ? '✓' : '+';
        pin.setAttribute('aria-label', (on ? 'Remove from' : 'Add to') + ' targets');
        pin.setAttribute('aria-pressed', on ? 'true' : 'false');
      }
    }
  }

  /* Getting players in is the pin button, and only the pin button. Dragging a
   * board row used to drop him here; it now re-ranks him on the board, which is
   * the one gesture that couldn't be expressed any other way. The queue never
   * needed the drag — it has an explicit toggle in the row (`+` / `✓`) and an
   * explicit `×` in the drawer, both of which also work on a phone, where HTML5
   * DnD doesn't fire at all. */

  function wire() {
    state.els.tab.addEventListener('click', togglePanel);
    state.els.close.addEventListener('click', close);

    state.els.nav.addEventListener('click', function (e) {
      var a = e.target.closest('[data-view]');
      if (!a) return;
      e.preventDefault();
      setView(a.getAttribute('data-view'));
    });

    state.els.body.addEventListener('click', function (e) {
      var x = e.target.closest('[data-drop]');
      if (x) { remove(x.getAttribute('data-drop')); return; }
    });

    // Pin buttons live on the host's board rows, so delegate from the D.
    D.addEventListener('click', function (e) {
      var pin = e.target.closest && e.target.closest('.oven-pin');
      if (!pin) return;
      var row = pin.closest('.oven-row[data-key]');
      if (!row) return;
      e.preventDefault();
      e.stopPropagation();
      toggle(row.getAttribute('data-key'));
    });

    D.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && state.open) close();
    });
  }

  function build() {
    var wrap = D.createElement('div');
    wrap.innerHTML =
      '<button class="oven-tp-tab" id="oven-tp-tab" type="button" aria-expanded="false" aria-controls="oven-tp">' +
        '<span class="oven-tp-tab-text">Targets</span>' +
        '<span class="oven-tp-tab-count" hidden>0</span>' +
      '</button>' +
      '<aside class="oven-tp" id="oven-tp" aria-hidden="true" aria-label="Targets and projections">' +
        '<div class="oven-tp-head">' +
          '<nav class="oven-tp-nav">' +
            '<a href="#" data-view="targets" class="active">Targets<span class="oven-tp-count" hidden>0</span></a>' +
            '<a href="#" data-view="projections">Projections</a>' +
            '<a href="#" data-view="team">Team</a>' +
          '</nav>' +
          '<button class="oven-tp-close" type="button" aria-label="Close targets">&times;</button>' +
        '</div>' +
        '<div class="oven-tp-body"></div>' +
        '<div class="oven-tp-foot"></div>' +
      '</aside>';
    while (wrap.firstChild) D.body.appendChild(wrap.firstChild);

    var panel = D.getElementById('oven-tp');
    state.els = {
      tab: D.getElementById('oven-tp-tab'),
      tabCount: D.querySelector('.oven-tp-tab-count'),
      panel: panel,
      nav: panel.querySelector('.oven-tp-nav'),
      count: panel.querySelector('.oven-tp-count'),
      close: panel.querySelector('.oven-tp-close'),
      body: panel.querySelector('.oven-tp-body'),
      foot: panel.querySelector('.oven-tp-foot'),
    };
  }

  function mount(opts) {
    if (state.mounted) return;
    state.getState = (opts && opts.getState) || null;

    // Per-league keys when the host names a league (both Oven pages do). The
    // unscoped fallback keeps the drawer independently mountable.
    var lid = opts && opts.leagueId;
    if (lid && global.OvenLeagues) {
      var tk = global.OvenLeagues.targetKeys(lid);
      state.syncKey = tk.syncKey;
      state.storageKey = tk.storageKey;
    } else {
      state.syncKey = C.TARGETS_SYNC_KEY;
      state.storageKey = C.TARGETS_STORAGE_BASE;
    }

    build();
    wire();
    state.mounted = true;

    var loader = typeof global.loadWithSync === 'function'
      ? global.loadWithSync(C.SYNC_SPORT, state.syncKey, state.storageKey, null)
      : Promise.resolve(null);

    return Promise.resolve(loader).then(function (saved) {
      if (saved && Array.isArray(saved.keys)) state.keys = saved.keys.slice();
      markBoard();
      render();
    }).catch(function () { render(); });
  }

  function refresh() {
    markBoard();
    if (state.open) render();
  }

  global.OvenTargets = {
    mount: mount,
    refresh: refresh,
    // The model, callable without the drawer: takes an explicit host state (or
    // the mounted one) so it can be exercised headless and read by other views.
    project: function (s) { return buildProjection(s ? normalize(s) : snapshot()); },
    // Same deal for the lineup fill — the slot assignment is worth exercising
    // against a fixture without a drawer on the page.
    team: function (s) { return buildTeam(s ? normalize(s) : snapshot()); },
    markBoard: markBoard,
    open: open,
    close: close,
    toggle: togglePanel,
    add: add,
    remove: remove,
    has: has,
    keys: function () { return state.keys.slice(); },
    state: state,
  };
})(window);
