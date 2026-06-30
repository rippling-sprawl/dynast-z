// Bets history renderer — filters, recent-performance table, cumulative P/L
// chart, and the filtered bet list. Extracted from views/bets/history.html so
// both that page and the admin /bets/audit view share one implementation.
//
// renderBetsHistory(els, all):
//   els  — { list, sub, perf, leagueChips, rangeChips, from, to, graph }
//          (the same element ids used on the history page)
//   all  — array of bets, newest first (e.g. allBetsWithSeedNewestFirst())

function renderBetsHistory(els, all) {
  const ALL = all || [];

  if (!ALL.length) {
    els.list.innerHTML = '<div class="bets-empty">No bets yet. <a href="/bets/place" style="color:#58a6ff">Track your first →</a></div>';
    els.perf.style.display = 'none';
    const filters = document.querySelector('.bets-filters');
    if (filters) filters.style.display = 'none';
    els.graph.style.display = 'none';
    if (els.sub) els.sub.textContent = 'All your saved picks, pending and resolved.';
    return;
  }

  // ---- filter state -------------------------------------------------------
  const LEAGUES = ['NFL', 'NBA', 'Other'];
  const RANGES = [
    { key: 'all', label: 'All' },
    { key: '30', label: 'Last 30' },
    { key: '7', label: 'Last 7' },
    { key: 'yesterday', label: 'Yesterday' },
    { key: 'today', label: 'Today' },
  ];
  const state = { leagues: new Set(), range: 'all', from: '', to: '' };

  // ---- date helpers (anchored to today's real local date) -----------------
  function startOfToday() {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    return d;
  }
  function placedTime(b) {
    const t = Date.parse(b.placed_at || '');
    return isNaN(t) ? null : t;
  }
  // Returns [start, end) in epoch ms, or null bound for open-ended.
  function rangeBounds() {
    const today0 = startOfToday().getTime();
    const DAY = 86400000;
    switch (state.range) {
      case 'today': return [today0, Infinity];
      case 'yesterday': return [today0 - DAY, today0];
      case '7': return [today0 - 7 * DAY, Infinity];
      case '30': return [today0 - 30 * DAY, Infinity];
      case 'custom': {
        const lo = state.from ? Date.parse(state.from + 'T00:00:00') : -Infinity;
        const hi = state.to ? Date.parse(state.to + 'T00:00:00') + DAY : Infinity;
        return [lo, hi];
      }
      default: return [-Infinity, Infinity]; // all
    }
  }

  function matchesLeague(b) {
    return state.leagues.size === 0 || state.leagues.has(b.league);
  }
  function inWindow(b, lo, hi) {
    const t = placedTime(b);
    if (t === null) return false;
    return t >= lo && t < hi;
  }

  function getFiltered() {
    const [lo, hi] = rangeBounds();
    return ALL.filter(b => matchesLeague(b) && inWindow(b, lo, hi));
  }

  // ---- stats --------------------------------------------------------------
  function statsFor(bets) {
    let net = 0, staked = 0, wins = 0, losses = 0, pushes = 0;
    for (const b of bets) {
      const pl = profitLoss(b);
      if (pl === null) continue; // pending — not settled
      net += pl;
      staked += Number(b.stake) || 0;
      if (b.status === 'win') wins++;
      else if (b.status === 'loss') losses++;
      else pushes++; // push / void
    }
    const roi = staked ? (net / staked) * 100 : 0;
    return { net, staked, wins, losses, pushes, roi, settled: wins + losses + pushes };
  }

  function plClass(n) { return n > 0 ? 'pos' : (n < 0 ? 'neg' : ''); }
  function signMoney(n) { return (n > 0 ? '+' : '') + fmtMoney(n); }

  // ---- recent performance cards (fixed windows, respect league filter) ----
  function leagueFilteredAll() {
    return ALL.filter(matchesLeague);
  }
  function windowedFromToday(days) {
    // days=0 → today; days=1 → yesterday (single prior day); else last N days
    const today0 = startOfToday().getTime();
    const DAY = 86400000;
    if (days === 'yesterday') return [today0 - DAY, today0];
    if (days === 'today') return [today0, Infinity];
    return [today0 - days * DAY, Infinity];
  }
  function renderPerfTable() {
    const base = leagueFilteredAll();
    const rows = [
      { label: 'Today', win: windowedFromToday('today') },
      { label: 'Yesterday', win: windowedFromToday('yesterday') },
      { label: 'Last 7', win: windowedFromToday(7) },
      { label: 'Last 30', win: windowedFromToday(30) },
    ];
    const body = rows.map(r => {
      const [lo, hi] = r.win;
      const s = statsFor(base.filter(b => inWindow(b, lo, hi)));
      const roiStr = (s.net > 0 ? '+' : '') + s.roi.toFixed(1) + '%';
      return '<tr>' +
          '<th scope="row">' + r.label + '</th>' +
          '<td class="perf-pl ' + plClass(s.net) + '">' + signMoney(s.net) + '</td>' +
          '<td class="perf-rec">' + s.wins + '-' + s.losses + '-' + s.pushes + '</td>' +
          '<td class="perf-roi ' + plClass(s.net) + '">' + roiStr + '</td>' +
        '</tr>';
    }).join('');
    els.perf.innerHTML =
      '<table class="perf-table">' +
        '<thead><tr><th scope="col">Period</th><th scope="col">P/L</th>' +
          '<th scope="col">Record</th><th scope="col">ROI</th></tr></thead>' +
        '<tbody>' + body + '</tbody>' +
      '</table>';
  }

  // ---- cumulative P/L graph (vanilla SVG, split green/red at zero) ---------
  function svgText(x, y, s, o) {
    o = o || {};
    return '<text x="' + x + '" y="' + y + '"' +
      ' fill="' + (o.fill || '#8b949e') + '" font-size="' + (o.size || 10) + '"' +
      (o.weight ? ' font-weight="' + o.weight + '"' : '') +
      ' text-anchor="' + (o.anchor || 'start') + '"' +
      (o.transform ? ' transform="' + o.transform + '"' : '') +
      '>' + s + '</text>';
  }
  function renderGraph(bets) {
    const settled = bets
      .filter(b => profitLoss(b) !== null)
      .slice()
      .sort((a, b) => (placedTime(a) || 0) - (placedTime(b) || 0));

    if (settled.length < 2) {
      els.graph.innerHTML = '<div class="pl-graph-empty">Not enough settled bets in range to chart.</div>';
      return;
    }

    // cumulative running P/L, seeded with a 0 starting point
    const ys = [0];
    let run = 0;
    for (const b of settled) { run += profitLoss(b); ys.push(run); }

    let min = Math.min(...ys), max = Math.max(...ys);
    if (min === max) { min -= 1; max += 1; }
    const span = max - min;

    // measured pixel geometry (width = container, height fixed) → crisp, undistorted text
    const W = Math.max(300, Math.floor(els.graph.clientWidth - 24));
    const H = 220;
    const mL = 54, mR = 16, mT = 28, mB = 40;
    const x0 = mL, x1 = W - mR, yTop = mT, yBot = H - mB;
    const plotW = x1 - x0, plotH = yBot - yTop;

    const xAt = i => x0 + (i / (ys.length - 1)) * plotW;
    const yAt = v => yTop + (1 - (v - min) / span) * plotH;
    const zeroY = yAt(0);

    const linePts = ys.map((v, i) => xAt(i).toFixed(1) + ',' + yAt(v).toFixed(1)).join(' ');
    // area closed along the zero baseline; split-clipped green (above) / red (below)
    const areaPts = xAt(0).toFixed(1) + ',' + zeroY.toFixed(1) + ' ' + linePts + ' ' +
      xAt(ys.length - 1).toFixed(1) + ',' + zeroY.toFixed(1);

    const sMoney = v => (v > 0 ? '+' : (v < 0 ? '-' : '')) + '$' + Math.round(Math.abs(v));
    const firstDate = fmtDate(settled[0].placed_at);
    const lastDate = fmtDate(settled[settled.length - 1].placed_at);
    const aboveH = Math.max(0, zeroY - yTop).toFixed(1);
    const belowH = Math.max(0, yBot - zeroY).toFixed(1);
    const midY = ((yTop + yBot) / 2).toFixed(1);

    els.graph.innerHTML =
      '<svg width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Cumulative profit and loss over time">' +
        '<defs>' +
          '<clipPath id="plAbove"><rect x="' + x0 + '" y="' + yTop + '" width="' + plotW + '" height="' + aboveH + '"/></clipPath>' +
          '<clipPath id="plBelow"><rect x="' + x0 + '" y="' + zeroY.toFixed(1) + '" width="' + plotW + '" height="' + belowH + '"/></clipPath>' +
        '</defs>' +
        svgText(W / 2, 16, 'Cumulative Profit / Loss', { fill: '#f0f6fc', size: 12, weight: 700, anchor: 'middle' }) +
        // axes
        '<line x1="' + x0 + '" y1="' + yTop + '" x2="' + x0 + '" y2="' + yBot + '" stroke="#30363d" stroke-width="1"/>' +
        '<line x1="' + x0 + '" y1="' + yBot + '" x2="' + x1 + '" y2="' + yBot + '" stroke="#30363d" stroke-width="1"/>' +
        // zero baseline
        '<line x1="' + x0 + '" y1="' + zeroY.toFixed(1) + '" x2="' + x1 + '" y2="' + zeroY.toFixed(1) + '" stroke="#484f58" stroke-width="1" stroke-dasharray="3 3"/>' +
        // split area fills
        '<polygon points="' + areaPts + '" fill="rgba(46,160,67,0.13)" clip-path="url(#plAbove)"/>' +
        '<polygon points="' + areaPts + '" fill="rgba(248,81,73,0.13)" clip-path="url(#plBelow)"/>' +
        // split line: green above zero, red below
        '<polyline points="' + linePts + '" fill="none" stroke="#2ea043" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" clip-path="url(#plAbove)"/>' +
        '<polyline points="' + linePts + '" fill="none" stroke="#f85149" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" clip-path="url(#plBelow)"/>' +
        // y-axis value labels (max / 0 / min)
        svgText(x0 - 7, yAt(max) + 3, sMoney(max), { anchor: 'end' }) +
        svgText(x0 - 7, zeroY + 3, '$0', { anchor: 'end' }) +
        svgText(x0 - 7, yAt(min) + 3, sMoney(min), { anchor: 'end' }) +
        // y-axis title
        svgText(14, midY, 'P / L ($)', { anchor: 'middle', transform: 'rotate(-90 14 ' + midY + ')' }) +
        // x-axis date labels
        svgText(x0, yBot + 15, firstDate, { anchor: 'start' }) +
        svgText(x1, yBot + 15, lastDate, { anchor: 'end' }) +
        // x-axis title
        svgText((x0 + x1) / 2, H - 6, 'Date placed', { anchor: 'middle' }) +
      '</svg>';
  }

  // ---- list + sub line ----------------------------------------------------
  function renderList(bets) {
    if (!bets.length) {
      els.list.innerHTML = '<div class="bets-empty">No bets match these filters.</div>';
    } else {
      els.list.innerHTML = bets.map(renderBetTile).join('');
    }
  }
  function renderSub(bets) {
    if (!els.sub) return;
    const s = statsFor(bets);
    const color = s.net > 0 ? '#2ea043' : (s.net < 0 ? '#f85149' : '#8b949e');
    els.sub.innerHTML = bets.length + ' bet' + (bets.length === 1 ? '' : 's') +
      ' &middot; ' + s.settled + ' settled &middot; Net P/L: ' +
      '<strong style="color:' + color + '">' + signMoney(s.net) + '</strong>';
  }

  // ---- render orchestration -----------------------------------------------
  function syncChips() {
    els.leagueChips.querySelectorAll('.filter-chip').forEach(chip => {
      const lg = chip.dataset.league;
      const on = lg === '' ? state.leagues.size === 0 : state.leagues.has(lg);
      chip.classList.toggle('active', on);
    });
    els.rangeChips.querySelectorAll('.filter-chip').forEach(chip => {
      chip.classList.toggle('active', chip.dataset.range === state.range);
    });
  }
  let lastFiltered = [];
  function rerender() {
    syncChips();
    const filtered = getFiltered();
    lastFiltered = filtered;
    renderPerfTable();
    renderGraph(filtered);
    renderList(filtered);
    renderSub(filtered);
  }
  // Graph is measured in pixels, so re-draw it when the viewport resizes.
  let resizeTimer = null;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => renderGraph(lastFiltered), 150);
  });

  // ---- build filter UI ----------------------------------------------------
  function chip(label, dataAttr, val) {
    return '<button type="button" class="filter-chip" data-' + dataAttr + '="' + val + '">' + label + '</button>';
  }
  els.leagueChips.innerHTML =
    chip('All', 'league', '') + LEAGUES.map(l => chip(l, 'league', l)).join('');
  els.rangeChips.innerHTML =
    RANGES.map(r => chip(r.label, 'range', r.key)).join('');

  els.leagueChips.addEventListener('click', e => {
    const btn = e.target.closest('.filter-chip');
    if (!btn) return;
    const lg = btn.dataset.league;
    if (lg === '') state.leagues.clear();
    else {
      if (state.leagues.has(lg)) state.leagues.delete(lg);
      else state.leagues.add(lg);
    }
    rerender();
  });
  els.rangeChips.addEventListener('click', e => {
    const btn = e.target.closest('.filter-chip');
    if (!btn) return;
    state.range = btn.dataset.range;
    state.from = ''; state.to = '';
    els.from.value = ''; els.to.value = '';
    rerender();
  });
  function onCustom() {
    state.from = els.from.value;
    state.to = els.to.value;
    state.range = (state.from || state.to) ? 'custom' : 'all';
    rerender();
  }
  els.from.addEventListener('change', onCustom);
  els.to.addEventListener('change', onCustom);

  rerender();
}
