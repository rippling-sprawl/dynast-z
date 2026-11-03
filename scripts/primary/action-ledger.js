/* Action Ledger — every Action Network bet, filtered, sorted and charted.
 *
 * Admin-only. The rows come from /api/action-ledger, which checks X-User-Id
 * against users.role, so requireAdmin() below is only the UI half of the gate.
 * Row shape (short keys) is documented in scripts/build_action_ledger.py.
 *
 * Three views over one filter state:
 *   all      every ticket whose event date is in the date range (default 60d),
 *            with a cumulative P/L chart over exactly the filtered set
 *   pending  ungraded tickets that end in the next 14 days
 *   futures  NFL tickets that end on or after Jan 1 2027
 * Type, league, team, result and search narrow all three; the date range only
 * applies to `all`, since the other two are defined by a date window of their own.
 *
 * Filters live in the query string so a view is linkable and survives a reload.
 *
 * With the type filter on Future, every view adds a Chances column (the win
 * chance as a percent: by default what the odds imply, but an admin can type
 * their own, which POSTs to /api/action-ledger and is kept server-side) and an
 * outlook table that buckets the open tickets by that chance.
 */
(function () {
  'use strict';

  if (!requireAdmin('/')) return;

  const DAY = 86400000;
  const PAGE = 300;
  const PENDING_DAYS = 14;
  // Action Network closes a ticket's day at 23:59:59 Pacific (ends_at is
  // 07:59:59Z), so "ends after Jan 1 2027" is measured from Pacific midnight,
  // and end dates are printed in Pacific time so a Jan 3 ticket reads Jan 3.
  const FUTURES_FROM = Date.parse('2027-01-01T08:00:00Z');
  const AN_TZ = 'America/Los_Angeles';

  const TYPE_ORDER = ['Spread', 'Moneyline', 'Total', 'Prop', 'Parlay', 'Teaser',
    'Future', 'Custom', 'Competition', 'Other'];
  // Outlook buckets for open futures, by win chance in percent: a ticket goes
  // in the first bucket whose floor it meets.
  const OUTLOOK = [
    { key: 'likely-win', label: 'Likely win', min: 70 },
    { key: 'lean-win', label: 'Lean win', min: 55 },
    { key: 'toss-up', label: 'Toss-up', min: 45 },
    { key: 'lean-loss', label: 'Lean loss', min: 30 },
    { key: 'likely-loss', label: 'Likely loss', min: 0 },
  ];
  const RESULT_LABEL = { win: 'Won', loss: 'Lost', push: 'Push', pending: 'Pending', void: 'Void' };

  const $ = id => document.getElementById(id);
  const els = {
    sub: $('al-sub'), stats: $('al-stats'), graph: $('al-graph'), buckets: $('al-buckets'),
    head: $('al-head'), body: $('al-body'), more: $('al-more'),
    range: $('f-range'), from: $('f-from'), to: $('f-to'), type: $('f-type'),
    league: $('f-league'), team: $('f-team'), result: $('f-result'), q: $('f-q'),
    reset: $('f-reset'), tabs: document.querySelectorAll('.al-tab'),
  };

  let ROWS = [];
  let META = {};
  let CHANCES = {};
  let shown = PAGE;
  let lastChart = null;
  const expanded = new Set();

  const DEFAULTS = { view: 'all', range: '60', from: '', to: '', type: '', league: '', team: '', result: '', q: '' };
  const state = Object.assign({}, DEFAULTS);
  const sorts = {
    all: { key: 'date', dir: 'desc' },
    pending: { key: 'ends', dir: 'asc' },
    futures: { key: 'ends', dir: 'asc' },
  };

  // ---- formatting ---------------------------------------------------------
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const ts = iso => (iso ? Date.parse(iso) : NaN);
  const eventTime = r => ts(r.st || r.pl);
  const fmtDate = (t, tz) => isNaN(t) ? '—' : new Date(t).toLocaleDateString('en-US',
    { month: 'short', day: 'numeric', year: 'numeric', timeZone: tz });
  const fmtOdds = o => o == null ? '—' : (o > 0 ? '+' + o : String(o));
  // Whole dollars stay whole; anything with cents shows both digits ($87.50).
  const money = v => {
    if (v == null) return '—';
    const cents = Math.round(Math.abs(v) * 100) % 100 !== 0;
    return '$' + Math.abs(v).toLocaleString('en-US',
      { minimumFractionDigits: cents ? 2 : 0, maximumFractionDigits: 2 });
  };
  const signed = v => v == null ? '—' : (v > 0 ? '+' : v < 0 ? '−' : '') + money(v);
  const league = lg => lg ? lg.toUpperCase().replace(/_/g, ' ') : '—';
  // American odds -> implied win chance, in percent (vig left in).
  const implied = o => o == null || o === 0 ? null : o > 0 ? 10000 / (o + 100) : -o * 100 / (-o + 100);
  const hasOwnChance = r => CHANCES[r.id] != null;
  const chanceOf = r => hasOwnChance(r) ? CHANCES[r.id] : implied(r.o);
  const pct = v => v == null ? '—' : (Math.round(v * 10) / 10) + '%';
  const showChances = () => state.type === 'Future';
  const isoDay = t => new Date(t - new Date(t).getTimezoneOffset() * 60000).toISOString().slice(0, 10);

  // ---- query string -------------------------------------------------------
  function readUrl() {
    const p = new URLSearchParams(location.search);
    for (const k of Object.keys(DEFAULTS)) if (p.has(k)) state[k] = p.get(k);
  }
  function writeUrl() {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(state)) if (v !== DEFAULTS[k]) p.set(k, v);
    const qs = p.toString();
    history.replaceState(null, '', location.pathname + (qs ? '?' + qs : ''));
  }

  // ---- filtering ----------------------------------------------------------
  function dateBounds() {
    const now = Date.now();
    const r = state.range;
    if (r === 'all') return [-Infinity, Infinity];
    if (r === 'ytd') return [new Date(new Date().getFullYear(), 0, 1).getTime(), Infinity];
    if (r === 'custom') {
      const lo = state.from ? new Date(state.from + 'T00:00').getTime() : -Infinity;
      const hi = state.to ? new Date(state.to + 'T23:59:59.999').getTime() : Infinity;
      return [lo, hi];
    }
    // "Last N days" runs to the present, not to the end of the slate: a
    // ticket on tonight's game is in it, next week's is not.
    const start = new Date(); start.setHours(0, 0, 0, 0);
    return [start.getTime() - (Number(r) - 1) * DAY, now];
  }

  function matchesShared(r) {
    if (state.type && r.t !== state.type) return false;
    if (state.league && r.lg !== state.league) return false;
    if (state.team) {
      const [lg, team] = state.team.split('|');
      if (r.lg !== lg || !(r.tm || []).includes(team)) return false;
    }
    if (state.result && r.r !== state.result) return false;
    if (state.q) {
      const hay = (r.d + ' ' + (r.m || '') + ' ' + (r.sub || '') + ' ' +
        (r.legs || []).map(l => l.d + ' ' + (l.m || '')).join(' ')).toLowerCase();
      if (!state.q.toLowerCase().split(/\s+/).every(w => hay.includes(w))) return false;
    }
    return true;
  }

  function inView(r, view) {
    if (view === 'pending') {
      const end = ts(r.en), now = Date.now();
      return r.r === 'pending' && end >= now && end <= now + PENDING_DAYS * DAY;
    }
    if (view === 'futures') return r.lg === 'nfl' && ts(r.en) >= FUTURES_FROM;
    const [lo, hi] = dateBounds();
    const t = eventTime(r);
    return t >= lo && t <= hi;
  }

  const filtered = () => ROWS.filter(r => inView(r, state.view) && matchesShared(r));

  // ---- filter options -----------------------------------------------------
  function fillOptions() {
    const types = new Set(ROWS.map(r => r.t));
    els.type.innerHTML = '<option value="">All types</option>' + TYPE_ORDER.filter(t => types.has(t))
      .map(t => `<option value="${t}">${t}</option>`).join('');

    const counts = {};
    ROWS.forEach(r => { if (r.lg) counts[r.lg] = (counts[r.lg] || 0) + 1; });
    els.league.innerHTML = '<option value="">All leagues</option>' + Object.keys(counts)
      .sort((a, b) => counts[b] - counts[a])
      .map(lg => `<option value="${esc(lg)}">${esc(league(lg))} (${counts[lg]})</option>`).join('');
    fillTeams();
  }

  // Team names repeat across leagues (Cardinals, Giants, Kings), so a team is
  // always a league + name pair, grouped by league when none is chosen.
  function fillTeams() {
    const byLeague = {};
    ROWS.forEach(r => {
      if (!r.tm || !r.lg || (state.league && r.lg !== state.league)) return;
      const set = byLeague[r.lg] = byLeague[r.lg] || new Set();
      r.tm.forEach(t => set.add(t));
    });
    const groups = Object.keys(byLeague).sort((a, b) => byLeague[b].size - byLeague[a].size);
    const opt = (lg, t) => `<option value="${esc(lg + '|' + t)}">${esc(t)}</option>`;
    els.team.innerHTML = '<option value="">All teams</option>' + (state.league
      ? [...(byLeague[state.league] || [])].sort().map(t => opt(state.league, t)).join('')
      : groups.map(lg => `<optgroup label="${esc(league(lg))}">` +
          [...byLeague[lg]].sort().map(t => opt(lg, t)).join('') + '</optgroup>').join(''));
    if (state.team && ![...els.team.options].some(o => o.value === state.team)) state.team = '';
    els.team.value = state.team;
  }

  function syncControls() {
    els.range.value = state.range;
    els.from.value = state.from;
    els.to.value = state.to;
    els.type.value = state.type;
    els.league.value = state.league;
    els.team.value = state.team;
    els.result.value = state.result;
    els.q.value = state.q;
    document.querySelectorAll('.al-date-only').forEach(el => {
      el.hidden = state.view !== 'all' || (el.classList.contains('al-custom') && state.range !== 'custom');
    });
    els.tabs.forEach(t => t.setAttribute('aria-selected', String(t.dataset.view === state.view)));
  }

  // ---- stats --------------------------------------------------------------
  function renderStats(rows) {
    const tile = (label, value, cls) =>
      `<div class="al-stat"><div class="al-stat-label">${label}</div><div class="al-stat-value ${cls || ''}">${value}</div></div>`;
    const open = rows.filter(r => r.r === 'pending');
    const risk = open.reduce((a, r) => a + (r.s || 0), 0);
    const toWin = open.reduce((a, r) => a + (r.w || 0), 0);
    if (state.view !== 'all') {
      els.stats.innerHTML = tile('Tickets', rows.length.toLocaleString()) +
        tile('Open', open.length.toLocaleString()) +
        tile('At risk', money(risk)) + tile('To win', money(toWin));
      return;
    }
    const settled = rows.filter(r => r.n != null && r.r !== 'pending');
    const w = settled.filter(r => r.r === 'win').length;
    const l = settled.filter(r => r.r === 'loss').length;
    const p = settled.length - w - l;
    const staked = settled.reduce((a, r) => a + (r.s || 0), 0);
    const net = settled.reduce((a, r) => a + r.n, 0);
    const roi = staked ? net / staked * 100 : null;
    const tone = v => v > 0 ? 'pos' : v < 0 ? 'neg' : '';
    els.stats.innerHTML = tile('Tickets', rows.length.toLocaleString()) +
      tile('Record', `${w}-${l}${p ? '-' + p : ''}`) +
      tile('Staked', money(staked)) +
      tile('Net', signed(net), tone(net)) +
      tile('ROI', roi == null ? '—' : (roi > 0 ? '+' : '') + roi.toFixed(1) + '%', tone(roi)) +
      tile('Open', `${open.length} · ${money(risk)}`);
  }

  // ---- chart --------------------------------------------------------------
  // Cumulative net over the filtered, settled tickets, one point per event
  // day. One series, so no legend: the title names it. Green above zero, red
  // below, split by clip at the zero line as on /bets/history. Colours come
  // from CSS classes rather than attributes, so a theme switch repaints it.
  function renderChart(rows) {
    if (state.view !== 'all') { els.graph.hidden = true; lastChart = null; return; }
    els.graph.hidden = false;
    const byDay = new Map();
    rows.forEach(r => {
      if (r.n == null || r.r === 'pending') return;
      const t = eventTime(r);
      if (isNaN(t)) return;
      const d = isoDay(t);
      const e = byDay.get(d) || { net: 0, n: 0 };
      e.net += r.n; e.n += 1;
      byDay.set(d, e);
    });
    const days = [...byDay.keys()].sort();
    if (days.length < 2) {
      els.graph.innerHTML = '<div class="pl-graph-empty">Not enough settled bets in this filter to chart.</div>';
      lastChart = null;
      return;
    }
    let run = 0;
    const pts = days.map(d => {
      const e = byDay.get(d);
      run += e.net;
      return { t: new Date(d + 'T12:00').getTime(), day: d, net: e.net, n: e.n, cum: run };
    });
    lastChart = pts;
    drawChart(pts);
  }

  function niceTicks(min, max, count) {
    const span = max - min || 1;
    const raw = span / count;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= raw);
    const out = [];
    for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push(Math.round(v * 100) / 100);
    return out;
  }

  function drawChart(pts) {
    const W = Math.max(300, Math.floor(els.graph.clientWidth - 24));
    const H = 240;
    const mL = 62, mR = 14, mT = 30, mB = 28;
    const x0 = mL, x1 = W - mR, yTop = mT, yBot = H - mB;
    let min = Math.min(0, ...pts.map(p => p.cum));
    let max = Math.max(0, ...pts.map(p => p.cum));
    if (min === max) { min -= 1; max += 1; }
    const pad = (max - min) * 0.06;
    min -= pad; max += pad;
    const tLo = pts[0].t, tHi = pts[pts.length - 1].t;
    const xAt = t => x0 + (t - tLo) / (tHi - tLo) * (x1 - x0);
    const yAt = v => yTop + (1 - (v - min) / (max - min)) * (yBot - yTop);
    const zeroY = yAt(0).toFixed(1);

    const line = pts.map((p, i) => (i ? 'L' : 'M') + xAt(p.t).toFixed(1) + ',' + yAt(p.cum).toFixed(1)).join('');
    const area = `M${xAt(tLo).toFixed(1)},${zeroY}` + line.replace(/^M/, 'L') + `L${xAt(tHi).toFixed(1)},${zeroY}Z`;
    const ticks = niceTicks(min, max, 4);
    const short = v => (v < 0 ? '−' : '') + '$' + (Math.abs(v) >= 1000
      ? (Math.abs(v) / 1000).toFixed(Math.abs(v) >= 10000 ? 0 : 1) + 'k' : Math.round(Math.abs(v)));
    const xLabels = [0, 0.5, 1].map(f => {
      const t = tLo + (tHi - tLo) * f;
      const anchor = f === 0 ? 'start' : f === 1 ? 'end' : 'middle';
      return `<text class="al-ax" x="${xAt(t).toFixed(1)}" y="${yBot + 18}" text-anchor="${anchor}">${fmtDate(t)}</text>`;
    }).join('');
    const total = pts[pts.length - 1].cum;

    els.graph.innerHTML =
      `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Cumulative net profit for the filtered bets, ${signed(total)} over ${pts.length} days">` +
        '<defs>' +
          `<clipPath id="al-up"><rect x="${x0}" y="0" width="${x1 - x0}" height="${zeroY}"/></clipPath>` +
          `<clipPath id="al-down"><rect x="${x0}" y="${zeroY}" width="${x1 - x0}" height="${H}"/></clipPath>` +
        '</defs>' +
        `<text class="al-title" x="${x0}" y="16">Cumulative net · <tspan class="${total >= 0 ? 'al-pos' : 'al-neg'}">${signed(total)}</tspan></text>` +
        ticks.map(v => `<line class="al-grid" x1="${x0}" x2="${x1}" y1="${yAt(v).toFixed(1)}" y2="${yAt(v).toFixed(1)}"/>` +
          `<text class="al-ax" x="${x0 - 8}" y="${(yAt(v) + 3.5).toFixed(1)}" text-anchor="end">${short(v)}</text>`).join('') +
        `<line class="al-zero" x1="${x0}" x2="${x1}" y1="${zeroY}" y2="${zeroY}"/>` +
        `<path class="al-area-up" d="${area}" clip-path="url(#al-up)"/>` +
        `<path class="al-area-down" d="${area}" clip-path="url(#al-down)"/>` +
        `<path class="al-line-up" d="${line}" clip-path="url(#al-up)"/>` +
        `<path class="al-line-down" d="${line}" clip-path="url(#al-down)"/>` +
        xLabels +
        `<line class="al-cross" id="al-cross" x1="0" x2="0" y1="${yTop}" y2="${yBot}" visibility="hidden"/>` +
        `<circle class="al-dot" id="al-dot" r="4.5" visibility="hidden"/>` +
        `<rect class="al-hit" x="${x0}" y="${yTop}" width="${x1 - x0}" height="${yBot - yTop}"/>` +
      '</svg><div class="al-tip" id="al-tip" hidden></div>';

    const svg = els.graph.querySelector('svg');
    const hit = svg.querySelector('.al-hit');
    const cross = $('al-cross'), dot = $('al-dot'), tip = $('al-tip');
    const hide = () => { cross.setAttribute('visibility', 'hidden'); dot.setAttribute('visibility', 'hidden'); tip.hidden = true; };
    const move = e => {
      const box = svg.getBoundingClientRect();
      const x = (e.clientX - box.left) * (W / box.width);
      const t = tLo + (x - x0) / (x1 - x0) * (tHi - tLo);
      let best = 0;
      for (let i = 1; i < pts.length; i++) if (Math.abs(pts[i].t - t) < Math.abs(pts[best].t - t)) best = i;
      const p = pts[best];
      const px = xAt(p.t), py = yAt(p.cum);
      cross.setAttribute('x1', px); cross.setAttribute('x2', px);
      cross.setAttribute('visibility', 'visible');
      dot.setAttribute('cx', px); dot.setAttribute('cy', py);
      dot.setAttribute('class', 'al-dot ' + (p.cum >= 0 ? 'al-dot-up' : 'al-dot-down'));
      dot.setAttribute('visibility', 'visible');
      tip.innerHTML = `<div class="al-tip-date">${fmtDate(p.t)}</div>` +
        `<div><span class="al-tip-k">Cumulative</span> <b class="${p.cum >= 0 ? 'al-pos' : 'al-neg'}">${signed(p.cum)}</b></div>` +
        `<div><span class="al-tip-k">That day</span> ${signed(p.net)} · ${p.n} bet${p.n === 1 ? '' : 's'}</div>`;
      tip.hidden = false;
      const scale = box.width / W;
      const left = px * scale + 12;
      tip.style.left = Math.min(left, box.width - tip.offsetWidth - 4) + 'px';
      tip.style.top = Math.max(4, py * scale - tip.offsetHeight - 10) + 'px';
    };
    hit.addEventListener('pointermove', move);
    hit.addEventListener('pointerdown', move);
    hit.addEventListener('pointerleave', hide);
  }

  // ---- outlook ------------------------------------------------------------
  // The open futures in the filter, bucketed by win chance. Expected is the
  // chance-weighted net: p * to-win - (1 - p) * stake.
  function renderBuckets(rows) {
    if (!showChances()) { els.buckets.hidden = true; return; }
    els.buckets.hidden = false;
    const open = rows.filter(r => r.r === 'pending');
    const agg = () => ({ n: 0, s: 0, w: 0, ev: 0 });
    const by = Object.fromEntries(OUTLOOK.map(b => [b.key, agg()]));
    const total = agg(), unrated = agg();
    open.forEach(r => {
      const c = chanceOf(r);
      const a = c == null ? unrated : by[OUTLOOK.find(b => c >= b.min).key];
      const p = (c || 0) / 100, s = r.s || 0, w = r.w || 0;
      for (const t of c == null ? [a] : [a, total]) {
        t.n += 1; t.s += s; t.w += w;
        if (c != null) t.ev += p * w - (1 - p) * s;
      }
    });
    // At the odds' own chances, expected is zero by construction; round off
    // the float dust so it reads $0, not +$0 or −$0.01.
    open.length && [total, unrated, ...Object.values(by)].forEach(a => { a.ev = Math.round(a.ev) || 0; });
    const tone = v => v > 0 ? 'al-pos' : v < 0 ? 'al-neg' : '';
    const range = (b, i) => i === 0 ? `${b.min}%+` : `${b.min}–${OUTLOOK[i - 1].min}%`;
    const row = (label, hint, a, cls) => `<tr class="${cls || ''}"><th scope="row">${label}` +
      (hint ? ` <span class="al-meta al-inline">${hint}</span>` : '') + '</th>' +
      `<td class="al-r al-num">${a.n.toLocaleString()}</td><td class="al-r al-num">${money(a.s)}</td>` +
      `<td class="al-r al-num">${money(a.w)}</td><td class="al-r al-num ${a.n ? tone(a.ev) : ''}">${a.n ? signed(a.ev) : '—'}</td></tr>`;
    els.buckets.innerHTML =
      '<table class="al-table al-outlook"><caption class="al-outlook-cap">Open futures by Chances</caption>' +
      '<thead><tr><th scope="col">Outlook</th><th scope="col" class="al-r">Tickets</th><th scope="col" class="al-r">At risk</th>' +
      '<th scope="col" class="al-r">To win</th><th scope="col" class="al-r">Expected</th></tr></thead><tbody>' +
      OUTLOOK.map((b, i) => row(`<span class="al-dot-k al-ok-${b.key}"></span>${b.label}`, range(b, i), by[b.key])).join('') +
      (unrated.n ? row('No chance', 'no odds', unrated) : '') +
      row('Total', '', total, 'al-outlook-total') + '</tbody></table>';
  }

  // ---- table --------------------------------------------------------------
  const COLUMNS = {
    all: ['date', 'bet', 'type', 'league', 'odds', 'stake', 'net', 'result'],
    pending: ['ends', 'bet', 'type', 'league', 'odds', 'stake', 'towin'],
    futures: ['ends', 'bet', 'type', 'odds', 'stake', 'towin', 'result'],
  };
  const COL = {
    date: { label: 'Date', get: r => eventTime(r), num: true, dir: 'desc' },
    ends: { label: 'Ends', get: r => ts(r.en), num: true, dir: 'asc' },
    bet: { label: 'Bet', get: r => r.d.toLowerCase() },
    type: { label: 'Type', get: r => r.t },
    league: { label: 'League', get: r => r.lg || null },
    odds: { label: 'Odds', get: r => r.o, num: true, dir: 'desc', right: true },
    chance: { label: 'Chances', get: chanceOf, num: true, dir: 'desc', right: true },
    stake: { label: 'Stake', get: r => r.s, num: true, dir: 'desc', right: true },
    towin: { label: 'To win', get: r => r.w, num: true, dir: 'desc', right: true },
    net: { label: 'Net', get: r => r.n, num: true, dir: 'desc', right: true },
    result: { label: 'Result', get: r => r.r },
  };

  // The Chances column rides in after Odds, and only for futures.
  function columns() {
    const cols = COLUMNS[state.view].slice();
    if (showChances()) cols.splice(cols.indexOf('odds') + 1, 0, 'chance');
    return cols;
  }

  function renderHead() {
    const s = sorts[state.view];
    els.head.innerHTML = '<tr>' + columns().map(k => {
      const c = COL[k];
      const active = s.key === k;
      return `<th class="${c.right ? 'al-r' : ''}" aria-sort="${active ? (s.dir === 'asc' ? 'ascending' : 'descending') : 'none'}">` +
        `<button type="button" class="al-sort" data-sort="${k}">${c.label}${active ? Sort.arrow(s.dir) : ''}</button></th>`;
    }).join('') + '</tr>';
  }

  function cell(k, r) {
    switch (k) {
      case 'date': return `<td class="al-nowrap">${fmtDate(eventTime(r))}</td>`;
      case 'ends': return `<td class="al-nowrap">${fmtDate(ts(r.en), AN_TZ)}</td>`;
      case 'bet': {
        const legs = r.legs && r.legs.length;
        const sub = [r.sub, r.m].filter(Boolean).map(esc).join(' · ');
        return `<td class="al-bet">` +
          (legs ? `<button type="button" class="al-legs-btn" data-id="${r.id}" aria-expanded="${expanded.has(r.id)}">${expanded.has(r.id) ? '▾' : '▸'}</button>` : '') +
          `<span class="al-desc">${esc(r.d)}</span>` +
          (sub ? `<span class="al-meta">${sub}</span>` : '') + '</td>';
      }
      case 'type': return `<td><span class="al-chip">${esc(r.t)}</span></td>`;
      case 'league': return `<td>${esc(league(r.lg))}</td>`;
      case 'odds': return `<td class="al-r al-num">${fmtOdds(r.o)}</td>`;
      case 'chance': {
        const v = chanceOf(r);
        // Only an open ticket's chance is worth setting; a graded one shows
        // what it was.
        if (r.r !== 'pending') return `<td class="al-r al-num al-chance-done">${pct(v)}</td>`;
        const own = hasOwnChance(r);
        return `<td class="al-r al-num al-chance-cell${own ? ' al-chance-own' : ''}">` +
          `<button type="button" class="al-chance-reset" data-id="${r.id}" title="Back to the odds' ${pct(implied(r.o))}" aria-label="Reset to the odds' chance"${own ? '' : ' hidden'}>↺</button>` +
          `<input class="al-chance" type="number" inputmode="decimal" min="0" max="100" step="0.1" data-id="${r.id}" ` +
          `value="${v == null ? '' : Math.round(v * 10) / 10}" aria-label="Win chance for ${esc(r.d)}"><span class="al-pct">%</span></td>`;
      }
      case 'stake': return `<td class="al-r al-num">${money(r.s)}</td>`;
      case 'towin': return `<td class="al-r al-num">${money(r.w)}</td>`;
      case 'net': return `<td class="al-r al-num ${r.n > 0 ? 'al-pos' : r.n < 0 ? 'al-neg' : ''}">${r.r === 'pending' ? '—' : signed(r.n)}</td>`;
      case 'result': return `<td><span class="al-res al-res-${esc(r.r)}">${RESULT_LABEL[r.r] || esc(r.r)}</span></td>`;
    }
    return '<td></td>';
  }

  function renderBody(rows) {
    const cols = columns();
    const s = sorts[state.view];
    const c = COL[s.key];
    const sorted = Sort.sortBy(rows, s.dir, { numeric: !!c.num, accessor: c.get });
    if (!sorted.length) {
      els.body.innerHTML = `<tr><td class="al-empty" colspan="${cols.length}">No bets match these filters.</td></tr>`;
      els.more.innerHTML = '';
      return;
    }
    els.body.innerHTML = sorted.slice(0, shown).map(r => {
      let html = `<tr class="al-row al-row-${esc(r.r)}">` + cols.map(k => cell(k, r)).join('') + '</tr>';
      if (r.legs && expanded.has(r.id)) {
        html += `<tr class="al-legs-row"><td colspan="${cols.length}"><ul class="al-legs">` +
          r.legs.map(l => `<li><span class="al-res al-res-${esc(l.r)}">${RESULT_LABEL[l.r] || esc(l.r)}</span>` +
            `<span class="al-desc">${esc(l.d)}</span>${l.m ? `<span class="al-meta">${esc(l.m)}</span>` : ''}</li>`).join('') +
          '</ul></td></tr>';
      }
      return html;
    }).join('');
    els.more.innerHTML = sorted.length > shown
      ? `<button type="button" class="al-reset" id="al-more-btn">Show ${Math.min(PAGE, sorted.length - shown)} more of ${(sorted.length - shown).toLocaleString()}</button>`
      : '';
  }

  // ---- render -------------------------------------------------------------
  let lastRows = [];
  function render() {
    syncControls();
    writeUrl();
    lastRows = filtered();
    // The Chances sort has nothing to sort on once the column is gone.
    if (!columns().includes(sorts[state.view].key)) sorts[state.view] = { key: COLUMNS[state.view][0], dir: COL[COLUMNS[state.view][0]].dir };
    renderStats(lastRows);
    renderChart(lastRows);
    renderBuckets(lastRows);
    renderHead();
    renderBody(lastRows);
  }

  function update(patch) {
    Object.assign(state, patch);
    shown = PAGE;
    render();
  }

  // ---- wiring -------------------------------------------------------------
  els.tabs.forEach(t => t.addEventListener('click', () => update({ view: t.dataset.view })));
  els.range.addEventListener('change', () => {
    const patch = { range: els.range.value };
    // Seed a custom range with the window it replaces, rather than empty.
    if (patch.range === 'custom' && !state.from && !state.to) {
      const [lo, hi] = dateBounds();
      if (isFinite(lo)) patch.from = isoDay(lo);
      patch.to = isoDay(isFinite(hi) ? hi : Date.now());
    }
    update(patch);
  });
  els.from.addEventListener('change', () => update({ from: els.from.value }));
  els.to.addEventListener('change', () => update({ to: els.to.value }));
  els.type.addEventListener('change', () => update({ type: els.type.value }));
  els.league.addEventListener('change', () => { state.league = els.league.value; fillTeams(); update({}); });
  els.team.addEventListener('change', () => update({ team: els.team.value }));
  els.result.addEventListener('change', () => update({ result: els.result.value }));
  let qTimer;
  els.q.addEventListener('input', () => {
    clearTimeout(qTimer);
    qTimer = setTimeout(() => update({ q: els.q.value.trim() }), 150);
  });
  els.reset.addEventListener('click', () => {
    Object.assign(state, DEFAULTS, { view: state.view });
    fillTeams();
    update({});
  });
  els.head.addEventListener('click', e => {
    const b = e.target.closest('[data-sort]');
    if (!b) return;
    const k = b.dataset.sort;
    sorts[state.view] = Sort.toggle(sorts[state.view], k, COL[k].dir || 'asc');
    renderHead();
    renderBody(lastRows);
  });
  els.body.addEventListener('click', e => {
    const b = e.target.closest('.al-legs-btn');
    if (!b) return;
    const id = Number(b.dataset.id);
    expanded.has(id) ? expanded.delete(id) : expanded.add(id);
    renderBody(lastRows);
  });
  // A chance edit saves on change and repaints only the outlook and its own
  // cell, not the table, so tabbing down the column keeps focus.
  async function saveChance(id, chance, input) {
    const key = String(id);
    const before = CHANCES[key];
    if (chance == null) delete CHANCES[key]; else CHANCES[key] = chance;
    const paint = () => {
      const r = ROWS.find(x => x.id === id);
      const td = input.closest('td');
      td.classList.toggle('al-chance-own', hasOwnChance(r));
      td.querySelector('.al-chance-reset').hidden = !hasOwnChance(r);
      const v = chanceOf(r);
      input.value = v == null ? '' : Math.round(v * 10) / 10;
      renderBuckets(lastRows);
    };
    paint();
    input.classList.remove('al-chance-err');
    try {
      const res = await fetch('/api/action-ledger', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-User-Id': getUser().user_id },
        body: JSON.stringify({ id, chance }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    } catch (err) {
      if (before == null) delete CHANCES[key]; else CHANCES[key] = before;
      paint();
      input.classList.add('al-chance-err');
      input.title = `Not saved: ${err.message}`;
    }
  }
  els.body.addEventListener('change', e => {
    const input = e.target.closest('.al-chance');
    if (!input) return;
    const raw = input.value.trim();
    const v = raw === '' ? null : Math.min(100, Math.max(0, Math.round(Number(raw) * 10) / 10));
    if (raw !== '' && isNaN(v)) return;
    saveChance(Number(input.dataset.id), v, input);
  });
  els.body.addEventListener('click', e => {
    const b = e.target.closest('.al-chance-reset');
    if (!b) return;
    saveChance(Number(b.dataset.id), null, b.closest('td').querySelector('.al-chance'));
  });
  els.more.addEventListener('click', e => {
    if (!e.target.closest('#al-more-btn')) return;
    shown += PAGE;
    renderBody(lastRows);
  });
  let rTimer;
  window.addEventListener('resize', () => {
    clearTimeout(rTimer);
    rTimer = setTimeout(() => { if (lastChart) drawChart(lastChart); }, 120);
  });

  // ---- load ---------------------------------------------------------------
  async function load() {
    const user = getUser();
    try {
      const res = await fetch('/api/action-ledger', { headers: { 'X-User-Id': user.user_id } });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      ROWS = data.rows || [];
      CHANCES = data.chances || {};
      META = data;
    } catch (err) {
      els.sub.textContent = `Couldn't load the ledger: ${err.message}`;
      return;
    }
    const fetched = META.fetched_at ? fmtDate(ts(META.fetched_at)) : 'unknown';
    els.sub.textContent = `${ROWS.length.toLocaleString()} tickets from Action Network · exported ${fetched}`;
    readUrl();
    fillOptions();
    render();
  }

  load();
})();
