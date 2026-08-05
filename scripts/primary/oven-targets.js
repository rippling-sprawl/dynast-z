/* The Baker's Oven — Targets & Projections (window.OvenTargets).
 *
 * A mountable right-edge drawer, not a page. It injects its own tab, panel and
 * event wiring into <body>, reads everything it needs through one accessor the
 * host view supplies, and persists only a list of player keys — so the same
 * component drops into the index, the big board, or anything later that can
 * describe a board and a draft:
 *
 *   OvenTargets.mount({ getState: function () { return {
 *     rows, drafted, picks, plan, teamsCount, rounds, myRosterId
 *   }; } });
 *   OvenTargets.refresh();   // after any poll
 *
 * Two sub-views:
 *   targets     — the queue, grouped by position, in my rank order
 *   projections — rounds 1..N, keepers and made picks filled in, future rounds
 *                 simulated forward
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

  var state = {
    mounted: false,
    open: false,
    view: 'targets',
    keys: [],          // board keys, insertion order
    getState: null,
    els: {},
  };

  function esc(s) { return global.OvenBoard.esc(s); }

  /* ---------- the queue ---------- */

  function has(key) { return state.keys.indexOf(key) !== -1; }

  function persist() {
    var payload = { keys: state.keys, updatedAt: Date.now() };
    if (typeof global.saveWithSync === 'function') {
      global.saveWithSync(C.SYNC_SPORT, C.TARGETS_SYNC_KEY, C.TARGETS_STORAGE_KEY, payload);
    } else {
      try { global.localStorage.setItem(C.TARGETS_STORAGE_KEY, JSON.stringify(payload)); } catch (e) { /* private mode */ }
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

  // The board owns the grade badge (heart for love/like, `fade` carried by the
  // row receding rather than a badge) — same markup here so the two surfaces
  // can't drift.
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
      posBadge(r.pos, r.fpPosRank) +
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
        '<p>Drag a player off the big board and drop him here — or tap the <span class="oven-tp-kbd">+</span> ' +
        'at the end of his row. Targets are grouped by position and ordered by your rank.</p>' +
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
      posBadge(e.row.pos, e.row.fpPosRank) +
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

    state.els.body.innerHTML = state.view === 'targets'
      ? renderTargets(s, proj)
      : renderProjections(s, proj);
    state.els.body.scrollTop = 0;

    state.els.foot.innerHTML = state.view === 'targets'
      ? (state.keys.length
          ? '<button class="oven-tp-link" type="button" id="oven-tp-clear">Clear all</button>' +
            '<span>Drag from the board to add.</span>'
          : '<span>Drag from the board to add.</span>')
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

  /* ---------- drag & drop ----------
   * HTML5 DnD is desktop-only (iOS Safari doesn't fire it at all), so the pin
   * button is the real affordance on a phone and dragging is the fast path on a
   * laptop. Both go through add(). */
  var DND_TYPE = 'application/x-oven-player';

  function wireDrag() {
    D.addEventListener('dragstart', function (e) {
      var row = e.target.closest && e.target.closest('.oven-row[data-key]');
      if (!row) return;
      var key = row.getAttribute('data-key');
      try {
        e.dataTransfer.setData(DND_TYPE, key);
        e.dataTransfer.setData('text/plain', key);
      } catch (err) { /* older Edge rejects custom types */ }
      e.dataTransfer.effectAllowed = 'copy';
      D.body.classList.add('oven-tp-dragging');
      // Nothing to drop onto if the drawer is shut.
      if (!state.open) open();
      if (state.view !== 'targets') setView('targets');
    });

    D.addEventListener('dragend', function () {
      D.body.classList.remove('oven-tp-dragging');
      state.els.panel.classList.remove('is-over');
    });

    ['dragenter', 'dragover'].forEach(function (ev) {
      state.els.panel.addEventListener(ev, function (e) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'copy';
        state.els.panel.classList.add('is-over');
      });
    });
    state.els.panel.addEventListener('dragleave', function (e) {
      if (!state.els.panel.contains(e.relatedTarget)) state.els.panel.classList.remove('is-over');
    });
    state.els.panel.addEventListener('drop', function (e) {
      e.preventDefault();
      state.els.panel.classList.remove('is-over');
      D.body.classList.remove('oven-tp-dragging');
      var key = '';
      try { key = e.dataTransfer.getData(DND_TYPE) || e.dataTransfer.getData('text/plain'); } catch (err) { key = ''; }
      if (!key) return;
      if (state.view !== 'targets') setView('targets');
      add(key);
    });

    // The tab itself is a drop target — dropping on a closed drawer should work.
    ['dragenter', 'dragover'].forEach(function (ev) {
      state.els.tab.addEventListener(ev, function (e) { e.preventDefault(); open(); });
    });
  }

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

    wireDrag();
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
    build();
    wire();
    state.mounted = true;

    var loader = typeof global.loadWithSync === 'function'
      ? global.loadWithSync(C.SYNC_SPORT, C.TARGETS_SYNC_KEY, C.TARGETS_STORAGE_KEY, null)
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
