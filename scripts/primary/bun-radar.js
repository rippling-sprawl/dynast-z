/*
  Baker's Buns — one team against all five markets.

  The Board answers "where does the model disagree with the market" one market
  at a time across thirty-two teams. This answers it five markets at a time for
  one team, which is the question a reader actually has once a team has caught
  their eye on the scatter: is the market high on this team everywhere, or only
  in the market I happened to be looking at?

  Two decisions worth stating:

  1. The model is a ring, not a polygon. It is one number — the composite score
     — so its percentile is the same on all five spokes and it draws as a
     regular pentagon. That looks like a mistake for about a second and then
     becomes the whole point: the model has no opinion about which market you
     ask it, so every departure of the orange shape from the grey one is the
     market moving, never the model. A reader can therefore read a single gap
     without holding two varying quantities in their head.

  2. The spokes are percentiles, not prices, for the same reason the scatter's
     axis is. Five markets on five spokes have to mean the same thing at the
     same radius, and 11.5 wins, a 52% division price and a 0.21% Super Bowl
     price do not. The price is printed in the bubble on each spoke, so the
     shape is the rank and the label is the fact.

  The mark on each spoke is a filled bubble carrying the percentile, borrowed
  from the combine radars this was modelled on: at five spokes there is room
  for the number, and a shape whose vertices are unlabelled asks the reader to
  measure against a grid instead of reading.
*/
(function () {
  'use strict';

  var ORANGE = '#f0883e';
  var GREEN = '#3fb950';
  var AXIS = '#2a2a2a';
  var GUIDE = '#484f58';
  var INK = '#8b949e';
  var INK_HI = '#f0f0f0';

  var MIN_W = 280;
  var FALLBACK_W = 560;
  var COMPACT_W = 460;

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function signed(v, d) {
    return (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(d);
  }

  function svgText(x, y, s, o) {
    o = o || {};
    return '<text x="' + x + '" y="' + y + '"' +
      ' fill="' + (o.fill || INK) + '" font-size="' + (o.size || 10) + '"' +
      ' font-family="monospace"' +
      (o.weight ? ' font-weight="' + o.weight + '"' : '') +
      (o.opacity ? ' opacity="' + o.opacity + '"' : '') +
      ' text-anchor="' + (o.anchor || 'start') + '">' + s + '</text>';
  }

  /* The model's rank in the same 0–100 the markets are ranked in, so the ring
   * and the polygon are on one scale. Computed over the whole field and never
   * over a filtered view, for the reason the scatter's fit is: a percentile
   * that moved when a chip was clicked would be a different statistic. */
  function modelPct(teams, scoreOf, abbr) {
    var vals = [], mine = null;
    (teams || []).forEach(function (t) {
      var s = scoreOf ? scoreOf(t) : t.score;
      if (s == null) return;
      vals.push(s);
      if (t.abbr === abbr) mine = s;
    });
    if (mine == null || vals.length < 2) return null;
    var below = 0, equal = 0;
    vals.forEach(function (v) {
      if (v < mine) below++; else if (v === mine) equal++;
    });
    return 100 * (below + (equal - 1) / 2) / (vals.length - 1);
  }

  /* Short spoke labels. The market's own `label` is written for a chip in a
   * row, where "Win Super Bowl" reads correctly; on a spoke there is no verb
   * to carry and the noun is what the reader is matching against the bubble. */
  var SHORT = {
    winTotal: 'WIN TOTAL', playoffs: 'PLAYOFFS', division: 'DIVISION',
    conference: 'CONFERENCE', superBowl: 'SUPER BOWL'
  };

  function draw(host, team, markets, teams, scoreOf) {
    var usable = (markets || []).filter(function (m) {
      return m.ok && m.pct[team.abbr] != null;
    });
    var mp = modelPct(teams, scoreOf, team.abbr);
    if (usable.length < 3 || mp == null) {
      host.innerHTML = '<p class="board-empty">Not enough priced markets for ' +
        esc(team.team) + '.</p>';
      return null;
    }

    var cw = Math.floor(host.clientWidth || FALLBACK_W);
    var compact = cw < COMPACT_W;
    var W = Math.max(MIN_W, cw);
    var H = Math.round(W * (compact ? 0.95 : 0.78));

    var FS = compact ? 9 : 10;
    var BUB = compact ? 12 : 14;          // bubble radius
    var PAD = 2;                          // breathing room at the SVG edge
    var LEAD = BUB + 10;                  // ring to label, clear of a 100 bubble

    var cx = W / 2, cy = H / 2 + (compact ? 4 : 6);

    var n = usable.length;
    // First spoke at twelve o'clock, then clockwise — the reading order the
    // labels are listed in everywhere else on the page.
    var ang = function (i) { return -Math.PI / 2 + (2 * Math.PI * i) / n; };

    var labels = usable.map(function (m) { return SHORT[m.key] || m.label; });
    var anchorAt = function (ca) {
      return Math.abs(ca) < 0.25 ? 'middle' : ca > 0 ? 'start' : 'end';
    };
    // A label above or below the centre needs its own baseline nudge; one out
    // to the side wants to sit on its spoke.
    var dyAt = function (ca, sa) {
      return Math.abs(ca) < 0.25 ? (sa < 0 ? -2 : FS + 1) : FS / 3;
    };

    /* The radius is solved from the labels rather than set from a pad constant,
     * because the labels are what actually reach the edges — the rings never
     * do. A constant has to be guessed against the longest one at the tightest
     * width, and SUPER BOWL on the upper-left spoke of a 360px phone is a
     * different guess from CONFERENCE on a 960px desktop. Asking each label
     * how much room it needs and taking the smallest answer is the same
     * arithmetic, done from the strings actually being drawn, so it cannot be
     * wrong for a label set this file does not yet have. */
    var R = Math.min(cx, cy, H - cy) - LEAD;
    for (var si = 0; si < n; si++) {
      var sa0 = ang(si), ca = Math.cos(sa0), sa = Math.sin(sa0);
      var lw = labels[si].length * 0.6 * FS;   // monospace advance
      var an = anchorAt(ca), dyv = dyAt(ca, sa);
      var cap;
      if (an === 'start') {
        cap = (W - PAD - lw - cx) / ca - LEAD;
      } else if (an === 'end') {
        cap = (PAD + lw - cx) / ca - LEAD;
      } else {
        cap = Infinity;   // a centred label's width is not a function of R
      }
      if (cap < R) R = cap;
      if (sa < -0.05) {
        cap = (PAD - dyv + 0.8 * FS - cy) / sa - LEAD;
      } else if (sa > 0.05) {
        cap = (H - PAD - dyv - 0.2 * FS - cy) / sa - LEAD;
      } else {
        cap = Infinity;
      }
      if (cap < R) R = cap;
    }
    R = Math.max(40, R);
    var px = function (i, r) { return cx + Math.cos(ang(i)) * R * (r / 100); };
    var py = function (i, r) { return cy + Math.sin(ang(i)) * R * (r / 100); };

    function ring(r) {
      var pts = [];
      for (var i = 0; i < n; i++) pts.push(px(i, r).toFixed(1) + ',' + py(i, r).toFixed(1));
      return pts.join(' ');
    }

    var svg = [];

    // --- grid: a web at every fifth, plus a spoke out to each market ---
    for (var r = 20; r <= 100; r += 20) {
      svg.push('<polygon points="' + ring(r) + '" fill="none" stroke="' + AXIS +
        '" stroke-width="1"/>');
    }
    for (var i = 0; i < n; i++) {
      svg.push('<line x1="' + cx.toFixed(1) + '" y1="' + cy.toFixed(1) +
        '" x2="' + px(i, 100).toFixed(1) + '" y2="' + py(i, 100).toFixed(1) +
        '" stroke="' + AXIS + '" stroke-width="1"/>');
    }

    /* --- the model, as a ring ---
     * Dashed and grey, the same treatment the scatter gives its fitted line,
     * because it is the same kind of object: the thing the market is being
     * measured against rather than a result in itself. */
    svg.push('<polygon points="' + ring(mp) + '" fill="none" stroke="' + GUIDE +
      '" stroke-width="1.5" stroke-dasharray="5 4"/>');

    // --- the market ---
    var mpts = [];
    usable.forEach(function (m, k) {
      mpts.push(px(k, m.pct[team.abbr]).toFixed(1) + ',' + py(k, m.pct[team.abbr]).toFixed(1));
    });
    svg.push('<polygon points="' + mpts.join(' ') + '" fill="' + ORANGE +
      '" fill-opacity="0.16" stroke="' + ORANGE + '" stroke-width="2"/>');

    // --- spoke labels, outside the outermost ring ---
    usable.forEach(function (m, k) {
      var a = ang(k), ca = Math.cos(a), sa = Math.sin(a);
      var lx = cx + ca * (R + LEAD);
      var ly = cy + sa * (R + LEAD) + dyAt(ca, sa);
      svg.push(svgText(lx.toFixed(1), ly.toFixed(1), esc(labels[k]), {
        anchor: anchorAt(ca), size: FS, fill: INK_HI, weight: '700'
      }));
    });

    // --- the bubbles, last so they sit above both shapes ---
    usable.forEach(function (m, k) {
      var v = m.pct[team.abbr];
      var bx = px(k, v), by = py(k, v);
      var gap = v - mp;
      svg.push(
        '<g class="radar-pt" tabindex="0" role="listitem"' +
        ' aria-label="' + esc(m.label) + ': ' + esc(m.fmt(m.value[team.abbr])) +
        ', market rank ' + Math.round(v) + ', model rank ' + Math.round(mp) + ', ' +
        signed(gap, 0) + ' versus the model">' +
        '<circle cx="' + bx.toFixed(1) + '" cy="' + by.toFixed(1) + '" r="' + BUB +
        '" fill="' + ORANGE + '" stroke="#1a1a1a" stroke-width="2"/>' +
        svgText(bx.toFixed(1), (by + FS / 3).toFixed(1), String(Math.round(v)), {
          anchor: 'middle', size: FS, fill: '#fff', weight: '700'
        }) +
        '</g>');
    });

    host.innerHTML =
      '<svg class="radar-svg" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '"' +
      ' role="list" aria-label="' + esc(team.team) + ' market percentiles across ' + n +
      ' markets, against a model percentile of ' + Math.round(mp) + '.">' +
      svg.join('') + '</svg>';

    return { modelPct: mp, markets: usable };
  }

  /* The read-out: the same job the scatter's two lists do, for one team. Every
   * market it is priced in, sorted by how far the market sits from the model,
   * so the biggest disagreement is the first thing read. */
  function summary(team, out) {
    var mp = out.modelPct;
    var rows = out.markets.map(function (m) {
      return { m: m, v: m.pct[team.abbr], gap: m.pct[team.abbr] - mp };
    }).sort(function (a, b) { return b.gap - a.gap; });

    return '<table class="radar-table">' +
      '<caption>' + esc(team.team) + ' — market rank against a model rank of ' +
      Math.round(mp) + '</caption>' +
      '<thead><tr><th>Market</th><th>Price</th><th>Market</th><th>vs model</th></tr></thead>' +
      '<tbody>' + rows.map(function (r) {
        var cls = r.gap >= 0 ? 'is-under' : 'is-over';   // market above model = market likes it
        return '<tr><td>' + esc(r.m.label) + '</td>' +
          '<td class="radar-num">' + esc(r.m.fmt(r.m.value[team.abbr])) + '</td>' +
          '<td class="radar-num">' + Math.round(r.v) + '</td>' +
          '<td class="radar-num ' + cls + '">' + signed(r.gap, 0) + '</td></tr>';
      }).join('') + '</tbody></table>';
  }

  /* ---------- public ---------- */

  var cache = { team: null, markets: null, teams: null, scoreOf: null, width: null };

  function renderRadar(team, markets, teams, scoreOf) {
    var host = document.getElementById('radar-chart');
    var reads = document.getElementById('radar-reads');
    var note = document.getElementById('radar-note');
    if (!host) return;

    cache.team = team; cache.markets = markets;
    cache.teams = teams; cache.scoreOf = scoreOf;

    var out = draw(host, team, markets, teams, scoreOf);
    if (!out) {
      if (reads) reads.innerHTML = '';
      if (note) note.textContent = '';
      return;
    }
    cache.width = Math.floor(host.clientWidth || FALLBACK_W);

    if (reads) reads.innerHTML = summary(team, out);
    if (note) {
      note.innerHTML =
        'Every market at once for one team. The <strong>orange shape</strong> is where ' +
        'the market ranks ' + esc(team.short || team.team) + ' in each of the five, 0 to 100 ' +
        'across the field. The <strong>dashed ring</strong> is where the model ranks them — ' +
        'one number, so it is the same on every spoke, which is what makes each gap the ' +
        'market moving rather than the model. Orange outside the ring is a market higher on ' +
        'them than the model is.';
    }
  }

  var resizeTimer = null;
  window.addEventListener('resize', function () {
    if (!cache.team) return;
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      var host = document.getElementById('radar-chart');
      if (host && cache.width != null && Math.floor(host.clientWidth) === cache.width) return;
      renderRadar(cache.team, cache.markets, cache.teams, cache.scoreOf);
    }, 150);
  });

  window.renderTeamRadar = renderRadar;
})();
