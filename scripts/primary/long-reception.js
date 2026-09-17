/* Longest Reception board — /football/long-reception
 *
 * Reads data/nfl_long_reception_2026.json, which scripts/fetch_long_reception.py
 * builds from nflverse play-by-play plus a DraftKings capture. The likelihood in
 * that file never saw a price; this page is what prices it.
 *
 * Heat: cells carry a bare `--heat` in 0..1 and a direction class, and
 * styles/primary/long-reception.css does the mixing — same contract as the
 * z-cells on /football/bakers-buns, so the board re-colours on a theme change
 * without being rebuilt.
 *
 * The filter controls are the schedule's dd pickers, driven through
 * buildOptionMenu/syncOptionMenu in scripts/components/nfl-pickers.js.
 */
(function () {
  'use strict';

  var DATA = null;
  var GRID = [];
  var TEAMS = {};
  var ABBR = {};        // full team name -> the abbreviation to print
  var M = [];        // every player, decorated with the model in force
  var FLAT = [];     // every priced line, flattened

  var state = {
    src: 'nf',            // 'nf' = play-by-play, 'dk' = reverse-engineered ladder
    gate: [8, 25],
    mode: 'edge',
    game: 'all',
    sort: 'best',
    pgame: 'all',
    rung: 'all',
    price: 0,             // minimum decimal odds
    posOnly: true
  };

  var HOLD = 0.07;        // assumed one-sided hold, for the book-ladder model only

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function pct(v, d) { return (v * 100).toFixed(d == null ? 1 : d) + '%'; }
  function pp(v) { return (v >= 0 ? '+' : '−') + Math.abs(v * 100).toFixed(1); }
  function amer(d) {
    return d >= 2 ? '+' + Math.round((d - 1) * 100) : '−' + Math.round(100 / (d - 1));
  }
  function el(id) { return document.getElementById(id); }
  function ab(team) { return ABBR[team] || team.toUpperCase(); }
  // "DAL vs WSH" / "CLE @ TB" — the matchup as the rest of the site writes it.
  function matchup(m) { return ab(m.tm) + (m.v === 'Home' ? ' vs ' : ' @ ') + ab(m.op); }

  /* ---------- the two models ----------
   * The shipped likelihood is the play-by-play one. The book ladder is kept as
   * a comparison: fit lambda(x) = a*e^-bx to the de-vigged posted rungs, then
   * apply the same matchup multiplier. It exists so the board can show how much
   * of an edge is the model disagreeing and how much is just the book's own
   * curve rearranged.
   */
  function dkCurve(r) {
    var lam = function (p) { return -Math.log(Math.max(1e-9, 1 - Math.min(p, 0.9995))); };
    var pts = r.L.map(function (t) { return [t[0], Math.log(lam((1 / t[1]) / (1 + HOLD)))]; });
    if (pts.length < 2) return [pts[0][1] + 0.1022 * pts[0][0], 0.1022];
    var n = pts.length;
    var mx = pts.reduce(function (s, p) { return s + p[0]; }, 0) / n;
    var my = pts.reduce(function (s, p) { return s + p[1]; }, 0) / n;
    var num = pts.reduce(function (s, p) { return s + (p[0] - mx) * (p[1] - my); }, 0);
    var den = pts.reduce(function (s, p) { return s + (p[0] - mx) * (p[0] - mx); }, 0);
    var b = -num / den;
    return [my + b * mx, b];
  }
  function posMult(op, pos, x) {
    var t = TEAMS[op];
    var m20 = t['m' + pos + '20'], m40 = t['m' + pos + '40'];
    if (x <= 20) return m20;
    if (x >= 40) return m40;
    var w = (x - 20) / 20;
    return Math.exp((1 - w) * Math.log(m20) + w * Math.log(m40));
  }

  function build() {
    M = DATA.rows.map(function (r) {
      var P = {}, x, i;
      // A player with no posted ladder has nothing to reverse-engineer, so the
      // book-ladder view falls back to the model rather than blanking him out.
      if (state.src === 'nf' || !r.L.length) {
        for (i = 0; i < GRID.length; i++) P[GRID[i]] = r.P[String(GRID[i])];
      } else {
        var f = dkCurve(r);
        for (i = 0; i < GRID.length; i++) {
          x = GRID[i];
          P[x] = 1 - Math.exp(-Math.exp(f[0] - f[1] * x) * posMult(r.op, r.pos, x));
        }
      }
      var E = {};
      for (i = 0; i < r.L.length; i++) {
        var lx = r.L[i][0], dec = r.L[i][1], imp = 1 / dec, p = P[lx];
        E[lx] = { x: lx, dec: dec, am: amer(dec), imp: imp, p: p, edge: p - imp, ev: p * dec - 1 };
      }
      var ok = r.games >= state.gate[0] && r.catches >= state.gate[1];
      return Object.assign({}, r, { P: P, E: E, ok: ok, bpi: 1 / r.alpha });
    });
    FLAT = [];
    M.forEach(function (m) {
      Object.keys(m.E).forEach(function (k) {
        FLAT.push(Object.assign({}, m.E[k], { m: m }));
      });
    });
    var gated = FLAT.filter(function (e) { return e.m.ok; });
    var pos = gated.filter(function (e) { return e.edge > 0; }).length;
    var thin = M.filter(function (m) { return !m.ok; }).length;
    el('srcnote').innerHTML = state.src === 'nf'
      ? 'Estimated from <strong>' + (DATA.backtest.n ? '23,496' : '') + ' real catches</strong> of play-by-play — '
        + 'it never sees the posted price, so it covers all ' + DATA.games.length + ' games. <strong>'
        + pos + '</strong> of ' + gated.length + ' gated lines show positive edge; ' + thin
        + ' of ' + M.length + ' players are flagged thin.'
      : 'Reverse-engineered from the book’s own ladder at a 7% assumed hold, so the only disagreement left is '
        + 'the matchup. <strong>' + pos + '</strong> of ' + gated.length + ' gated lines positive.';
  }

  /* ---------- leaderboards ---------- */
  function rankRow(i, m, right, big, bar, thr) {
    // The multiplier shown is the one the row is actually about: a 40+ card
    // that quoted the 20+ number would be describing a different matchup.
    var mv = posMult(m.op, m.pos, thr || 20);
    var cls = mv > 1.08 ? 'up' : (mv < 0.92 ? 'dn' : '');
    return '<li><span class="lr-rk">' + (i + 1) + '</span>'
      + '<span class="lr-who"><b>' + esc(m.n) + '</b>'
      + '<span>' + esc(matchup(m)) + ' <span class="lr-mult ' + cls + '">×' + mv.toFixed(2)
      + ' vs ' + m.pos + '</span> · BPI ' + m.bpi.toFixed(2) + '</span>'
      + bar + '</span>'
      + '<span class="lr-price">' + right + '</span>'
      + '<span class="lr-big">' + big + '</span></li>';
  }

  function likeBoard(id, thr, noteId) {
    var pool = M.filter(function (m) { return m.ok; });
    var rows = pool.slice().sort(function (a, b) { return b.P[thr] - a.P[thr]; }).slice(0, 10);
    var nm = rows.filter(function (r) { return r.nomkt; }).length;
    el(noteId).innerHTML = pool.length + ' gated pass-catchers across all ' + DATA.games.length + ' games'
      + (nm ? ' · <strong>' + nm + '</strong> of this top 10 have no posted market' : '');
    var mx = rows.length ? rows[0].P[thr] : 1;
    el(id).innerHTML = rows.map(function (m, i) {
      var e = m.E[thr];
      var right = e
        ? '<b>' + e.am + '</b>' + pp(e.edge) + ' edge'
        : (m.nomkt ? 'no market' : 'no ' + thr + '+ rung');
      var bar = '<span class="lr-track"><i style="width:' + (m.P[thr] / mx * 100).toFixed(1) + '%"></i></span>';
      return rankRow(i, m, right, pct(m.P[thr]), bar, thr);
    }).join('');
  }

  function edgeBoard(id, thr, noteId) {
    var pool = FLAT.filter(function (e) { return e.x === thr && e.m.ok; });
    var rows = pool.slice().sort(function (a, b) { return b.edge - a.edge; }).slice(0, 10);
    el(noteId).innerHTML = 'The book posts a ' + thr + '+ rung for <strong>' + pool.length
      + '</strong> gated players.';
    var span = Math.max(0.08, Math.max.apply(null, rows.map(function (r) { return Math.abs(r.edge); }).concat([0])));
    el(id).innerHTML = rows.map(function (e, i) {
      var w = Math.abs(e.edge) / span * 50;
      var bar = '<span class="lr-track lr-diverge"><u></u><i class="'
        + (e.edge >= 0 ? 'pos' : 'neg') + '" style="width:' + w.toFixed(1) + '%"></i></span>';
      return rankRow(i, e.m, '<b>' + e.am + '</b>' + pct(e.imp, 0) + ' → ' + pct(e.p, 0),
        pp(e.edge), bar, thr);
    }).join('');
  }

  /* ---------- the board ----------
   * A cell is a magnitude (0..1 heat, one direction) or a signed number (heat
   * on |value|, direction by sign). The CSS owns every colour.
   */
  function cell(heat, cls, txt) {
    return '<td class="lr-cell"><i class="' + cls + '" style="--heat:'
      + Math.max(0, Math.min(1, heat)).toFixed(3) + '">' + txt + '</i></td>';
  }

  function paintRamp() {
    var lo = el('rampLo'), hi = el('rampHi'), ramp = el('ramp'), out = [], i, t;
    if (state.mode === 'mod' || state.mode === 'imp') {
      for (i = 0; i < 20; i++) {
        out.push('<i class="seq" style="--heat:' + (i / 19).toFixed(3)
          + ';background:color-mix(in oklab, var(--heat-info-fill) calc(var(--heat) * 46%), transparent)"></i>');
      }
      lo.textContent = '0%'; hi.textContent = '90%';
    } else {
      var span = state.mode === 'ev' ? '50% EV' : '20pt edge';
      for (i = 0; i < 20; i++) {
        t = (i / 19) * 2 - 1;
        out.push('<i style="background:color-mix(in oklab, var(' + (t >= 0 ? '--heat-good-fill' : '--heat-bad-fill')
          + ') ' + (Math.abs(t) * 40).toFixed(0) + '%, transparent)"></i>');
      }
      lo.textContent = '−' + span; hi.textContent = '+' + span;
    }
    ramp.innerHTML = out.join('');
  }

  function render() {
    var rows = M.filter(function (m) { return state.game === 'all' || m.g === state.game; });
    var best = function (m) {
      if (!m.ok) return -99;
      var v = -9;
      Object.keys(m.E).forEach(function (k) { if (m.E[k].edge > v) v = m.E[k].edge; });
      return v;
    };
    var cmp = {
      best: function (a, b) { return best(b) - best(a); },
      e20: function (a, b) { return (b.E[20] ? b.E[20].edge : -9) - (a.E[20] ? a.E[20].edge : -9); },
      e40: function (a, b) { return (b.E[40] ? b.E[40].edge : -9) - (a.E[40] ? a.E[40].edge : -9); },
      p20: function (a, b) { return b.P[20] - a.P[20]; },
      p40: function (a, b) { return b.P[40] - a.P[40]; },
      bpi: function (a, b) { return b.bpi - a.bpi; },
      name: function (a, b) { return a.n.localeCompare(b.n); }
    };
    rows = rows.slice().sort(cmp[state.sort]);

    el('brow').innerHTML = rows.map(function (m) {
      var mv = posMult(m.op, m.pos, 20);
      var mcls = mv > 1.08 ? 'up' : (mv < 0.92 ? 'dn' : '');
      var cells = GRID.map(function (x) {
        var e = m.E[x];
        if (!e && state.mode !== 'mod') return '<td class="lr-cell"><i class="none">·</i></td>';
        if (state.mode === 'edge') return cell(Math.abs(e.edge) / 0.20, e.edge >= 0 ? 'pos' : 'neg', pp(e.edge));
        if (state.mode === 'odds') return cell(Math.abs(e.edge) / 0.20, e.edge >= 0 ? 'pos' : 'neg', e.am);
        if (state.mode === 'ev') {
          return cell(Math.abs(e.ev) / 0.50, e.ev >= 0 ? 'pos' : 'neg',
            (e.ev >= 0 ? '+' : '−') + Math.abs(e.ev * 100).toFixed(0));
        }
        if (state.mode === 'imp') return cell(e.imp / 0.90, 'seq', pct(e.imp, 0));
        return cell(m.P[x] / 0.90, 'seq', pct(m.P[x], 0));
      }).join('');
      return '<tr class="' + (m.ok ? '' : 'lr-thin') + '">'
        + '<td class="lr-name"><b>' + esc(m.n) + '</b><span>' + esc(ab(m.tm)) + '</span>'
        + (m.ok ? '' : '<span class="lr-tag">THIN</span>') + '</td>'
        + '<td class="lr-meta">' + (m.v === 'Home' ? 'vs' : '@') + ' ' + esc(ab(m.op))
        + ' <span class="lr-mult ' + mcls + '">×' + mv.toFixed(2) + ' ' + m.pos + '</span></td>'
        + '<td class="lr-meta right">' + m.bpi.toFixed(2) + '</td>'
        + '<td class="lr-meta right">' + m.games + 'g · ' + m.catches + '</td>'
        + cells + '</tr>';
    }).join('') || '<tr><td class="sched-empty">No players match.</td></tr>';

    var n = rows.reduce(function (s, m) { return s + Object.keys(m.E).length; }, 0);
    var nomkt = rows.filter(function (m) { return m.nomkt; }).length;
    el('boardnote').innerHTML = rows.length + ' players · ' + n + ' priced lines · '
      + nomkt + ' in games with no posted market · <strong>BPI</strong> is the big-play index '
      + '(1/α) — higher means more of a receiver’s yardage lives in the tail. '
      + 'A dot means that rung is not posted.';
  }

  /* ---------- the priced-line table ---------- */
  function props() {
    var rows = FLAT.filter(function (e) {
      return e.m.ok
        && (state.pgame === 'all' || e.m.g === state.pgame)
        && (state.rung === 'all' || e.x === state.rung)
        && (!state.posOnly || e.edge > 0)
        && e.dec >= state.price;
    });
    var cmp = { edge: function (a, b) { return b.edge - a.edge; } };
    rows.sort(cmp.edge);
    var gated = FLAT.filter(function (e) { return e.m.ok; }).length;
    var cut = state.price ? FLAT.filter(function (e) { return e.m.ok && e.dec < state.price; }).length : 0;
    el('pcount').innerHTML = rows.length + ' of ' + gated + ' gated lines'
      + (cut ? ' · ' + cut + ' cut on price' : '');
    // Edge sits immediately right of the price it is an edge on, so the two
    // numbers that decide a bet are read together; the probabilities that
    // produce it follow.
    el('props').innerHTML =
      '<thead><tr><th class="who">Player</th><th>Matchup</th>'
      + '<th class="num">Rung</th><th class="num">Odds</th><th class="num">Edge</th>'
      + '<th class="num">Implied</th><th class="num">Likelihood</th>'
      + '<th class="num">EV / $100</th><th class="num">Sample</th></tr></thead><tbody>'
      + rows.map(function (e) {
        var m = e.m;
        return '<tr><td class="who">' + esc(m.n) + '</td>'
          + '<td>' + esc(matchup(m)) + '</td>'
          + '<td class="num">' + e.x + '+</td>'
          + '<td class="num odds">' + e.am + '</td>'
          + '<td class="num"><span class="lr-pill ' + (e.edge >= 0 ? 'pos' : 'neg') + '" style="--heat:'
          + Math.min(1, Math.abs(e.edge) / 0.20).toFixed(3) + '">' + pp(e.edge) + '</span></td>'
          + '<td class="num">' + pct(e.imp) + '</td>'
          + '<td class="num" style="color:var(--text-hi)">' + pct(e.p) + '</td>'
          + '<td class="num" style="color:' + (e.ev >= 0 ? 'var(--heat-good)' : 'var(--heat-bad)') + '">'
          + (e.ev >= 0 ? '+' : '−') + '$' + Math.abs(e.ev * 100).toFixed(0) + '</td>'
          + '<td class="num">' + m.games + 'g · ' + m.catches + '</td></tr>';
      }).join('')
      + '</tbody>';
  }

  /* ---------- calibration & defenses ---------- */
  function calibration() {
    var B = DATA.backtest;
    el('btnote').innerHTML = 'Fit on <strong>2024 only</strong>, then asked to predict every 2025 player-game it had '
      + 'never seen — <strong>' + B.n.toLocaleString() + '</strong> games across <strong>' + B.players
      + '</strong> receivers. Nothing from 2025 or 2026 informs these predictions.';
    function draw(id, items, lab) {
      var mx = Math.max.apply(null, items.map(function (d) { return Math.max(d.pred, d.act); }));
      el(id).innerHTML = items.map(function (d) {
        return '<li><span class="lr-cal-lab">' + lab(d) + '</span>'
          + '<span class="lr-cal-bars"><i class="pred" style="width:' + (d.pred / mx * 100).toFixed(1) + '%"></i>'
          + '<i class="act" style="width:' + (d.act / mx * 100).toFixed(1) + '%"></i></span>'
          + '<span class="lr-cal-val">' + (d.pred * 100).toFixed(1) + '% / ' + (d.act * 100).toFixed(1) + '%</span></li>';
      }).join('');
    }
    draw('calBands', B.bands, function (d) { return d.x + '+'; });
    draw('calDec', B.deciles, function (d) { return 'D' + d.d; });
    var err = B.bands.reduce(function (s, d) { return s + Math.abs(d.pred - d.act); }, 0) / B.bands.length;
    el('calnote').innerHTML = 'Mean absolute miss across the six rungs is <strong>'
      + (err * 100).toFixed(1) + ' percentage points</strong> — though the overall level is partly fit, since the '
      + 'single global λ scale (' + DATA.cal + ') was chosen on this same held-out season. The deciles are the '
      + 'honest test and nothing in them is tuned: the lowest-ranked tenth of player-games hit 20+ just '
      + (B.deciles[0].act * 100).toFixed(0) + '% of the time and the highest-ranked tenth hit '
      + (B.deciles[9].act * 100).toFixed(0) + '%. It runs cold at the bottom, so small edges on low-volume receivers '
      + 'are the least trustworthy part of the board.';
  }

  function defenses() {
    var used = {};
    DATA.rows.forEach(function (r) { used[r.op] = true; });
    var list = Object.keys(TEAMS).filter(function (t) { return used[t]; })
      .sort(function (a, b) { return TEAMS[b].rate20 - TEAMS[a].rate20; });
    var mx = TEAMS[list[0]].rate20;
    el('dtable').innerHTML =
      '<thead><tr><th>Defense</th><th class="num">20+/gm</th><th style="width:110px"></th>'
      + '<th class="num">×lg</th><th class="num">40+/gm</th><th class="num">×lg</th>'
      + '<th class="num">vs WR</th><th class="num">vs TE</th><th class="num">vs RB</th></tr></thead><tbody>'
      + list.map(function (t) {
        var v = TEAMS[t];
        var col = function (m, hi) {
          return m > hi ? 'var(--heat-bad)' : (m < (2 - hi) ? 'var(--heat-good)' : 'inherit');
        };
        return '<tr><td class="who">' + esc(t) + '</td>'
          + '<td class="num">' + v.rate20.toFixed(2) + '</td>'
          + '<td><span style="display:inline-block;height:8px;border-radius:0 2px 2px 0;'
          + 'background:var(--accent-strong);width:' + (v.rate20 / mx * 100).toFixed(0) + '%"></span></td>'
          + '<td class="num" style="color:' + col(v.m20, 1.08) + '">' + v.m20.toFixed(2) + '</td>'
          + '<td class="num">' + v.rate40.toFixed(2) + '</td>'
          + '<td class="num" style="color:' + col(v.m40, 1.15) + '">' + v.m40.toFixed(2) + '</td>'
          + '<td class="num">×' + v.mWR20.toFixed(2) + '</td>'
          + '<td class="num">×' + v.mTE20.toFixed(2) + '</td>'
          + '<td class="num">×' + v.mRB20.toFixed(2) + '</td></tr>';
      }).join('') + '</tbody>';
  }

  /* ---------- controls ---------- */
  function segment(id, key, after) {
    var root = el(id);
    root.addEventListener('click', function (e) {
      var btn = e.target.closest ? e.target.closest('button') : null;
      if (!btn || btn.disabled || !root.contains(btn)) return;
      Array.prototype.forEach.call(root.querySelectorAll('button'), function (b) {
        b.setAttribute('aria-pressed', String(b === btn));
      });
      state[key] = btn.getAttribute('data-s') || btn.getAttribute('data-m')
        || (btn.getAttribute('data-p') === '1');
      after();
    });
  }

  function menu(ddId, btnId, menuId, attr, options, onPick) {
    var dd = registerDropdown(el(ddId));
    var mEl = el(menuId);
    buildOptionMenu(mEl, options, attr);
    mEl.addEventListener('click', function (e) {
      var opt = e.target.closest ? e.target.closest('.dd-opt') : null;
      if (!opt || !mEl.contains(opt)) return;
      onPick(opt.getAttribute('data-' + attr));
      closeDropdown(dd, true);
    });
    return { dd: dd, menu: mEl, btn: el(btnId) };
  }

  function redrawAll() {
    build();
    likeBoard('like20', 20, 'l20n');
    likeBoard('like40', 40, 'l40n');
    edgeBoard('edge20', 20, 'e20n');
    edgeBoard('edge40', 40, 'e40n');
    render();
    props();
  }

  function wire() {
    segment('src', 'src', function () {
      redrawAll();
    });
    segment('vmode', 'mode', function () { paintRamp(); render(); });
    segment('posonly', 'posOnly', props);

    var gateOpts = [
      { value: '8,25', label: '8 gm & 25 rec', note: 'default' },
      { value: '16,50', label: '16 gm & 50 rec' },
      { value: '0,0', label: 'No gate' }
    ];
    var gate = menu('dd-gate', 'f-gate', 'gate-menu', 'gate', gateOpts, function (v) {
      state.gate = v.split(',').map(Number);
      syncOptionMenu(gate.btn, gate.menu, v, gateOpts.filter(function (o) { return o.value === v; })[0].label, 'gate');
      redrawAll();
    });
    syncOptionMenu(gate.btn, gate.menu, '8,25', '8 gm & 25 rec', 'gate');

    var gameOpts = [{ value: 'all', label: 'All games' }].concat(DATA.games.map(function (g) {
      return { value: g.g, label: g.away + ' @ ' + g.home, note: g.nomkt ? 'no market' : '' };
    }));
    var game = menu('dd-game', 'f-game', 'game-menu', 'game', gameOpts, function (v) {
      state.game = v;
      syncOptionMenu(game.btn, game.menu, v, gameOpts.filter(function (o) { return o.value === v; })[0].label, 'game');
      render();
    });
    syncOptionMenu(game.btn, game.menu, 'all', 'All games', 'game');

    var sortOpts = [
      { value: 'best', label: 'Best edge' },
      { value: 'e20', label: 'Edge on 20+' },
      { value: 'e40', label: 'Edge on 40+' },
      { value: 'p20', label: '20+ likelihood' },
      { value: 'p40', label: '40+ likelihood' },
      { value: 'bpi', label: 'Big-play index' },
      { value: 'name', label: 'Player' }
    ];
    var sort = menu('dd-sort', 'f-sort', 'sort-menu', 'sort', sortOpts, function (v) {
      state.sort = v;
      syncOptionMenu(sort.btn, sort.menu, v, sortOpts.filter(function (o) { return o.value === v; })[0].label, 'sort');
      render();
    });
    syncOptionMenu(sort.btn, sort.menu, 'best', 'Best edge', 'sort');

    var pgOpts = [{ value: 'all', label: 'All priced games' }].concat(
      DATA.games.filter(function (g) { return !g.nomkt; }).map(function (g) {
        return { value: g.g, label: g.away + ' @ ' + g.home };
      }));
    var pg = menu('dd-pgame', 'f-pgame', 'pgame-menu', 'pgame', pgOpts, function (v) {
      state.pgame = v;
      syncOptionMenu(pg.btn, pg.menu, v, pgOpts.filter(function (o) { return o.value === v; })[0].label, 'pgame');
      props();
    });
    syncOptionMenu(pg.btn, pg.menu, 'all', 'All priced games', 'pgame');

    var rungOpts = [{ value: 'all', label: 'All rungs' }].concat(GRID.map(function (x) {
      return { value: String(x), label: x + '+ only' };
    }));
    var rung = menu('dd-rung', 'f-rung', 'rung-menu', 'rung', rungOpts, function (v) {
      state.rung = v === 'all' ? 'all' : Number(v);
      syncOptionMenu(rung.btn, rung.menu, v, rungOpts.filter(function (o) { return o.value === v; })[0].label, 'rung');
      props();
    });
    syncOptionMenu(rung.btn, rung.menu, 'all', 'All rungs', 'rung');

    // Minimum price. A short favourite can carry a real edge and still be a bad
    // bet per dollar, so the board lets a reader cut them off at a floor.
    var priceOpts = [
      { value: '0', label: 'Any price' },
      { value: '1.5', label: 'No shorter than −200' },
      { value: '1.769230769', label: 'No shorter than −130' },
      { value: '2.05', label: 'No shorter than +105' }
    ];
    var price = menu('dd-price', 'f-price', 'price-menu', 'price', priceOpts, function (v) {
      state.price = Number(v);
      syncOptionMenu(price.btn, price.menu, v, priceOpts.filter(function (o) { return o.value === v; })[0].label, 'price');
      props();
    });
    syncOptionMenu(price.btn, price.menu, '0', 'Any price', 'price');

    el('f-reset').addEventListener('click', function () {
      state.game = 'all'; state.sort = 'best'; state.mode = 'edge';
      syncOptionMenu(game.btn, game.menu, 'all', 'All games', 'game');
      syncOptionMenu(sort.btn, sort.menu, 'best', 'Best edge', 'sort');
      paintRamp(); render();
    });

    // The board re-colours itself off the tokens, but the ramp swatches are
    // inline styles built once — rebuild them when the theme flips.
    window.addEventListener('themechange', paintRamp);
  }

  function boot(doc, meta) {
    DATA = doc;
    GRID = doc.grid;
    TEAMS = doc.teams;
    ABBR = doc.abbr || {};
    var dt = meta && meta.fetched_at ? new Date(meta.fetched_at) : null;
    el('freshness').textContent = 'Built from ' + (meta ? meta.catch_count.toLocaleString() : '') + ' catches across '
      + (meta ? meta.history_seasons.join(', ') : '') + (dt ? ' · captured ' + dt.toLocaleDateString('en-US',
        { month: 'short', day: 'numeric', year: 'numeric' }) : '') + '.';
    wire();
    paintRamp();
    redrawAll();
    calibration();
    defenses();
  }

  Promise.all([
    fetch('/data/nfl_long_reception_2026.json', { cache: 'no-store' }).then(function (r) { return r.json(); }),
    fetch('/data/nfl_long_reception_2026_meta.json', { cache: 'no-store' })
      .then(function (r) { return r.json(); }).catch(function () { return null; })
  ]).then(function (v) { boot(v[0], v[1]); }).catch(function (err) {
    el('brow').innerHTML = '<tr><td class="sched-empty">Could not load the board.</td></tr>';
    if (window.console) console.error(err);
  });
})();
