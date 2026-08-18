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
     result. It is drawn across the teams and not across the axis: extending it
     to 0% and 100% would show a fit over a range no team occupies.

     The axis stays symmetric about zero, which was reconsidered when the
     compact layout needed height and deliberately kept. The field is −1.14 to
     +0.87, so on a 0.25 quantum −1.25 is already the tightest bound the bottom
     allows and every spare pixel is at the top; that gap is the shape of the
     model (its floor is further from average than its ceiling) rather than
     waste, and squaring it away would move the league average off the middle
     of the chart, which is the one thing the reader locates without a tick.

  2. Direction is carried by which side of the line a team sits on, and only
     after that by color. The page's green and orange are 5.7 ΔE apart under
     deuteranopia, below the safe floor; every tinted cell in the table gets
     away with it because it also prints a signed number beside the color. A
     chart mark prints nothing, so here position does the work and the color
     is along for the ride.

  3. The mark is the team's logo rather than a dot with a label. Thirty-two
     labelled dots need a legend or thirty-two pieces of leader text; a logo is
     its own label. It is not collision-free: an 18px mark clears every pair
     above about 820px wide, and below that the cloud is tight enough that a
     few pairs overlap — 4 pairs at 700px, 11 at 560px. That is tolerated
     because a partly-occluded logo is still identifiable, and the alternative
     is nudging marks off their true positions, which would make the residual
     the chart is built to show into a lie. What the overlap does buy is a
     floor on how small the chart may get: below 560px it goes portrait and
     compact — taller than wide, 13px marks, margins cut to the bone, axis
     titles moved out to HTML — rather than scrolling sideways. Portrait is
     what does the work there: the same 364px-wide field drops from 11
     overlapping pairs at a landscape aspect to 5 at H = 1.1W, because teams
     crowded in price are rarely crowded in score as well.

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

  /* Three widths doing three different jobs, which used to be one constant.
   * COMPACT_W is where the layout changes shape; MIN_W is where it stops
   * shrinking and the wrapper finally scrolls; FALLBACK_W is only ever used
   * when the host has no measured width yet, where guessing "phone" would be
   * the wrong guess. */
  var COMPACT_W = 560;
  var MIN_W = 300;
  var FALLBACK_W = 560;

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function imp(o) {
    return o > 0 ? 100 / (o + 100) : -o / (-o + 100);
  }

  /* The playoff pair, kept here as the fallback market for a caller that hands
   * over no market at all — bun-markets.js owns the other four and this one
   * too when the page is doing the asking. Null for a team the sheet priced on
   * only one side: there is no hold to divide out of a single number. */
  function marketProb(t) {
    var o = t.odds || {};
    if (o.make == null || o.miss == null) return null;
    var a = imp(o.make), b = imp(o.miss);
    return a / (a + b);
  }

  /* The y value comes from an accessor rather than straight off `t.score`,
   * because the page lets a reader re-weight the blend. When they do, the
   * sheet's published score is no longer the model's answer and everything
   * derived from it here — the fit, every residual, both lists — has to be
   * built from theirs instead. Callers that have no such notion pass nothing
   * and get `t.score`. */
  function points(teams, scoreOf, market) {
    var out = [];
    (teams || []).forEach(function (t) {
      var s = scoreOf ? scoreOf(t) : t.score;
      // x is the percentile and `raw` is the price behind it. The five markets
      // are four different units spread across four different orders of
      // magnitude — a 0.21% Super Bowl price against an 81% playoff one — so
      // the axis is the rank they share and the price rides along for the
      // tooltip, which is the one place it can be read as itself.
      var p = market ? market.pct[t.abbr] : null;
      var raw = market ? market.value[t.abbr] : null;
      if (p == null || s == null) return;
      out.push({
        abbr: t.abbr, team: t.team, conf: t.conf, div: t.div,
        x: p / 100, raw: raw, y: s
      });
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

  function signed(v, d) { return (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(d); }

  /* The playoff market, built here from the projections alone. Only ever used
   * when a caller passes no market — the page always passes one, so this is
   * what keeps the module standalone rather than a code path anyone reads. */
  function fallbackMarket(teams) {
    var value = {}, order = [];
    (teams || []).forEach(function (t) {
      var p = marketProb(t);
      if (p != null) { value[t.abbr] = p; order.push(t.abbr); }
    });
    var n = order.length, pctOf = {};
    order.forEach(function (k) {
      var below = 0;
      order.forEach(function (j) { if (value[j] < value[k]) below++; });
      pctOf[k] = n > 1 ? 100 * below / (n - 1) : 100;
    });
    return {
      key: 'playoffs', label: 'Make playoffs',
      axis: 'market — de-vigged chance to make the playoffs',
      tipLabel: 'to make', sumLabel: 'de-vigged prices',
      expected: 14, expectedNote: '14 playoff berths',
      fmt: function (v) { return Math.round(v * 100) + '%'; },
      totalFmt: function (v) { return v.toFixed(1); },
      ok: n >= 3, count: n, value: value, pct: pctOf,
      total: order.reduce(function (s2, k) { return s2 + value[k]; }, 0)
    };
  }

  /* ---------- the chart ---------- */

  function draw(host, teams, matches, scoreOf, market) {
    market = market || fallbackMarket(teams);
    var pts = points(teams, scoreOf, market);
    var f = fit(pts);
    if (!pts.length || !f) {
      host.innerHTML = '<p class="board-empty">Not enough priced teams to plot.</p>';
      return null;
    }

    /* Two tiers, and the branch lives here rather than in a media query
     * because none of what it decides — margins, mark size, tick spacing, how
     * many decimals a label carries, whether the axis titles are drawn at all
     * — is reachable from CSS. It is all baked into an SVG string measured in
     * pixels. Measuring the host rather than the viewport for the same reason:
     * clientWidth is the only number that agrees with what actually gets
     * drawn once a scrollbar or a narrower container is in play. */
    var cw = Math.floor(host.clientWidth || FALLBACK_W);
    var compact = cw < COMPACT_W;
    var W = Math.max(MIN_W, cw);

    // Portrait on a phone. Score and price are only half correlated, so height
    // is what separates teams the width has crowded together.
    var H = Math.max(340, Math.min(470, Math.round(W * (compact ? 1.1 : 0.56))));
    var mL = compact ? 34 : 54;
    var mR = compact ? 12 : 22;
    var mT = compact ? 14 : 30;
    var mB = compact ? 22 : 46;
    var LOGO = compact ? 13 : 18;
    var HIT = compact ? 12 : 15;   // 24px across at compact — the tap-target floor
    var FS = compact ? 9 : 10;
    var GAP = compact ? 6 : 8;     // y label to plot edge
    var x0 = mL, x1 = W - mR, yTop = mT, yBot = H - mB;
    var plotW = x1 - x0, plotH = yBot - yTop;

    /* x is a percentile, so the domain is the whole scale and does not move
     * when the market does. That is the point of ranking: the axis means the
     * same thing on a win total as on a Super Bowl price, and switching
     * markets moves the teams rather than redrawing the ruler underneath
     * them. */
    var xmin = 1, xmax = 0, ylim = 0, i;
    for (i = 0; i < pts.length; i++) {
      if (pts[i].x < xmin) xmin = pts[i].x;
      if (pts[i].x > xmax) xmax = pts[i].x;
      if (Math.abs(pts[i].y) > ylim) ylim = Math.abs(pts[i].y);
    }
    var xhi = 1;
    // Symmetric about zero: the axis is a z-score blend whose midpoint is the
    // league average, and an asymmetric one would put that average off-center.
    ylim = Math.ceil((ylim + 0.05) * 4) / 4;

    var sx = function (p) { return x0 + (p / xhi) * plotW; };
    var sy = function (v) { return yTop + (1 - (v + ylim) / (2 * ylim)) * plotH; };

    var svg = [];

    /* --- gridlines ---
     * These are the plot frame; there is no axis rect behind them, so the last
     * rule on each side has to land exactly on the domain bound or the
     * opposite set of rules ends in mid-air. Both loops therefore run off an
     * integer counter rather than accumulating a float step, which drifts
     * (0.2 six times over is 0.6000000000000001) and would miss the bound. */
    var g = [];
    var k, v, p;

    // x: a rule every tenth of the scale, a label every fifth. Bare numbers,
    // because these are percentiles and a "%" here would read as a price.
    var nx = Math.round(xhi / 0.1);
    for (k = 0; k <= nx; k++) {
      p = k / 10;
      g.push('<line x1="' + sx(p).toFixed(1) + '" y1="' + yTop + '" x2="' + sx(p).toFixed(1) +
        '" y2="' + yBot + '" stroke="' + AXIS + '" stroke-width="1"/>');
      if (k % 2 === 0 || k === nx) {
        g.push(svgText(sx(p).toFixed(1), yBot + FS + 6, String(Math.round(p * 100)),
          { anchor: 'middle', size: FS }));
      }
    }

    /* y: outward from zero, not upward from −ylim. Stepping from the bound
     * meant zero was a tick only when ylim happened to be a multiple of the
     * step, which on a 0.25 quantum it usually is not — so the dashed rule at
     * the league average was described in two comments and drawn in none, and
     * every label carried a quarter it did not need. Counting out from zero
     * guarantees the rule and makes the labels clean halves, which is also
     * what pays for the narrow left margin. */
    var ny = Math.floor(ylim / 0.5 + 1e-9);
    for (k = 0; k <= ny; k++) {
      var vs = k === 0 ? [0] : [k * 0.5, -k * 0.5];
      for (var j = 0; j < vs.length; j++) {
        v = vs[j];
        g.push('<line x1="' + x0 + '" y1="' + sy(v).toFixed(1) + '" x2="' + x1 +
          '" y2="' + sy(v).toFixed(1) + '" stroke="' + (k === 0 ? GUIDE : AXIS) +
          '" stroke-width="1"' + (k === 0 ? ' stroke-dasharray="3 3"' : '') + '/>');
        g.push(svgText(x0 - GAP, (sy(v) + 3).toFixed(1), signed(v, 1),
          { anchor: 'end', size: FS }));
      }
    }
    // The bounds close the top and bottom of the frame. Unlabelled: they are
    // padding rounded up to a quarter, not a value anyone should read.
    [-ylim, ylim].forEach(function (b) {
      g.push('<line x1="' + x0 + '" y1="' + sy(b).toFixed(1) + '" x2="' + x1 +
        '" y2="' + sy(b).toFixed(1) + '" stroke="' + AXIS + '" stroke-width="1"/>');
    });
    svg.push(g.join(''));

    /* --- the fit line, drawn across the teams rather than across the axis ---
     * Running it edge to edge showed the fit over a range no team is priced
     * in — nearly a fifth of the width past the priciest one — which reads as
     * a prediction the regression has no data behind. It stops at the outer
     * two teams instead, overhanging by half a mark so it passes through them
     * rather than stopping at their centres. The y clamp then makes the "clipped
     * to the plot" this comment used to claim actually true, without a clipPath. */
    var pad = (LOGO / 2 + 4) * xhi / plotW;
    var xL = Math.max(0, xmin - pad), xR = Math.min(xhi, xmax + pad);
    if (f.b) {
      var atY = function (y) { return (y - f.a) / f.b; };
      var lo = Math.min(atY(-ylim), atY(ylim)), hi = Math.max(atY(-ylim), atY(ylim));
      xL = Math.min(Math.max(xL, lo), hi);
      xR = Math.min(Math.max(xR, lo), hi);
    }
    var fyL = f.a + f.b * xL, fyR = f.a + f.b * xR;
    svg.push('<line x1="' + sx(xL).toFixed(1) + '" y1="' + sy(fyL).toFixed(1) +
      '" x2="' + sx(xR).toFixed(1) + '" y2="' + sy(fyR).toFixed(1) +
      '" stroke="' + GUIDE + '" stroke-width="1.5" stroke-dasharray="6 4"/>');
    /* Below the line, not above it: the line now ends among the priciest teams
     * instead of out in empty space, and above-right sits on top of them.
     * Dropped entirely at compact, where 70px of label has nowhere to go — all
     * four corners of the line land on a mark at 364px wide. #board-note names
     * the dashed line in prose directly above the chart, so nothing is lost. */
    if (!compact) {
      svg.push(svgText((sx(xR) - 4).toFixed(1), (sy(fyR) + 14).toFixed(1), 'market agrees', {
        anchor: 'end', size: 9, opacity: '0.75'
      }));
    }

    // --- corner annotations: what each side of the line means ---
    // They sit inside the plot, so they cost no margin at either width, and
    // they are the only thing in the SVG that says what the two colors are.
    svg.push(svgText(x0 + 10, yTop + 15,
      compact ? 'model likes' : 'model likes · market doesn’t', {
        size: 9, fill: GREEN, opacity: '0.6'
      }));
    svg.push(svgText(x1 - 10, yBot - 8,
      compact ? 'market likes' : 'market likes · model doesn’t', {
        size: 9, fill: ORANGE, opacity: '0.6', anchor: 'end'
      }));

    /* --- one group per team: residual stem, then the logo on top of it ---
     * Filtered-out teams are emitted first so the faded ones cannot cover a
     * team that was asked for. Data order put them wherever the JSON happened
     * to list them, and a 0.16-opacity logo drawn last both hides an active
     * mark and wins the hit test in front of it, so pointing at a team the
     * chips had selected could open a tooltip for one they had not. */
    var marksOff = [], marksOn = [];
    pts.forEach(function (d) {
      var cx = sx(d.x), cy = sy(d.y);
      var ly = sy(f.a + f.b * d.x);
      d.resid = d.y - (f.a + f.b * d.x);

      // A filtered-out team keeps its place — the field is the point of the
      // chart — but drops its stem and fades, so the chips read as "show me
      // where these sit" rather than as a different chart.
      var on = matches ? matches(d) : true;
      var col = d.resid >= 0 ? GREEN : ORANGE;

      (on ? marksOn : marksOff).push('<g class="board-pt' + (on ? '' : ' is-off') + '"' +
        ' data-abbr="' + esc(d.abbr) + '" data-team="' + esc(d.team) + '"' +
        ' data-x="' + cx.toFixed(1) + '" data-y="' + cy.toFixed(1) + '"' +
        ' data-mkt="' + esc(market.fmt(d.raw)) + '" data-pct="' + Math.round(d.x * 100) + '"' +
        ' data-label="' + esc(market.tipLabel) + '"' +
        ' data-score="' + signed(d.y, 2) + '"' +
        ' data-resid="' + signed(d.resid, 2) + '" tabindex="0" role="listitem"' +
        ' aria-label="' + esc(d.team) + ': ' + esc(market.tipLabel) + ' ' +
        esc(market.fmt(d.raw)) + ', ' + Math.round(d.x * 100) + 'th percentile, score ' +
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
        '" r="' + HIT + '" fill="transparent"/>' +
        '</g>');
    });
    svg.push(marksOff.join('') + marksOn.join(''));

    /* --- axis titles ---
     * Dropped at compact, where the rotated one alone would eat a ninth of the
     * total width — the most expensive pixels on the page. #board-axis-note
     * carries both as real HTML instead, which is selectable, translatable and
     * respects the reader's font size, none of which SVG text baked at 9px is. */
    if (!compact) {
      svg.push(svgText((x0 + x1) / 2, H - 8, esc(market.axis + ', percentile'),
        { anchor: 'middle', size: 10 }));
      svg.push(svgText(15, (yTop + yBot) / 2, 'model — composite score', {
        anchor: 'middle', size: 10, transform: 'rotate(-90 15 ' + ((yTop + yBot) / 2) + ')'
      }));
    }

    host.innerHTML =
      '<svg class="board-svg" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '"' +
      ' role="list" aria-label="Model composite score against ' + esc(market.axis) +
      ', as a percentile, ' + pts.length + ' teams. Teams above the fitted line are ones the ' +
      'model rates higher than the market prices them.">' + svg.join('') + '</svg>';

    return { pts: pts, r2: f.r2, compact: compact, width: cw, market: market };
  }

  /* ---------- the read-out beneath the chart ----------
   * The chart's own accessible fallback, and the part most people will actually
   * quote. Computed rather than written down, so it can never drift from the
   * numbers above it the way a hand-typed list would. */
  function summary(pts, market) {
    var by = pts.slice().sort(function (a, b) { return b.resid - a.resid; });
    var n = Math.min(5, Math.floor(by.length / 2));

    function chunk(list, cls) {
      return '<ol class="board-list ' + cls + '">' + list.map(function (d) {
        return '<li><img src="' + LOGO_DIR + esc(d.abbr) + '.svg" alt="" aria-hidden="true">' +
          '<span class="board-abbr">' + esc(d.abbr) + '</span>' +
          '<span class="board-resid">' + signed(d.resid, 2) + '</span>' +
          '<span class="board-mkt">' + esc(market.fmt(d.raw)) + '</span></li>';
      }).join('') + '</ol>';
    }

    return '<div class="board-reads">' +
      '<div class="board-read is-over"><h4>Model likes · market doesn’t</h4>' +
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
        '<span>' + esc(g.dataset.label) + ' <b>' + esc(g.dataset.mkt) + '</b></span>' +
        '<span>market rank <b>' + esc(g.dataset.pct) + '</b> of 100</span>' +
        '<span>score <b>' + esc(g.dataset.score) + '</b></span>' +
        '<span class="' + (g.dataset.resid.charAt(0) === '−' ? 'is-under' : 'is-over') +
        '"><b>' + esc(g.dataset.resid) + '</b> vs the fit</span>';
      tip.hidden = false;

      // Flip to the left of the mark when it would otherwise run off the
      // right, and above it when it would run off the bottom — the wrapper
      // hides its overflow, so a tip placed past the edge is simply gone.
      var x = parseFloat(g.dataset.x), y = parseFloat(g.dataset.y);
      var w = tip.offsetWidth, h = tip.offsetHeight;
      tip.style.left = Math.max(0, Math.min(host.clientWidth - w, x - w / 2)) + 'px';
      tip.style.top = (y + 16 + h > host.clientHeight ? y - 16 - h : y + 16) + 'px';
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

    /* Touch. Without this the compact chart is thirty-two unlabelled logos:
     * everything above is hover or focus, and a phone has neither. `click`
     * rather than `touchstart`, which fires before the browser has decided
     * whether the gesture was a tap or the start of a scroll, and then fires
     * again as a synthetic click on iOS. */
    host.addEventListener('click', function (e) {
      var g = e.target.closest ? e.target.closest('.board-pt') : null;
      if (g) show(g); else hide();
    });
    document.addEventListener('click', function (e) {
      if (!host.contains(e.target)) hide();
    });
    return hide;
  }

  /* ---------- public ---------- */

  var cache = { teams: null, matches: null, scoreOf: null, market: null, hideTip: null, width: null };

  function renderBoard(teams, matches, scoreOf, market) {
    var wrap = document.getElementById('board-chart-wrap');
    var host = document.getElementById('board-chart');
    var reads = document.getElementById('board-reads');
    var note = document.getElementById('board-note');
    var axisNote = document.getElementById('board-axis-note');
    if (!host) return;

    cache.teams = teams;
    cache.matches = matches;
    cache.scoreOf = scoreOf;
    cache.market = market;
    if (cache.hideTip) cache.hideTip();

    var out = draw(host, teams, matches, scoreOf, market);
    if (!out) return;

    cache.width = out.width;
    // The axis titles live in one place or the other, never both.
    if (axisNote) axisNote.hidden = !out.compact;

    if (!cache.hideTip && wrap) cache.hideTip = initTip(wrap, host);
    if (reads) reads.innerHTML = summary(out.pts, out.market);

    var m = out.market;
    if (axisNote) {
      axisNote.innerHTML = '&uarr; model — composite score &middot; &rarr; ' +
        esc(m.axis) + ', percentile';
    }
    if (note) {
      /* The sum is the market's own audit and it is different for each one —
       * 14 berths, 8 divisions, 2 conferences, 1 champion, 272 wins. Printing
       * it rather than asserting it is what makes the de-vig checkable by the
       * reader instead of trusted. */
      note.innerHTML =
        'Every team against both at once: the model’s composite score up the side, ' +
        esc(m.axis.replace(/^market — /, 'the market’s ')) + ' along the bottom, ' +
        'ranked 0–100 across the field. The dashed line is where the two agree ' +
        '(R² ' + out.r2.toFixed(2) + ') — so a team’s <strong>distance above or below ' +
        'it</strong> is the disagreement, and the stem draws it. The ' + m.count + ' ' +
        esc(m.sumLabel) + ' sum to ' + m.totalFmt(m.total) + ', against ' +
        esc(m.expectedNote) + '.';
    }
  }

  /* The chart is measured in pixels, so it is redrawn rather than scaled — but
   * only when the width it was measured against has actually moved. iOS fires
   * resize every time the URL bar collapses, which is a height change, and
   * rebuilding thirty-two <image> elements and closing the tooltip in the
   * middle of a scroll is not what the reader asked for. */
  var resizeTimer = null;
  window.addEventListener('resize', function () {
    if (!cache.teams) return;
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      var host = document.getElementById('board-chart');
      if (host && cache.width != null && Math.floor(host.clientWidth) === cache.width) return;
      renderBoard(cache.teams, cache.matches, cache.scoreOf, cache.market);
    }, 150);
  });

  window.renderBoard = renderBoard;
})();
