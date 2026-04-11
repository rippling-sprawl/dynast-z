// Shared utilities for Masters views

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
    return JSON.parse(localStorage.getItem('masters_selections') || '{}');
  } catch { return {}; }
}

function saveSelections(sel) {
  if (typeof saveWithSync === 'function') {
    saveWithSync('masters', 'selections', 'masters_selections', sel);
  } else {
    localStorage.setItem('masters_selections', JSON.stringify(sel));
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
    const data = JSON.parse(localStorage.getItem('masters_3ball') || '{}');
    // Migrate old flat format to per-round format
    if (data.groups && !data.rounds) {
      data.rounds = { [data.round || 1]: data.groups };
      delete data.groups;
      localStorage.setItem('masters_3ball', JSON.stringify(data));
    }
    if (!data.rounds) data.rounds = {};
    return data;
  } catch { return { rounds: {} }; }
}

function save3BallGroups(data) {
  if (typeof saveWithSync === 'function') {
    saveWithSync('masters', '3ball', 'masters_3ball', data);
  } else {
    localStorage.setItem('masters_3ball', JSON.stringify(data));
  }
}

function getGroupPicks() {
  try {
    return JSON.parse(localStorage.getItem('masters_groups') || '{"groups":[]}');
  } catch { return { groups: [] }; }
}

function saveGroupPicks(data) {
  if (typeof saveWithSync === 'function') {
    saveWithSync('masters', 'groups', 'masters_groups', data);
  } else {
    localStorage.setItem('masters_groups', JSON.stringify(data));
  }
}

async function initMastersSync() {
  if (typeof loadWithSync !== 'function' || !isLoggedIn()) return;
  const sel = await loadWithSync('masters', 'selections', 'masters_selections', {});
  const ball = await loadWithSync('masters', '3ball', 'masters_3ball', { rounds: {} });
  const grp = await loadWithSync('masters', 'groups', 'masters_groups', { groups: [] });
  return { selections: sel, threeBall: ball, groupPicks: grp };
}

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
  const resp = await fetch('/api/masters/scores');
  if (!resp.ok) throw new Error('Failed to fetch scores');
  return resp.json();
}
