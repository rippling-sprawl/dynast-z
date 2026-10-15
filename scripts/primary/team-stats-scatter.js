/*
  Team Stats — Yards vs Points.

  Every team placed by point differential per game (x) and yardage
  differential per game (y). Per game rather than season totals because a bye
  leaves some teams a game behind for a week, and a cumulative margin would
  read that missing game as a worse team.

  The two numbers usually travel together — out-gain people and you tend to
  outscore them — so the cloud runs bottom-left to top-right and the dashed
  line is that trend, fitted across the league. What a bettor reads off it is
  the horizontal distance: a team left of the line is scoring less than its
  yardage says it should (turnovers, red-zone stalls, one-score losses), one
  right of it is scoring more. Points are the noisier of the two, so those
  gaps are where a team's record is most likely to move back toward its
  yardage. The read-out under the chart lists the five furthest each way.

  The fit is points on yards, not yards on points, for that reason: yards are
  treated as the steadier signal and points as the thing being explained. On
  this chart's axes that makes the residual horizontal.

  The mark is the logo, as on the Baker's Buns board (bun-charts.js), and for
  the same reasons: a logo is its own label, partly-overlapped logos are still
  readable, and nudging marks apart would move them off their true values.
*/
(function () {
  'use strict';

  var LOGO_DIR = '/assets/icons/nfl/';

  /* Read from the theme tokens on every draw, because an SVG built as a string
   * cannot spend var(--x). The fallbacks are the dark values. */
  var GREEN, ORANGE, AXIS, GUIDE, INK;

  function refreshPalette() {
    var c = (window.Theme && window.Theme.color) || function (t, f) { return f; };
    GREEN = c('--good', '#3fb950');
    ORANGE = c('--orange', '#f0883e');
    AXIS = c('--hairline', '#2a2a2a');
    GUIDE = c('--text-5', '#484f58');
    INK = c('--text-3', '#8b949e');
  }

  // Same three widths as bun-charts.js: where the layout changes shape, where
  // it stops shrinking, and the guess used before the host has a width.
  var COMPACT_W = 560;
  var MIN_W = 300;
  var FALLBACK_W = 560;

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function signed(v, d) { return (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(d); }

  function svgText(x, y, s, o) {
    o = o || {};
    return '<text x="' + x + '" y="' + y + '"' +
      ' fill="' + (o.fill || INK) + '" font-size="' + (o.size || 10) + '"' +
      ' font-family="monospace"' +
      (o.opacity ? ' opacity="' + o.opacity + '"' : '') +
      ' text-anchor="' + (o.anchor || 'start') + '"' +
      (o.transform ? ' transform="' + o.transform + '"' : '') +
      '>' + s + '</text>';
  }

  function points(teams) {
    return (teams || []).filter(function (t) { return t.gp > 0; }).map(function (t) {
      return {
        abbr: t.abbr, team: t.team, gp: t.gp,
        pf: t.pf / t.gp, pa: t.pa / t.gp, yf: t.yf / t.gp, ya: t.ya / t.gp,
        x: (t.pf - t.pa) / t.gp,
        y: (t.yf - t.ya) / t.gp
      };
    });
  }

  /* Points on yards: x = a + b·y. Over every team, so a residual belongs to the
   * team and not to whatever else happens to be on the chart. */
  function fit(pts) {
    var n = pts.length;
    if (n < 3) return null;
    var mx = 0, my = 0, i;
    for (i = 0; i < n; i++) { mx += pts[i].x; my += pts[i].y; }
    mx /= n; my /= n;
    var sxy = 0, syy = 0, sxx = 0, dx, dy;
    for (i = 0; i < n; i++) {
      dx = pts[i].x - mx; dy = pts[i].y - my;
      sxy += dx * dy; syy += dy * dy; sxx += dx * dx;
    }
    if (!syy || !sxx) return null;
    var b = sxy / syy;
    return { a: mx - b * my, b: b, r2: (sxy * sxy) / (sxx * syy) };
  }

  /* A 1/2/5 step that puts about `n` ticks on each side of zero, and the bound
   * rounded up to it. Both axes are symmetric about zero: zero is the league
   * average on each, and the quadrants only mean something if it is centred. */
  function axis(maxAbs, n) {
    var raw = Math.max(maxAbs, 1e-6) / n;
    var mag = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10));
    var step = [1, 2, 5, 10].map(function (m) { return m * mag; })
      .filter(function (s) { return s >= raw; })[0];
    return { step: step, lim: Math.ceil((maxAbs * 1.06) / step) * step };
  }

  function draw(host, teams) {
    refreshPalette();
    var pts = points(teams);
    var f = fit(pts);
    if (!pts.length || !f) {
      host.innerHTML = '<p class="ts-empty">Not enough games played to plot.</p>';
      return null;
    }

    var cw = Math.floor(host.clientWidth || FALLBACK_W);
    var compact = cw < COMPACT_W;
    var W = Math.max(MIN_W, cw);
    var H = Math.max(340, Math.min(520, Math.round(W * (compact ? 1.1 : 0.62))));
    var mL = compact ? 36 : 56;
    var mR = compact ? 12 : 22;
    var mT = compact ? 14 : 22;
    var mB = compact ? 22 : 46;
    var LOGO = compact ? 15 : 22;
    var HIT = compact ? 12 : 15;
    var FS = compact ? 9 : 10;
    var x0 = mL, x1 = W - mR, yTop = mT, yBot = H - mB;
    var plotW = x1 - x0, plotH = yBot - yTop;

    var mxAbs = 0, myAbs = 0;
    pts.forEach(function (d) {
      mxAbs = Math.max(mxAbs, Math.abs(d.x));
      myAbs = Math.max(myAbs, Math.abs(d.y));
    });
    var ax = axis(mxAbs, 3);
    var ay = axis(myAbs, 3);

    var sx = function (v) { return x0 + ((v + ax.lim) / (2 * ax.lim)) * plotW; };
    var sy = function (v) { return yTop + (1 - (v + ay.lim) / (2 * ay.lim)) * plotH; };

    var svg = [], k, v, n;

    /* Gridlines, counted outward from zero on an integer counter so the last
     * rule lands exactly on the bound and closes the frame. Zero is dashed:
     * it is the league average and the quadrant boundary. */
    n = Math.round(ax.lim / ax.step);
    for (k = -n; k <= n; k++) {
      v = k * ax.step;
      svg.push('<line x1="' + sx(v).toFixed(1) + '" y1="' + yTop + '" x2="' + sx(v).toFixed(1) +
        '" y2="' + yBot + '" stroke="' + (k === 0 ? GUIDE : AXIS) + '" stroke-width="1"' +
        (k === 0 ? ' stroke-dasharray="3 3"' : '') + '/>');
      svg.push(svgText(sx(v).toFixed(1), yBot + FS + 6, signed(v, 0), { anchor: 'middle', size: FS }));
    }
    n = Math.round(ay.lim / ay.step);
    for (k = -n; k <= n; k++) {
      v = k * ay.step;
      svg.push('<line x1="' + x0 + '" y1="' + sy(v).toFixed(1) + '" x2="' + x1 +
        '" y2="' + sy(v).toFixed(1) + '" stroke="' + (k === 0 ? GUIDE : AXIS) + '" stroke-width="1"' +
        (k === 0 ? ' stroke-dasharray="3 3"' : '') + '/>');
      svg.push(svgText(x0 - (compact ? 5 : 8), (sy(v) + 3).toFixed(1), signed(v, 0),
        { anchor: 'end', size: FS }));
    }

    /* The trend, drawn across the teams' yardage range only — past the outer
     * teams it would be a prediction with no data behind it — and clamped to
     * the plot so a steep fit cannot run off the frame. */
    var ylo = Infinity, yhi = -Infinity;
    pts.forEach(function (d) { ylo = Math.min(ylo, d.y); yhi = Math.max(yhi, d.y); });
    var seg = [];
    [ylo, yhi].forEach(function (yy) {
      var xx = f.a + f.b * yy;
      if (xx < -ax.lim || xx > ax.lim) {
        xx = Math.max(-ax.lim, Math.min(ax.lim, xx));
        yy = f.b ? (xx - f.a) / f.b : yy;
      }
      seg.push([sx(xx), sy(yy)]);
    });
    svg.push('<line x1="' + seg[0][0].toFixed(1) + '" y1="' + seg[0][1].toFixed(1) +
      '" x2="' + seg[1][0].toFixed(1) + '" y2="' + seg[1][1].toFixed(1) +
      '" stroke="' + GUIDE + '" stroke-width="1.5" stroke-dasharray="6 4"/>');

    // Corner annotations: the two off-diagonal quadrants are the ones with a
    // story, so they are the ones that carry color.
    var cs = compact ? 8 : 9;
    svg.push(svgText(x0 + 8, yTop + 14, compact ? 'out-gaining · outscored' : 'out-gaining them · outscored anyway',
      { size: cs, fill: GREEN, opacity: '0.7' }));
    svg.push(svgText(x1 - 8, yBot - 8, compact ? 'out-gained · outscoring' : 'out-gained · outscoring them anyway',
      { size: cs, fill: ORANGE, opacity: '0.7', anchor: 'end' }));

    var marks = [];
    pts.forEach(function (d) {
      var cx = sx(d.x), cy = sy(d.y);
      d.resid = d.x - (f.a + f.b * d.y);
      marks.push('<g class="ts-pt" data-abbr="' + esc(d.abbr) + '"' +
        ' data-x="' + cx.toFixed(1) + '" data-y="' + cy.toFixed(1) + '" tabindex="0" role="listitem"' +
        ' aria-label="' + esc(d.team) + ': ' + signed(d.x, 1) + ' points and ' + signed(d.y, 1) +
        ' yards per game over ' + d.gp + ' games">' +
        '<image href="' + LOGO_DIR + esc(d.abbr) + '.svg" x="' + (cx - LOGO / 2).toFixed(1) +
        '" y="' + (cy - LOGO / 2).toFixed(1) + '" width="' + LOGO + '" height="' + LOGO + '"/>' +
        '<circle cx="' + cx.toFixed(1) + '" cy="' + cy.toFixed(1) + '" r="' + HIT +
        '" fill="transparent"/></g>');
    });
    svg.push(marks.join(''));

    // Axis titles in the SVG only when there is room; at compact the HTML
    // note under the chart carries them.
    if (!compact) {
      svg.push(svgText((x0 + x1) / 2, H - 8, 'point differential per game', { anchor: 'middle' }));
      svg.push(svgText(15, (yTop + yBot) / 2, 'yardage differential per game', {
        anchor: 'middle', transform: 'rotate(-90 15 ' + ((yTop + yBot) / 2) + ')'
      }));
    }

    host.innerHTML =
      '<svg class="ts-svg" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '"' +
      ' role="list" aria-label="Point differential per game against yardage differential per game, ' +
      pts.length + ' teams.">' + svg.join('') + '</svg>';

    return { pts: pts, fit: f, compact: compact, width: cw };
  }

  /* The five furthest from the trend each way. Computed, never typed, so it
   * cannot drift from the chart above it. */
  function summary(pts) {
    var by = pts.slice().sort(function (a, b) { return a.resid - b.resid; });
    var n = Math.min(5, Math.floor(by.length / 2));

    function list(rows, cls) {
      return '<ol class="ts-list ' + cls + '">' + rows.map(function (d) {
        return '<li><img src="' + LOGO_DIR + esc(d.abbr) + '.svg" alt="" aria-hidden="true">' +
          '<span class="ts-abbr">' + esc(d.abbr) + '</span>' +
          '<span class="ts-resid">' + signed(d.resid, 1) + '</span>' +
          '<span class="ts-ctx">' + signed(d.x, 1) + ' pts · ' + signed(d.y, 0) + ' yds</span></li>';
      }).join('') + '</ol>';
    }

    return '<div class="ts-reads">' +
      '<div class="ts-read is-up"><h4>Scoring below their yards</h4>' +
      '<p>Points per game short of what their yardage margin usually buys.</p>' +
      list(by.slice(0, n), 'is-up') + '</div>' +
      '<div class="ts-read is-down"><h4>Scoring above their yards</h4>' +
      '<p>Points per game beyond what their yardage margin usually buys.</p>' +
      list(by.slice(-n).reverse(), 'is-down') + '</div>' +
      '</div>';
  }

  function initTip(wrap, host, byAbbr) {
    var tip = document.createElement('div');
    tip.className = 'ts-tip';
    tip.hidden = true;
    wrap.appendChild(tip);

    function show(g) {
      var d = byAbbr()[g.dataset.abbr];
      if (!d) return;
      tip.innerHTML =
        '<strong>' + esc(d.team) + '</strong>' +
        '<span>' + d.gp + ' games</span>' +
        '<span>points <b>' + d.pf.toFixed(1) + '</b> – ' + d.pa.toFixed(1) +
        ' <b>(' + signed(d.x, 1) + ')</b></span>' +
        '<span>yards <b>' + d.yf.toFixed(0) + '</b> – ' + d.ya.toFixed(0) +
        ' <b>(' + signed(d.y, 0) + ')</b></span>' +
        '<span class="' + (d.resid < 0 ? 'is-up' : 'is-down') + '"><b>' + signed(d.resid, 1) +
        '</b> pts vs the trend</span>';
      tip.hidden = false;
      var x = parseFloat(g.dataset.x), y = parseFloat(g.dataset.y);
      var w = tip.offsetWidth, h = tip.offsetHeight;
      tip.style.left = Math.max(0, Math.min(host.clientWidth - w, x - w / 2)) + 'px';
      tip.style.top = (y + 16 + h > host.clientHeight ? y - 16 - h : y + 16) + 'px';
    }
    function hide() { tip.hidden = true; }

    // Decided on every mouseover rather than paired with mouseout, which
    // flickers crossing between a mark's image and its hit circle.
    host.addEventListener('mouseover', function (e) {
      var g = e.target.closest ? e.target.closest('.ts-pt') : null;
      if (g) show(g); else hide();
    });
    host.addEventListener('mouseleave', hide);
    host.addEventListener('focusin', function (e) {
      var g = e.target.closest ? e.target.closest('.ts-pt') : null;
      if (g) show(g);
    });
    host.addEventListener('focusout', hide);
    // A phone has neither hover nor focus; a tap is how it gets a tooltip.
    host.addEventListener('click', function (e) {
      var g = e.target.closest ? e.target.closest('.ts-pt') : null;
      if (g) show(g); else hide();
    });
    document.addEventListener('click', function (e) {
      if (!host.contains(e.target)) hide();
    });
    return hide;
  }

  var state = { teams: null, width: null, hideTip: null, byAbbr: {} };

  function render(teams) {
    var wrap = document.getElementById('ts-chart-wrap');
    var host = document.getElementById('ts-chart');
    var reads = document.getElementById('ts-reads');
    var axisNote = document.getElementById('ts-axis-note');
    var fitNote = document.getElementById('ts-fit');
    if (!host) return;

    state.teams = teams;
    if (state.hideTip) state.hideTip();
    var out = draw(host, teams);
    if (!out) return;

    state.width = out.width;
    state.byAbbr = {};
    out.pts.forEach(function (d) { state.byAbbr[d.abbr] = d; });
    if (!state.hideTip && wrap) state.hideTip = initTip(wrap, host, function () { return state.byAbbr; });

    if (axisNote) axisNote.hidden = !out.compact;
    if (reads) reads.innerHTML = summary(out.pts);
    if (fitNote) {
      fitNote.textContent = 'Trend: every 10 yards of margin per game is worth ' +
        signed(out.fit.b * 10, 1) + ' points of margin (R² ' + out.fit.r2.toFixed(2) + ').';
    }
  }

  // Redraw only when the measured width moves — iOS fires resize as the URL
  // bar collapses, which is a height change.
  var resizeTimer = null;
  window.addEventListener('resize', function () {
    if (!state.teams) return;
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      var host = document.getElementById('ts-chart');
      if (host && Math.floor(host.clientWidth) === state.width) return;
      render(state.teams);
    }, 150);
  });

  // Every color is baked into the SVG string, so a theme change is a redraw.
  window.addEventListener('themechange', function () {
    if (state.teams) render(state.teams);
  });

  window.renderYardsVsPoints = render;
})();
