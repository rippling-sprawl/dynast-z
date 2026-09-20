/* Longest Reception board — /football/long-reception
 *
 * Reads data/nfl_long_reception_2026.json, which scripts/fetch_long_reception.py
 * builds from nflverse play-by-play plus a DraftKings capture. The likelihood in
 * that file never saw a price; this page is what prices it.
 *
 * The file is a list of weeks, each one frozen at the moment it was priced —
 * its own matchups, its own ladders, and the defense table those prices were
 * read against. So the page holds one week at a time in `W` and everything
 * below reads from there, not from the document. Switching weeks touches no
 * network: the whole season is already in hand, the same way /football/schedule
 * holds a season and changes weeks locally.
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
  var META = null;
  var WEEKS = [];       // every week the file carries, ascending
  var W = null;         // the one on screen
  var GRID = [];
  var TEAMS = {};       // that week's defenses, as they stood when it was priced
  var ABBR = {};        // full team name -> the abbreviation to print
  var M = [];        // every player, decorated with the model in force
  var FLAT = [];     // every priced line, flattened

  var state = {
    week: null,
    // The sample gate still applies to everything drawn -- it is read from the
    // board file at boot rather than offered as a control, because ungated the
    // biggest number on the page belongs to a receiver with no career catches.
    gate: [8, 25],
    pos: 'all',           // 'all' | 'WR' | 'TE' | 'RB'
    pgame: 'all',
    rung: 'all',
    price: 0,             // minimum decimal odds
    posOnly: true,
    q: '',                // folded player search, '' when the box is shut
    qText: ''             // the same thing as typed, for the count line
  };

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
  // Names on this board carry apostrophes and accents (Ja'Marr, Amon-Ra), so a
  // search folds case and accents off both sides before it compares.
  function fold(s) {
    s = String(s == null ? '' : s).toLowerCase();
    return s.normalize ? s.normalize('NFD').replace(/[\u0300-\u036f]/g, '') : s;
  }
  function el(id) { return document.getElementById(id); }
  function ab(team) { return ABBR[team] || team.toUpperCase(); }
  // "DAL vs WSH" / "CLE @ TB" — the matchup as the rest of the site writes it.
  function matchup(m) { return ab(m.tm) + (m.v === 'Home' ? ' vs ' : ' @ ') + ab(m.op); }

  function posMult(op, pos, x) {
    var t = TEAMS[op];
    var m20 = t['m' + pos + '20'], m40 = t['m' + pos + '40'];
    if (x <= 20) return m20;
    if (x >= 40) return m40;
    var w = (x - 20) / 20;
    return Math.exp((1 - w) * Math.log(m20) + w * Math.log(m40));
  }

  /* ---------- the week ----------
   * Which week the page opens on, by the same rule /football/schedule uses: the
   * file ships each week as [start, end) and the first that has not ended yet is
   * "now", so a Tuesday reads as the week about to start rather than as nothing.
   *
   * Where it differs is the fallthrough. The schedule has all eighteen weeks and
   * only runs out at the end of a season; the board has only the weeks somebody
   * captured, so it runs out every time the clock passes the last slate priced.
   * That lands on the most recent week, which is the last board there is.
   */
  function currentWeek() {
    var now = new Date();
    for (var i = 0; i < WEEKS.length; i++) {
      if (WEEKS[i].end && now < new Date(WEEKS[i].end)) return WEEKS[i].week;
    }
    return WEEKS[WEEKS.length - 1].week;
  }

  // "Sep 17–21", or "Sep 30–Oct 4" across a month. The window runs to midnight
  // after the last game, so the day the reader thinks of as the end is the day
  // before it. Read in UTC because that is the zone the window was written in.
  function weekRange(w) {
    if (!w.start || !w.end) return '';
    var o = { timeZone: 'UTC', month: 'short', day: 'numeric' };
    var a = new Date(w.start).toLocaleDateString('en-US', o);
    var b = new Date(new Date(w.end).getTime() - 864e5).toLocaleDateString('en-US', o);
    return a.split(' ')[0] === b.split(' ')[0] ? a + '–' + b.split(' ')[1] : a + '–' + b;
  }

  function build() {
    M = W.rows.map(function (r) {
      var P = {}, i;
      for (i = 0; i < GRID.length; i++) P[GRID[i]] = r.P[String(GRID[i])];
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
    var catches = META && META.catch_count ? META.catch_count.toLocaleString() : '';
    var vol = M.filter(function (m) { return m.mrate != null; }).length;
    el('srcnote').innerHTML = 'Estimated from <strong>' + catches + ' real catches</strong> of play-by-play — '
      + 'it never sees the longest-reception price it is judging, so it covers all ' + W.games.length
      + ' games of week ' + W.week + '. <strong>'
      + pos + '</strong> of ' + gated.length + ' gated lines show positive edge; ' + thin
      + ' of ' + M.length + ' players are flagged thin'
      + (vol ? '; ' + vol + ' take their catch volume from a posted receptions line' : '') + '.';
  }

  // Gate and position decide what is on the page at all, so every surface asks
  // the same question rather than each re-deriving it.
  function shown(m) {
    return m.ok && (state.pos === 'all' || m.pos === state.pos);
  }

  /* ---------- leaderboards ---------- */
  function rankRow(i, m, right, big, bar, thr) {
    // The multiplier shown is the one the row is actually about: a 40+ card
    // that quoted the 20+ number would be describing a different matchup.
    var mv = posMult(m.op, m.pos, thr || 20);
    var cls = mv > 1.08 ? 'up' : (mv < 0.92 ? 'dn' : '');
    // The two halves of the likelihood, named: how many catches he is getting
    // and how far they go. A rec figure the receptions market set is marked,
    // because it is the one number here the model did not derive itself.
    //
    // This line is one line by design — nowrap and an ellipsis — so ADOT rides
    // on BPI's title rather than taking width of its own. That is where a
    // reader would look for it anyway: BPI is what the model concluded about a
    // receiver's depth, ADOT is the evidence its prior was set from.
    //
    // BPI before volume because the narrow card of a side-by-side pair does
    // still clip, and what clips should be the number that is repeated in the
    // table below rather than the one that is only here.
    var vol = m.rate.toFixed(1) + ' rec' + (m.mrate != null ? '<sup title="from the posted '
      + 'receptions line">m</sup>' : '');
    var bpi = '<span' + (m.adot != null ? ' title="' + m.adot.toFixed(1)
      + ' yd average depth of target"' : '') + '>BPI ' + m.bpi.toFixed(2) + '</span>';
    return '<li><span class="lr-rk">' + (i + 1) + '</span>'
      + '<span class="lr-who"><b>' + esc(m.n) + '</b>'
      + '<span>' + esc(matchup(m)) + ' <span class="lr-mult ' + cls + '">×' + mv.toFixed(2)
      + ' vs ' + m.pos + '</span> · ' + bpi + ' · ' + vol + '</span>'
      + bar + '</span>'
      + '<span class="lr-price">' + right + '</span>'
      + '<span class="lr-big">' + big + '</span></li>';
  }

  function likeBoard(id, thr, noteId) {
    var pool = M.filter(shown);
    var rows = pool.slice().sort(function (a, b) { return b.P[thr] - a.P[thr]; }).slice(0, 10);
    var nm = rows.filter(function (r) { return r.nomkt; }).length;
    el(noteId).innerHTML = pool.length + ' gated pass-catchers across all ' + W.games.length
      + ' games of week ' + W.week
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
    var pool = FLAT.filter(function (e) { return e.x === thr && shown(e.m); });
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

  /* ---------- the priced-line table ---------- */

  // The header is built once and never again: it holds a live search box, and
  // rebuilding it on every keystroke would blur the field mid-word. props()
  // therefore writes the body only.
  var headUp = false;
  var ICON_Q = '<svg class="lr-find-q" viewBox="0 0 16 16" aria-hidden="true">'
    + '<circle cx="6.9" cy="6.9" r="4.4"/><path d="M10.2 10.2 14 14"/></svg>';
  var ICON_X = '<svg class="lr-find-x" viewBox="0 0 16 16" aria-hidden="true">'
    + '<path d="M4.2 4.2 11.8 11.8M11.8 4.2 4.2 11.8"/></svg>';

  function propsHead() {
    if (headUp) return;
    headUp = true;
    // Edge sits immediately right of the price it is an edge on, so the two
    // numbers that decide a bet are read together.
    el('props').innerHTML =
      '<thead><tr><th class="who"><span class="lr-find" id="pfind" data-open="0">'
      + '<span class="lr-find-lab">Player</span>'
      + '<input type="text" class="lr-find-in" id="pfind-in" tabindex="-1"'
      + ' placeholder="Search players" aria-label="Search players"'
      + ' autocomplete="off" autocapitalize="off" spellcheck="false">'
      + '<button type="button" class="lr-find-btn" id="pfind-btn"'
      + ' aria-controls="pfind-in" aria-expanded="false" aria-label="Search players">'
      + ICON_Q + ICON_X + '</button>'
      + '</span></th><th>Matchup</th>'
      + '<th class="num" title="Catches expected this game — the volume half of the '
      + 'likelihood. A dot marks one the posted receptions line set.">Rec</th>'
      + '<th class="num">Rung</th><th class="num">Odds</th><th class="num">Edge</th>'
      + '</tr></thead><tbody id="pbody"></tbody>';
    wireFind();
  }

  function wireFind() {
    var wrap = el('pfind'), box = el('pfind-in'), btn = el('pfind-btn');
    function open(on) {
      wrap.setAttribute('data-open', on ? '1' : '0');
      btn.setAttribute('aria-expanded', String(on));
      btn.setAttribute('aria-label', on ? 'Clear player search' : 'Search players');
      // Shut, the box is off the tab order as well as out of sight.
      box.tabIndex = on ? 0 : -1;
      if (on) { box.focus(); box.select(); return; }
      box.value = '';
      if (state.q) { state.q = ''; state.qText = ''; props(); }
    }
    btn.addEventListener('click', function () {
      open(wrap.getAttribute('data-open') !== '1');
    });
    box.addEventListener('input', function () {
      state.qText = box.value.trim();
      state.q = fold(state.qText);
      props();
    });
    box.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape' && e.key !== 'Esc') return;
      e.stopPropagation();
      open(false);
      btn.focus();
    });
  }

  function props() {
    propsHead();
    var rows = FLAT.filter(function (e) {
      return shown(e.m)
        && (state.pgame === 'all' || e.m.g === state.pgame)
        && (state.rung === 'all' || e.x === state.rung)
        && (!state.posOnly || e.edge > 0)
        && (!state.q || fold(e.m.n).indexOf(state.q) >= 0)
        && e.dec >= state.price;
    });
    var cmp = { edge: function (a, b) { return b.edge - a.edge; } };
    rows.sort(cmp.edge);
    var pool = FLAT.filter(function (e) { return shown(e.m); });
    var cut = state.price ? pool.filter(function (e) { return e.dec < state.price; }).length : 0;
    el('pcount').innerHTML = rows.length + ' of ' + pool.length + ' gated lines'
      + (state.pos === 'all' ? '' : ' at ' + state.pos)
      + (state.q ? ' · matching “' + esc(state.qText) + '”' : '')
      + (cut ? ' · ' + cut + ' cut on price' : '');
    el('pbody').innerHTML = rows.length ? rows.map(function (e) {
        var m = e.m;
        return '<tr><td class="who">' + esc(m.n) + '</td>'
          + '<td>' + (m.v === 'Home' ? 'vs ' : '@ ') + esc(ab(m.op)) + '</td>'
          + '<td class="num lr-vol' + (m.mrate != null ? ' mkt' : '') + '">'
          + m.rate.toFixed(1) + '</td>'
          + '<td class="num">' + e.x + '+</td>'
          + '<td class="num odds">' + e.am + '</td>'
          + '<td class="num"><span class="lr-pill ' + (e.edge >= 0 ? 'pos' : 'neg') + '" style="--heat:'
          + Math.min(1, Math.abs(e.edge) / 0.20).toFixed(3) + '">' + pp(e.edge) + '</span></td>'
          + '</tr>';
      }).join('')
      : '<tr><td class="sched-empty" colspan="6">No line matches these filters.</td></tr>';
    scatter(rows);
  }

  /* ---------- likelihood against the posted price ----------
   * The table above is the same numbers; this is their geometry. A line's
   * price is a probability too — 1/decimal — so the two live on one scale and
   * can share both axes. Put the book's number across and the model's up and
   * the fair price is the 45° line y = x: on it the two agree, above it the
   * model says a bet is likelier than you are being charged for.
   *
   * The edge is then literally a distance. `edge = p − imp` is the vertical
   * gap, and the perpendicular to y = x is that same gap over √2 — the
   * shortest way off the fair line, which is what the drop from each point
   * draws. That only reads as a perpendicular if a percentage point is the
   * same length across as it is up, so the plot is square over one shared
   * domain and never stretched to the card. The SVG carries its own width and
   * the sheet centres it.
   *
   * Everything here is drawn from the rows props() just filtered, so the
   * picture is always the table: change the game, the rung, the price floor or
   * the positive-edge toggle and the chart changes with it.
   *
   * It draws the top CAP of them and not the whole filtered set. Five hundred
   * lines was a smudge along the diagonal — the stems that carry the whole
   * argument were shorter than the gaps between the points, and the ones worth
   * looking at were buried under the ones that are not. The rows arrive already
   * sorted by edge, so the picture is the table's first screen: the shortlist,
   * with the table underneath it as the record.
   */
  var CAP = 25;
  var lastRows = [];

  function gc(token, fallback) {
    return (window.Theme && window.Theme.color) ? window.Theme.color(token, fallback) : fallback;
  }

  function svgText(x, y, s, o) {
    o = o || {};
    return '<text x="' + x + '" y="' + y + '"'
      + ' fill="' + (o.fill || gc('--text-3', '#8b949e')) + '"'
      + ' font-size="' + (o.size || 10) + '"'
      + (o.weight ? ' font-weight="' + o.weight + '"' : '')
      + (o.opacity ? ' opacity="' + o.opacity + '"' : '')
      // A halo, for the labels that have to sit on top of the cloud. It is
      // painted under the glyph rather than over it, so the text keeps its own
      // weight and the card colour does the clearing.
      + (o.halo ? ' stroke="' + o.halo + '" stroke-width="3" stroke-linejoin="round"'
        + ' paint-order="stroke fill"' : '')
      + ' text-anchor="' + (o.anchor || 'start') + '"'
      + (o.transform ? ' transform="' + o.transform + '"' : '')
      + '>' + s + '</text>';
  }

  /* The domain both axes share. Whole percents throughout: the grid has to
   * land exactly on its bounds, and accumulating 0.05 twenty times does not.
   * It is derived from what is on screen rather than fixed at 0–100, because a
   * 40+-only view lives in the bottom corner and would otherwise be a smudge —
   * but it stays square, so the diagonal is still 45° whatever it spans. */
  function domain(rows) {
    var lo = 100, hi = 0;
    rows.forEach(function (e) {
      lo = Math.min(lo, e.imp * 100, e.p * 100);
      hi = Math.max(hi, e.imp * 100, e.p * 100);
    });
    if (hi < lo) { lo = 0; hi = 100; }
    var pad = Math.max(2, (hi - lo) * 0.08);
    lo = Math.floor((lo - pad) / 5) * 5;
    hi = Math.ceil((hi + pad) / 5) * 5;
    lo = Math.max(0, lo);
    hi = Math.min(100, hi);
    // A cluster tighter than ten points would magnify rounding into structure.
    if (hi - lo < 10) { hi = Math.min(100, lo + 10); lo = Math.max(0, hi - 10); }
    return { lo: lo, hi: hi, span: hi - lo };
  }

  function scatter(all) {
    lastRows = all;
    var host = el('scatter');
    if (!host) return;
    var note = el('scnote');

    if (!all.length) {
      host.innerHTML = '<p class="lr-plot-empty">No line matches these filters.</p>';
      if (note) note.textContent = '';
      return;
    }
    // Already sorted by edge where it was filtered, so the top of the table is
    // the top of the chart without a second sort deciding a different order.
    var rows = all.slice(0, CAP);

    var INK = gc('--text-3', '#8b949e');
    var FAINT = gc('--text-4', '#6e7681');
    var AXIS = gc('--border', '#30363d');
    var GUIDE = gc('--text-5', '#484f58');
    var GOOD = gc('--heat-good', '#3fb950');
    var BAD = gc('--heat-bad', '#f0883e');
    var PAPER = gc('--surface', '#161b22');

    var cw = host.clientWidth || 560;
    var compact = cw < 520;
    var mL = compact ? 30 : 42;
    var mR = compact ? 12 : 16;
    var mT = compact ? 12 : 16;
    var mB = compact ? 30 : 38;
    // Square, capped: past ~430px a bigger square separates nothing further and
    // only pushes the cards below it off the screen.
    var side = Math.max(200, Math.min(cw - mL - mR, compact ? 320 : 480));
    var W = mL + side + mR, H = mT + side + mB;
    var x0 = mL, x1 = mL + side, yTop = mT, yBot = mT + side;

    var d = domain(rows);
    var sx = function (v) { return x0 + (v * 100 - d.lo) / d.span * side; };
    var sy = function (v) { return yTop + (1 - (v * 100 - d.lo) / d.span) * side; };

    var svg = [];

    /* --- grid, in whole percents --- */
    var step = d.span > 55 ? 20 : (d.span > 25 ? 10 : 5);
    var g = [], t, px, py;
    for (t = Math.ceil(d.lo / step) * step; t <= d.hi; t += step) {
      px = sx(t / 100); py = sy(t / 100);
      g.push('<line x1="' + px.toFixed(1) + '" y1="' + yTop + '" x2="' + px.toFixed(1)
        + '" y2="' + yBot + '" stroke="' + AXIS + '" stroke-width="1"/>');
      g.push('<line x1="' + x0 + '" y1="' + py.toFixed(1) + '" x2="' + x1
        + '" y2="' + py.toFixed(1) + '" stroke="' + AXIS + '" stroke-width="1"/>');
      g.push(svgText(px.toFixed(1), yBot + (compact ? 12 : 14), t + '%',
        { anchor: 'middle', size: compact ? 9 : 10, fill: FAINT }));
      g.push(svgText(x0 - 6, (py + 3).toFixed(1), t + '%',
        { anchor: 'end', size: compact ? 9 : 10, fill: FAINT }));
    }
    // The bounds close the frame; the loop only reaches them when they happen
    // to be multiples of the step.
    g.push('<rect x="' + x0 + '" y="' + yTop + '" width="' + side + '" height="' + side
      + '" fill="none" stroke="' + AXIS + '" stroke-width="1"/>');
    svg.push(g.join(''));

    /* --- the fair line, corner to corner because the square guarantees it --- */
    svg.push('<line x1="' + sx(d.lo / 100).toFixed(1) + '" y1="' + sy(d.lo / 100).toFixed(1)
      + '" x2="' + sx(d.hi / 100).toFixed(1) + '" y2="' + sy(d.hi / 100).toFixed(1)
      + '" stroke="' + GUIDE + '" stroke-width="1.5" stroke-dasharray="6 4"/>');
    // Rides along the line rather than parked in a corner: it labels the line,
    // and a corner would have it labelling the region instead. Near the far end
    // because the near one is where the cheap 40+ rungs pile up.
    var lt = d.lo + d.span * 0.86;
    var lx = sx(lt / 100) + 9, ly = sy(lt / 100) + 9;
    svg.push(svgText(lx.toFixed(1), ly.toFixed(1), 'fair price', {
      anchor: 'middle', size: 9, fill: GUIDE, halo: PAPER,
      transform: 'rotate(-45 ' + lx.toFixed(1) + ' ' + ly.toFixed(1) + ')'
    }));

    // What each side of the line means, inside the plot so it costs no margin.
    svg.push(svgText(x0 + 9, yTop + 14,
      compact ? 'value' : 'value — model above the price',
      { size: 9, fill: GOOD, opacity: '0.75' }));
    svg.push(svgText(x1 - 9, yBot - 9,
      compact ? 'no value' : 'no value — price above the model',
      { size: 9, fill: BAD, opacity: '0.75', anchor: 'end' }));

    /* --- one mark per priced line, each with its drop to the fair line ---
     * Stems first as a layer of their own, so a dense corner does not bury a
     * point under the next point's stem. */
    var r = rows.length > 220 ? 2.4 : (rows.length > 90 ? 3 : 3.8);
    var stems = [], dots = [];
    rows.forEach(function (e) {
      var cx = sx(e.imp), cy = sy(e.p);
      var f = (e.imp + e.p) / 2;                 // the foot of the perpendicular
      var fx = sx(f), fy = sy(f);
      var col = e.edge >= 0 ? GOOD : BAD;
      stems.push('<line x1="' + cx.toFixed(1) + '" y1="' + cy.toFixed(1)
        + '" x2="' + fx.toFixed(1) + '" y2="' + fy.toFixed(1)
        + '" stroke="' + col + '" stroke-width="1.4" opacity="0.5"/>');
      dots.push('<circle cx="' + cx.toFixed(1) + '" cy="' + cy.toFixed(1) + '" r="' + r
        + '" fill="' + col + '" fill-opacity="0.85" stroke="' + PAPER + '" stroke-width="0.8">'
        + '<title>' + esc(e.m.n) + ' · ' + e.x + '+ · ' + e.am + '\n'
        + 'price ' + pct(e.imp, 1) + ' · model ' + pct(e.p, 1) + ' · edge ' + pp(e.edge) + '</title>'
        + '</circle>');
    });
    svg.push(stems.join('') + dots.join(''));

    /* --- the three longest drops, named --- */
    if (!compact) {
      rows.slice().sort(function (a, b) { return Math.abs(b.edge) - Math.abs(a.edge); })
        .slice(0, 3).forEach(function (e) {
          var cx = sx(e.imp), cy = sy(e.p);
          var right = cx < x0 + side * 0.72;
          svg.push(svgText((cx + (right ? 7 : -7)).toFixed(1), (cy + 3).toFixed(1),
            esc(e.m.n) + ' ' + e.x + '+', {
              size: 9.5, fill: gc('--text-hi', '#f0f6fc'), halo: PAPER,
              anchor: right ? 'start' : 'end'
            }));
        });
    }

    /* --- axis titles --- */
    svg.push(svgText((x0 + x1) / 2, H - (compact ? 4 : 6),
      compact ? 'price, implied' : 'the book — implied probability of the posted price',
      { anchor: 'middle', size: compact ? 9.5 : 10, fill: INK }));
    var my = ((yTop + yBot) / 2).toFixed(1);
    svg.push(svgText(11, my, compact ? 'model' : 'the model — likelihood',
      { anchor: 'middle', size: compact ? 9.5 : 10, fill: INK,
        transform: 'rotate(-90 11 ' + my + ')' }));

    var up = rows.filter(function (e) { return e.edge >= 0; }).length;
    var capped = all.length > rows.length;
    host.innerHTML = '<svg width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '"'
      + ' role="img" aria-label="' + (capped ? 'The ' + rows.length + ' biggest edges of the '
        + all.length + ' priced lines the table is showing' : rows.length + ' priced lines')
      + ', plotted with the price’s implied probability across and the model’s likelihood up. '
      + up + ' sit above the fair line, where the model is likelier than the price. '
      + 'The table above lists every one of them.">' + svg.join('') + '</svg>';

    if (note) {
      note.innerHTML = (capped
        ? 'The <strong>' + rows.length + '</strong> biggest edges of the ' + all.length
          + ' lines the table is showing — its first ' + rows.length + ' rows.'
        : 'All <strong>' + rows.length + '</strong> line' + (rows.length === 1 ? '' : 's')
          + ' the table is showing, one point each.')
        + ' Distance from the dashed line is the edge: every point drops to it at a right angle, and '
        + 'both axes carry the same scale so that drop is the shortest way back to a fair price.'
        + (rows.length > 1
          ? ' These run ' + pp(rows[0].edge) + ' to ' + pp(rows[rows.length - 1].edge) + ' points'
            + (up < rows.length ? ', ' + up + ' of them above the line' : '') + '.'
          : '');
    }
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
    W.rows.forEach(function (r) { used[r.op] = true; });
    // Frozen with the week, not recomputed: these are the multipliers that
    // produced the likelihoods above, which for a past week is not what the
    // same defenses look like today.
    el('dnote').innerHTML = 'Explosive receptions allowed per game, weighted '
      + '<strong>20% 2024 · 50% 2025 · 30% 2026</strong> as they stood when week '
      + W.week + ' was priced. The board applies the position-specific multiplier — '
      + 'a defense can be soft to tight ends and stingy outside.';
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

  /* The two game menus list one week's fixtures, so they are rebuilt on every
   * week change rather than filled once. Both filters reset to all games with
   * them: a fixture picked in week 2 is not on week 3's slate, and leaving the
   * control reading "Lions @ Bills" over an empty table would be worse than
   * dropping the pick. */
  var pgM = null, weekM = null;
  var pgOpts = [];

  function optLabel(opts, v) {
    var hit = opts.filter(function (o) { return String(o.value) === String(v); })[0];
    return hit ? hit.label : String(v);
  }

  function rebuildGameMenus() {
    pgOpts = [{ value: 'all', label: 'All priced games' }].concat(
      W.games.filter(function (g) { return !g.nomkt; }).map(function (g) {
        return { value: g.g, label: g.away + ' @ ' + g.home };
      }));
    buildOptionMenu(pgM.menu, pgOpts, 'pgame');
    syncOptionMenu(pgM.btn, pgM.menu, state.pgame, optLabel(pgOpts, state.pgame), 'pgame');
  }

  function setWeek(n) {
    W = WEEKS.filter(function (w) { return w.week === n; })[0] || WEEKS[WEEKS.length - 1];
    state.week = W.week;
    TEAMS = W.teams || {};
    state.pgame = 'all';
    rebuildGameMenus();
    syncOptionMenu(weekM.btn, weekM.menu, W.week, 'Week ' + W.week, 'week');
  }

  // Only the week is worth carrying in the URL: it is the one choice that says
  // which numbers are on screen rather than how they are arranged.
  function readWeekParam() {
    var v = new URLSearchParams(location.search).get('week');
    var n = Number(v);
    return v && WEEKS.some(function (w) { return w.week === n; }) ? n : null;
  }

  function writeWeekParam() {
    var q = new URLSearchParams(location.search);
    q.set('week', String(state.week));
    history.replaceState(null, '', location.pathname + '?' + q.toString());
  }

  function redrawAll() {
    build();
    likeBoard('like20', 20, 'l20n');
    likeBoard('like40', 40, 'l40n');
    edgeBoard('edge20', 20, 'e20n');
    edgeBoard('edge40', 40, 'e40n');
    props();
  }

  function wire() {
    var weekOpts = WEEKS.map(function (w) {
      return { value: w.week, label: 'Week ' + w.week, note: weekRange(w) };
    });
    weekM = menu('dd-week', 'f-week', 'week-menu', 'week', weekOpts, function (v) {
      setWeek(Number(v));
      writeWeekParam();
      redrawAll();
      defenses();
      freshness();
    });

    segment('posonly', 'posOnly', props);

    var posOpts = [
      { value: 'all', label: 'All positions' },
      { value: 'WR', label: 'WR' },
      { value: 'TE', label: 'TE' },
      { value: 'RB', label: 'RB' }
    ];
    var posM = menu('dd-pos', 'f-pos', 'pos-menu', 'pos', posOpts, function (v) {
      state.pos = v;
      syncOptionMenu(posM.btn, posM.menu, v, optLabel(posOpts, v), 'pos');
      redrawAll();
    });
    syncOptionMenu(posM.btn, posM.menu, 'all', 'All positions', 'pos');

    pgM = menu('dd-pgame', 'f-pgame', 'pgame-menu', 'pgame', [], function (v) {
      state.pgame = v;
      syncOptionMenu(pgM.btn, pgM.menu, v, optLabel(pgOpts, v), 'pgame');
      props();
    });

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
      { value: '1.5', label: 'At Least −200' },
      { value: '1.769230769', label: 'At Least −130' },
      { value: '2.05', label: 'At Least +105' },
      { value: '3', label: 'At Least +200' }
    ];
    var price = menu('dd-price', 'f-price', 'price-menu', 'price', priceOpts, function (v) {
      state.price = Number(v);
      syncOptionMenu(price.btn, price.menu, v, priceOpts.filter(function (o) { return o.value === v; })[0].label, 'price');
      props();
    });
    syncOptionMenu(price.btn, price.menu, '0', 'Any price', 'price');

  }

  // The capture date is the selected week's own, not the file's: a past week was
  // priced off prices taken then, and the file's mtime says nothing about it.
  function freshness() {
    var dt = W.captured ? new Date(W.captured)
      : (META && META.fetched_at ? new Date(META.fetched_at) : null);
    el('freshness').textContent = 'Built from '
      + (META ? META.catch_count.toLocaleString() : '') + ' catches across '
      + (META ? META.history_seasons.join(', ') : '')
      + (dt ? ' · week ' + W.week + ' prices captured ' + dt.toLocaleDateString('en-US',
        { month: 'short', day: 'numeric', year: 'numeric' }) : '') + '.';
  }

  function boot(doc, meta) {
    DATA = doc;
    META = meta;
    GRID = doc.grid;
    ABBR = doc.abbr || {};
    if (Array.isArray(doc.gate) && doc.gate.length === 2) state.gate = doc.gate;
    WEEKS = (doc.weeks || []).slice().sort(function (a, b) { return a.week - b.week; });
    if (!WEEKS.length) throw new Error('no weeks in the board file');
    // An explicit ?week= wins on first load — a link to week 2 has to keep
    // meaning week 2 once week 3 is the current one.
    wire();
    setWeek(readWeekParam() || currentWeek());
    freshness();
    redrawAll();
    calibration();
    defenses();
  }

  /* The scatter is measured in pixels and its colours are baked into the SVG as
   * attribute strings, so both a resize and a theme change mean redrawing it —
   * the rest of the page is CSS and re-colours itself. */
  var szT = null;
  window.addEventListener('resize', function () {
    clearTimeout(szT);
    szT = setTimeout(function () { scatter(lastRows); }, 150);
  });
  window.addEventListener('themechange', function () { scatter(lastRows); });

  Promise.all([
    fetch('/data/nfl_long_reception_2026.json', { cache: 'no-store' }).then(function (r) { return r.json(); }),
    fetch('/data/nfl_long_reception_2026_meta.json', { cache: 'no-store' })
      .then(function (r) { return r.json(); }).catch(function () { return null; })
  ]).then(function (v) { boot(v[0], v[1]); }).catch(function (err) {
    el('props').innerHTML = '<tbody><tr><td class="sched-empty">Could not load the board.</td></tr></tbody>';
    if (window.console) console.error(err);
  });
})();
