// Shared utilities for golf tournament views
// Tournament context is parsed from URL: /golf/:year/:tournament/:page

const TOURNAMENT_CONTEXT = (function() {
  const parts = window.location.pathname.split('/').filter(Boolean);
  // Expected: ['golf', '2026', 'masters', 'leaderboard']
  if (parts[0] === 'golf' && parts.length >= 3) {
    const year = parseInt(parts[1], 10);
    const tournament = parts[2];
    return { tournament, year, key: tournament + '_' + year };
  }
  // Fallback for old /masters/* URLs during transition
  if (parts[0] === 'masters') {
    return { tournament: 'masters', year: 2026, key: 'masters_2026' };
  }
  return { tournament: 'masters', year: 2026, key: 'masters_2026' };
})();

// Backward-compatible sport key for Supabase sync
// Existing masters data uses sport="masters", so we map masters_2026 -> masters
function syncSport() {
  if (TOURNAMENT_CONTEXT.key === 'masters_2026') return 'masters';
  return TOURNAMENT_CONTEXT.key;
}

function localKey(suffix) {
  // masters_2026 uses the old key format for backward compat
  if (TOURNAMENT_CONTEXT.key === 'masters_2026') return 'masters_' + suffix;
  return TOURNAMENT_CONTEXT.key + '_' + suffix;
}

function formatScore(n) {
  if (n === null || n === undefined || n === '') return '';
  if (n === 'E' || n === 0 || n === '0') return 'E';
  const num = typeof n === 'string' ? parseInt(n, 10) : n;
  if (isNaN(num)) return String(n);
  if (num === 0) return 'E';
  return num > 0 ? '+' + num : String(num);
}

function scoreClass(n) {
  if (n === null || n === undefined || n === '' || n === 'E') return 'score-even';
  const num = typeof n === 'string' ? parseInt(n, 10) : n;
  if (isNaN(num) || num === 0) return 'score-even';
  return num < 0 ? 'score-under' : 'score-over';
}

function holeClass(relPar) {
  if (relPar === null || relPar === undefined) return 'no-score';
  if (relPar <= -2) return 'eagle';
  if (relPar === -1) return 'birdie';
  if (relPar === 0) return 'par';
  if (relPar === 1) return 'bogey';
  return 'double-plus';
}

function formatHoleScore(relPar) {
  if (relPar === null || relPar === undefined) return '';
  if (relPar === 0) return '0';
  return relPar > 0 ? '+' + relPar : String(relPar);
}

function getSelections() {
  try {
    return JSON.parse(localStorage.getItem(localKey('selections')) || '{}');
  } catch { return {}; }
}

function saveSelections(sel) {
  if (typeof saveWithSync === 'function') {
    saveWithSync(syncSport(), 'selections', localKey('selections'), sel);
  } else {
    localStorage.setItem(localKey('selections'), JSON.stringify(sel));
  }
}

function isSelected(name, sel) {
  if (!sel) return false;
  if (sel.winner && sel.winner.includes(name)) return true;
  if (sel.top5 && sel.top5.includes(name)) return true;
  if (sel.top10 && sel.top10.includes(name)) return true;
  return false;
}

function get3BallGroups() {
  try {
    const data = JSON.parse(localStorage.getItem(localKey('3ball')) || '{}');
    // Migrate old flat format to per-round format
    if (data.groups && !data.rounds) {
      data.rounds = { [data.round || 1]: data.groups };
      delete data.groups;
      localStorage.setItem(localKey('3ball'), JSON.stringify(data));
    }
    if (!data.rounds) data.rounds = {};
    return data;
  } catch { return { rounds: {} }; }
}

function save3BallGroups(data) {
  if (typeof saveWithSync === 'function') {
    saveWithSync(syncSport(), '3ball', localKey('3ball'), data);
  } else {
    localStorage.setItem(localKey('3ball'), JSON.stringify(data));
  }
}

function getGroupPicks() {
  try {
    return JSON.parse(localStorage.getItem(localKey('groups')) || '{"groups":[]}');
  } catch { return { groups: [] }; }
}

function saveGroupPicks(data) {
  if (typeof saveWithSync === 'function') {
    saveWithSync(syncSport(), 'groups', localKey('groups'), data);
  } else {
    localStorage.setItem(localKey('groups'), JSON.stringify(data));
  }
}

async function initTournamentSync() {
  if (typeof loadWithSync !== 'function' || !isLoggedIn()) return;
  const sport = syncSport();
  const lk = localKey;
  const sel = await loadWithSync(sport, 'selections', lk('selections'), {});
  const ball = await loadWithSync(sport, '3ball', lk('3ball'), { rounds: {} });
  const grp = await loadWithSync(sport, 'groups', lk('groups'), { groups: [] });
  return { selections: sel, threeBall: ball, groupPicks: grp };
}

// Keep old name as alias for backward compat with ev-model etc
const initMastersSync = initTournamentSync;

function sortByToPar(players) {
  return players.slice().sort((a, b) => {
    const ap = parseToPar(a.topar);
    const bp = parseToPar(b.topar);
    if (ap !== bp) return ap - bp;
    return (a.full_name || '').localeCompare(b.full_name || '');
  });
}

function parseToPar(val) {
  if (val === 'E' || val === '0' || val === 0) return 0;
  if (val === '' || val === null || val === undefined) return 999;
  const n = parseInt(val, 10);
  return isNaN(n) ? 999 : n;
}

function timeAgo() {
  const now = new Date();
  const h = now.getHours();
  const m = now.getMinutes().toString().padStart(2, '0');
  const ampm = h >= 12 ? 'PM' : 'AM';
  const hr = h % 12 || 12;
  return hr + ':' + m + ' ' + ampm;
}

async function fetchScores() {
  const t = TOURNAMENT_CONTEXT.tournament;
  const y = TOURNAMENT_CONTEXT.year;
  const resp = await fetch('/api/golf/scores?tournament=' + encodeURIComponent(t) + '&year=' + y);
  if (!resp.ok) throw new Error('Failed to fetch scores');
  return resp.json();
}

// Helper to get tournament display name from tournaments.json (cached)
let _tournamentsCache = null;
async function getTournamentMeta() {
  if (_tournamentsCache) return _tournamentsCache;
  try {
    const resp = await fetch('/data/tournaments.json');
    _tournamentsCache = await resp.json();
  } catch { _tournamentsCache = {}; }
  return _tournamentsCache;
}

function getTournamentInfo() {
  const t = TOURNAMENT_CONTEXT.tournament;
  const y = TOURNAMENT_CONTEXT.year;
  // Synchronous fallback names
  const names = {
    masters: 'The Masters',
    pga: 'PGA Championship',
    'us-open': 'US Open',
    open: 'The Open Championship',
  };
  return { name: names[t] || t, tournament: t, year: y };
}
