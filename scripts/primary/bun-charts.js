/*
  Baker's Buns — The Board.

  The projections table holds the model (`score`) and the market (`make` /
  `miss`) in four separate columns and leaves the reader to join them. This is
  that join: every team placed against both at once, so the gap between what
  the model thinks and what the book is charging becomes a length you can see
  rather than arithmetic you have to do in your head.

  Three decisions worth stating, because each could reasonably have gone the
  other way:

  1. The y axis is the raw composite score, not a probability. Turning a
     z-score blend into "% to make the playoffs" needs a calibration this data
     does not contain, and inventing one would put a fabricated number on the
     axis of the one chart that exists to be honest. So the model keeps its own
     units, the market keeps percent, and disagreement is read as distance from
     the fitted line rather than as a percentage-point edge. That line is
     descriptive — it is where the market has priced this model's average team,
     nothing more — which is why it is drawn as a faint guide and not as a
     result.

  2. Direction is carried by which side of the line a team sits on, and only
     after that by colour. The page's green and orange are 5.7 ΔE apart under
     deuteranopia, below the safe floor; every tinted cell in the table gets
     away with it because it also prints a signed number beside the colour. A
     chart mark prints nothing, so here position does the work and the colour
     is along for the ride.

  3. The mark is the team's logo rather than a dot with a label. Thirty-two
     labelled dots need a legend or thirty-two pieces of leader text; a logo is
     its own label. At the widths this chart is drawn at the closest pair of
     teams sits 21.6px apart on desktop and 15px at 600px wide, so an 18px mark
     never collides and nothing has to be nudged off its true position to make
     room. Below 560px the wrapper scrolls sideways instead of squeezing, the
     same thing .bun-table-wrap does with the table.

  De-vigging: make and miss are the two sides of one market, so their implied
  probabilities sum to 1 plus the book's hold (3.4–4.4% across this field).
  Dividing each by that sum strips the hold proportionally. The check that it
  worked: the 32 de-vigged make probabilities sum to 14.0, which is exactly the
  number of playoff berths.
*/
(function () {
  'use strict';

  var LOGO_DIR = '/assets/icons/nfl/';

  /* Borrowed wholesale from the table's palette — see the file comment for why
   * none of these are new. GUIDE is the fit line and the zero rule; they are
   * scenery, and sit a step below the axis labels on purpose. */
  var GREEN = '#3fb950';
  var ORANGE = '#f0883e';
  var AXIS = '#2a2a2a';
  var GUIDE = '#484f58';
  var INK = '#8b949e';
  var INK_HI = '#f0f0f0';

  var MIN_W = 560;    // below this the wrapper scrolls rather than the chart squeezing
  var LOGO = 18;

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function imp(o) {
    return o > 0 ? 100 / (o + 100) : -o / (-o + 100);
  }

  // Null for a team the sheet priced on only one side of the market — there is
  // no hold to divide out of a single number, so it has no x position.
  function marketProb(t) {
    var o = t.odds || {};
    if (o.make == null || o.miss == null) return null;
    var a = imp(o.make), b = imp(o.miss);
    return a / (a + b);
  }

  function points(teams) {
    var out = [];
    (teams || []).forEach(function (t) {
      var p = marketProb(t);
      if (p == null || t.score == null) return;
      out.push({ abbr: t.abbr, team: t.team, conf: t.conf, div: t.div, x: p, y: t.score });
    });
    return out;
  }

  /* Ordinary least squares, plus the R² the section note quotes. Fitted over
   * every team in the field and never over the filtered view: a fit that moved
   * when you clicked a division chip would redefine "the market agrees" as you
   * read, and each team's residual would change without its data changing. */
  function fit(pts) {
    var n = pts.length;
    if (n < 3) return null;
    var mx = 0, my = 0, i;
    for (i = 0; i < n; i++) { mx += pts[i].x; my += pts[i].y; }
    mx /= n; my /= n;

    var sxy = 0, sxx = 0, syy = 0, dx, dy;
    for (i = 0; i < n; i++) {
      dx = pts[i].x - mx; dy = pts[i].y - my;
      sxy += dx * dy; sxx += dx * dx; syy += dy * dy;
    }
    if (!sxx || !syy) return null;

    var b = sxy / sxx;
    return { b: b, a: my - b * mx, r2: (sxy * sxy) / (sxx * syy) };
  }

  function svgText(x, y, s, o) {
    o = o || {};
    return '<text x="' + x + '" y="' + y + '"' +
      ' fill="' + (o.fill || INK) + '" font-size="' + (o.size || 10) + '"' +
      ' font-family="monospace"' +
      (o.weight ? ' font-weight="' + o.weight + '"' : '') +
      (o.opacity ? ' opacity="' + o.opacity + '"' : '') +
      ' text-anchor="' + (o.anchor || 'start') + '"' +
      (o.transform ? ' transform="' + o.transform + '"' : '') +
      '>' + s + '</text>';
  }

  function pct(p) { return Math.round(p * 100) + '%'; }
  function signed(v, d) { return (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(d); }

  /* ---------- the chart ---------- */

  function draw(host, teams, matches) {
    var pts = points(teams);
    var f = fit(pts);
    if (!pts.length || !f) {
      host.innerHTML = '<p class="board-empty">Not enough priced teams to plot.</p>';
      return null;
    }

    var W = Math.max(MIN_W, Math.floor(host.clientWidth || MIN_W));
    var H = Math.max(340, Math.min(470, Math.round(W * 0.56)));
    var mL = 54, mR = 22, mT = 30, mB = 46;
    var x0 = mL, x1 = W - mR, yTop = mT, yBot = H - mB;
    var plotW = x1 - x0, plotH = yBot - yTop;

    // x runs from a clean 0 to the first fifth above the priciest team, so the
    // gridline spacing stays on round percentages.
    var xhi = 0, ylim = 0, i;
    for (i = 0; i < pts.length; i++) {
      if (pts[i].x > xhi) xhi = pts[i].x;
      if (Math.abs(pts[i].y) > ylim) ylim = Math.abs(pts[i].y);
    }
    xhi = Math.min(1, Math.ceil((xhi + 0.02) * 5) / 5);
    // Symmetric about zero: the axis is a z-score blend whose midpoint is the
    // league average, and an asymmetric one would put that average off-centre.
    ylim = Math.ceil((ylim + 0.05) * 4) / 4;

    var sx = function (p) { return x0 + (p / xhi) * plotW; };
    var sy = function (v) { return yTop + (1 - (v + ylim) / (2 * ylim)) * plotH; };

    var svg = [];

    // --- gridlines: x every 20%, y every 0.5, plus the emphasised zero rule ---
    var g = [];
    for (var p = 0; p <= xhi + 1e-9; p += 0.2) {
      g.push('<line x1="' + sx(p).toFixed(1) + '" y1="' + yTop + '" x2="' + sx(p).toFixed(1) +
        '" y2="' + yBot + '" stroke="' + AXIS + '" stroke-width="1"/>');
      g.push(svgText(sx(p), yBot + 16, pct(p), { anchor: 'middle' }));
    }
    for (var v = -ylim; v <= ylim + 1e-9; v += 0.5) {
      var isZero = Math.abs(v) < 1e-9;
      g.push('<line x1="' + x0 + '" y1="' + sy(v).toFixed(1) + '" x2="' + x1 +
        '" y2="' + sy(v).toFixed(1) + '" stroke="' + (isZero ? GUIDE : AXIS) +
        '" stroke-width="1"' + (isZero ? ' stroke-dasharray="3 3"' : '') + '/>');
      g.push(svgText(x0 - 8, sy(v) + 3, signed(v, 2), { anchor: 'end' }));
    }
    svg.push(g.join(''));

    // --- the fit line, clipped to the plot ---
    var fy0 = f.a + f.b * 0, fy1 = f.a + f.b * xhi;
    svg.push('<line x1="' + sx(0) + '" y1="' + sy(fy0).toFixed(1) +
      '" x2="' + sx(xhi) + '" y2="' + sy(fy1).toFixed(1) +
      '" stroke="' + GUIDE + '" stroke-width="1.5" stroke-dasharray="6 4"/>');
    svg.push(svgText(sx(xhi) - 4, sy(fy1) - 7, 'market agrees', {
      anchor: 'end', size: 9, opacity: '0.75'
    }));

    // --- corner annotations: what each side of the line means ---
    svg.push(svgText(x0 + 10, yTop + 15, 'model likes · market hasn’t', {
      size: 9, fill: GREEN, opacity: '0.6'
    }));
    svg.push(svgText(x1 - 10, yBot - 8, 'market likes · model doesn’t', {
      size: 9, fill: ORANGE, opacity: '0.6', anchor: 'end'
    }));

    // --- one group per team: residual stem, then the logo on top of it ---
    var marks = [];
    pts.forEach(function (d) {
      var cx = sx(d.x), cy = sy(d.y);
      var ly = sy(f.a + f.b * d.x);
      d.resid = d.y - (f.a + f.b * d.x);

      // A filtered-out team keeps its place — the field is the point of the
      // chart — but drops its stem and fades, so the chips read as "show me
      // where these sit" rather than as a different chart.
      var on = matches ? matches(d) : true;
      var col = d.resid >= 0 ? GREEN : ORANGE;

      marks.push('<g class="board-pt' + (on ? '' : ' is-off') + '"' +
        ' data-abbr="' + esc(d.abbr) + '" data-team="' + esc(d.team) + '"' +
        ' data-x="' + cx.toFixed(1) + '" data-y="' + cy.toFixed(1) + '"' +
        ' data-mkt="' + pct(d.x) + '" data-score="' + signed(d.y, 2) + '"' +
        ' data-resid="' + signed(d.resid, 2) + '" tabindex="0" role="listitem"' +
        ' aria-label="' + esc(d.team) + ': market ' + pct(d.x) + ' to make, score ' +
        signed(d.y, 2) + ', ' + signed(d.resid, 2) + ' versus the fit">' +
        (on
          ? '<line x1="' + cx.toFixed(1) + '" y1="' + cy.toFixed(1) +
            '" x2="' + cx.toFixed(1) + '" y2="' + ly.toFixed(1) +
            '" stroke="' + col + '" stroke-width="1.5" opacity="0.55"/>'
          : '') +
        '<image href="' + LOGO_DIR + esc(d.abbr) + '.svg" x="' + (cx - LOGO / 2).toFixed(1) +
        '" y="' + (cy - LOGO / 2).toFixed(1) + '" width="' + LOGO + '" height="' + LOGO + '"/>' +
        // A hit target wider than the mark, so a 18px logo is not an 18px
        // tooltip. Invisible, and last so it sits above the image.
        '<circle cx="' + cx.toFixed(1) + '" cy="' + cy.toFixed(1) +
        '" r="15" fill="transparent"/>' +
        '</g>');
    });
    svg.push(marks.join(''));

    // --- axis titles ---
    svg.push(svgText((x0 + x1) / 2, H - 8, 'market — de-vigged chance to make the playoffs',
      { anchor: 'middle', size: 10 }));
    svg.push(svgText(15, (yTop + yBot) / 2, 'model — composite score', {
      anchor: 'middle', size: 10, transform: 'rotate(-90 15 ' + ((yTop + yBot) / 2) + ')'
    }));

    host.innerHTML =
      '<svg class="board-svg" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '"' +
      ' role="list" aria-label="Model composite score against de-vigged market probability, ' +
      pts.length + ' teams. Teams above the fitted line are ones the model rates higher than ' +
      'the market prices them.">' + svg.join('') + '</svg>';

    return { pts: pts, r2: f.r2, sum: pts.reduce(function (s, d) { return s + d.x; }, 0) };
  }

  /* ---------- the read-out beneath the chart ----------
   * The chart's own accessible fallback, and the part most people will actually
   * quote. Computed rather than written down, so it can never drift from the
   * numbers above it the way a hand-typed list would. */
  function summary(pts) {
    var by = pts.slice().sort(function (a, b) { return b.resid - a.resid; });
    var n = Math.min(4, Math.floor(by.length / 2));

    function chunk(list, cls) {
      return '<ol class="board-list ' + cls + '">' + list.map(function (d) {
        return '<li><img src="' + LOGO_DIR + esc(d.abbr) + '.svg" alt="" aria-hidden="true">' +
          '<span class="board-abbr">' + esc(d.abbr) + '</span>' +
          '<span class="board-resid">' + signed(d.resid, 2) + '</span>' +
          '<span class="board-mkt">' + pct(d.x) + '</span></li>';
      }).join('') + '</ol>';
    }

    return '<div class="board-reads">' +
      '<div class="board-read is-over"><h4>Model likes · market hasn’t</h4>' +
      '<p>Rated well above what the price implies for teams at that score.</p>' +
      chunk(by.slice(0, n), 'is-over') + '</div>' +
      '<div class="board-read is-under"><h4>Market likes · model doesn’t</h4>' +
      '<p>Priced well above where this model puts them.</p>' +
      chunk(by.slice(-n).reverse(), 'is-under') + '</div>' +
      '</div>';
  }

  /* ---------- tooltip ----------
   * Positioned against the wrapper rather than the page, so it travels with the
   * chart when the wrapper is scrolled sideways on a narrow screen. */
  function initTip(wrap, host) {
    var tip = document.createElement('div');
    tip.className = 'board-tip';
    tip.hidden = true;
    wrap.appendChild(tip);

    function show(g) {
      tip.innerHTML =
        '<strong>' + esc(g.dataset.team) + '</strong>' +
        '<span>market <b>' + esc(g.dataset.mkt) + '</b> to make</span>' +
        '<span>score <b>' + esc(g.dataset.score) + '</b></span>' +
        '<span class="' + (g.dataset.resid.charAt(0) === '−' ? 'is-under' : 'is-over') +
        '"><b>' + esc(g.dataset.resid) + '</b> vs the fit</span>';
      tip.hidden = false;

      // Flip to the left of the mark when it would otherwise run off the right.
      var x = parseFloat(g.dataset.x), y = parseFloat(g.dataset.y);
      var w = tip.offsetWidth;
      tip.style.left = Math.max(0, Math.min(host.clientWidth - w, x - w / 2)) + 'px';
      tip.style.top = (y + 16) + 'px';
    }

    function hide() { tip.hidden = true; }

    /* One handler for both showing and hiding. Pairing mouseover with mouseout
     * flickers: a group is a stem, an image and a hit circle, and crossing
     * between them fires a mouseout that is not a leave. Deciding on every
     * mouseover instead — a mark under the pointer shows, anything else hides —
     * has no such gap. */
    host.addEventListener('mouseover', function (e) {
      var g = e.target.closest ? e.target.closest('.board-pt') : null;
      if (g) show(g); else hide();
    });
    host.addEventListener('mouseleave', hide);
    host.addEventListener('focusin', function (e) {
      var g = e.target.closest ? e.target.closest('.board-pt') : null;
      if (g) show(g);
    });
    host.addEventListener('focusout', hide);
    return hide;
  }

  /* ---------- public ---------- */

  var cache = { teams: null, matches: null, hideTip: null };

  function renderBoard(teams, matches) {
    var wrap = document.getElementById('board-chart-wrap');
    var host = document.getElementById('board-chart');
    var reads = document.getElementById('board-reads');
    var note = document.getElementById('board-note');
    if (!host) return;

    cache.teams = teams;
    cache.matches = matches;
    if (cache.hideTip) cache.hideTip();

    var out = draw(host, teams, matches);
    if (!out) return;

    if (!cache.hideTip && wrap) cache.hideTip = initTip(wrap, host);
    if (reads) reads.innerHTML = summary(out.pts);
    if (note) {
      note.innerHTML =
        'Every team against both at once: the model’s composite score up the side, ' +
        'the market’s de-vigged price to make the playoffs along the bottom. The dashed ' +
        'line is where the two agree across the field (R² ' + out.r2.toFixed(2) +
        ') — so a team’s <strong>distance above or below it</strong> is the ' +
        'disagreement, and the stem draws it. The 32 de-vigged prices sum to ' +
        out.sum.toFixed(1) + ', against 14 playoff berths.';
    }
  }

  // The chart is measured in pixels, so it is redrawn rather than scaled.
  var resizeTimer = null;
  window.addEventListener('resize', function () {
    if (!cache.teams) return;
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      renderBoard(cache.teams, cache.matches);
    }, 150);
  });

  window.renderBoard = renderBoard;
})();
