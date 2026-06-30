// Bets tracker — data layer + helpers (Phase 1 proof of concept).
//
// Persistence is browser localStorage under a single key. This module is the
// ONLY place that touches storage, so it can be swapped for a DB/API later
// without changing the pages. Also holds the odds math (from the
// sports-betting skill) and the autosuggest index loader.

const BETS_KEY = 'dz_bets_v1';
const BETS_INDEX_URL = '/data/bets-index.json';
const TEST_DATA_URL = '/data/test_data.json';

// Config flag: when false, the read-only demo seed (test_data.json) is never
// fetched or merged into reads — the tracker shows only the user's real bets.
// Flip to true to re-enable the seed for viewing/designing the history UI.
const ENABLE_TEST_DATA = false;

const SPORT_BY_LEAGUE = { NFL: 'Football', NBA: 'Basketball', Other: '' };

// Two independent status axes (disambiguated — see /bets/settle):
//   event_status  — how the underlying event/bet resolved (stored as bet.status)
//   wager_status  — where the money stands (stored as bet.wager_status)
const EVENT_STATUSES = ['pending', 'win', 'loss', 'push', 'void'];
const WAGER_STATUSES = ['unpaid', 'paid', 'settled'];

// Bets with no wager_status are grouped under this label in the Settle Up view.
const WAGER_STATUS_MISSING = 'Missing';

// ---- storage ---------------------------------------------------------------

function loadBets() {
  try {
    const raw = localStorage.getItem(BETS_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr : [];
  } catch (e) {
    return [];
  }
}

function saveBets(arr) {
  localStorage.setItem(BETS_KEY, JSON.stringify(arr || []));
}

function getBet(id) {
  // Seed-aware so the place form can edit a test bet (see seed section below).
  return loadBetsWithSeed().find(b => b.id === id) || null;
}

function deleteBet(id) {
  saveBets(loadBets().filter(b => b.id !== id));
}

// ---- read-only test seed ---------------------------------------------------
// Demo bets loaded from /data/test_data.json (built by scripts/build_test_data.py)
// for viewing/designing the history UI. They are merged into reads ONLY — the
// write path (saveBets/upsertBet/deleteBet) stays pure localStorage, so the seed
// is never persisted and can't collide with the user's real bets. Each seed bet
// carries `_test: true`.

let _seedCache = null;

async function loadTestBets() {
  if (_seedCache) return _seedCache;
  if (!ENABLE_TEST_DATA) {
    _seedCache = [];
    return _seedCache;
  }
  try {
    const res = await fetch(TEST_DATA_URL);
    const arr = await res.json();
    _seedCache = Array.isArray(arr) ? arr : [];
  } catch (e) {
    _seedCache = [];
  }
  return _seedCache;
}

// Sync accessor — empty until loadTestBets() has resolved.
function seedBets() {
  return _seedCache || [];
}

// Real (localStorage) bets plus seed bets, dropping any seed whose id has been
// shadowed by a real bet (e.g. after editing+saving a test bet).
function loadBetsWithSeed() {
  const real = loadBets();
  const realIds = new Set(real.map(b => b.id));
  return real.concat(seedBets().filter(b => !realIds.has(b.id)));
}

// Create (no id) or update (existing id). Returns the saved bet.
function upsertBet(bet) {
  const bets = loadBets();
  if (bet.id) {
    const i = bets.findIndex(b => b.id === bet.id);
    if (i >= 0) bets[i] = bet;
    else bets.push(bet);
  } else {
    bet.id = 'b_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    bet.placed_at = new Date().toISOString();
    bets.push(bet);
  }
  bet.sport = SPORT_BY_LEAGUE[bet.league] !== undefined ? SPORT_BY_LEAGUE[bet.league] : '';
  if (bet.status && bet.status !== 'pending' && !bet.settled_at) {
    bet.settled_at = new Date().toISOString();
  }
  if (bet.status === 'pending') bet.settled_at = null;
  saveBets(bets);
  return bet;
}

function pendingBets() {
  return loadBets().filter(b => b.status === 'pending');
}

// Newest first, by placed_at.
function allBetsNewestFirst() {
  return loadBets().slice().sort((a, b) =>
    (b.placed_at || '').localeCompare(a.placed_at || ''));
}

// Seed-aware variants for the views (call after `await loadTestBets()`).
function pendingBetsWithSeed() {
  return loadBetsWithSeed().filter(b => b.status === 'pending');
}

function allBetsWithSeedNewestFirst() {
  return loadBetsWithSeed().slice().sort((a, b) =>
    (b.placed_at || '').localeCompare(a.placed_at || ''));
}

// ---- odds / payout math (sports-betting skill) -----------------------------

function americanToDecimal(american) {
  const a = Number(american);
  if (!a) return null;
  return a > 0 ? (a / 100) + 1 : (100 / Math.abs(a)) + 1;
}

// Profit if the bet wins, from stake + american odds.
function toWinFromOdds(stake, american) {
  const d = americanToDecimal(american);
  const s = Number(stake);
  if (!d || !s) return null;
  return +(s * (d - 1)).toFixed(2);
}

// Net profit/loss given the bet's status. Returns null while pending.
function profitLoss(bet) {
  const stake = Number(bet.stake) || 0;
  const toWin = Number(bet.to_win) || 0;
  switch (bet.status) {
    case 'win': return +toWin;
    case 'loss': return -stake;
    case 'push':
    case 'void': return 0;
    default: return null; // pending
  }
}

// ---- autosuggest index -----------------------------------------------------

let _indexCache = null;

async function loadIndex() {
  if (_indexCache) return _indexCache;
  try {
    const res = await fetch(BETS_INDEX_URL);
    _indexCache = await res.json();
  } catch (e) {
    _indexCache = { leagues: ['NFL', 'NBA', 'Other'], teams: {}, players: {} };
  }
  return _indexCache;
}

// Team options for a league. Each is a combobox option:
//   label  = full name shown in the dropdown ("New York Jets")
//   value  = abbreviation stored + displayed ("NYJ")
//   search = abbr + full name, so typing "NYJ" or "Jets" both match
// (the abbr is searchable but never shown as the dropdown label).
function teamSuggestions(index, league) {
  const list = (index.teams && index.teams[league]) || [];
  return list.map(t => ({
    label: t.name,
    value: t.abbr,
    search: `${t.abbr} ${t.name}`,
  }));
}

// Player options for a league (used on the "side" field for props).
function playerSuggestions(index, league) {
  const list = (index.players && index.players[league]) || [];
  return list.map(p => {
    const label = p.team ? `${p.name} (${p.team})` : p.name;
    return { label, value: label, search: `${p.name} ${p.team || ''}` };
  });
}

// Combined team + player options — used where either is a valid pick ("side").
function sideSuggestions(index, league) {
  return teamSuggestions(index, league).concat(playerSuggestions(index, league));
}

// ---- formatting helpers ----------------------------------------------------

function fmtOdds(american) {
  const a = Number(american);
  if (!a) return '';
  return a > 0 ? `+${a}` : `${a}`;
}

function fmtMoney(n) {
  if (n === null || n === undefined || n === '') return '';
  const v = Number(n);
  const sign = v < 0 ? '-' : '';
  return `${sign}$${Math.abs(v).toFixed(2)}`;
}

function fmtDate(s) {
  if (!s) return '';
  // Accept ISO timestamps and plain YYYY-MM-DD date strings.
  const d = s.length <= 10 ? new Date(s + 'T00:00:00') : new Date(s);
  if (isNaN(d)) return s;
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

// Compact MM.DD.YY (used on bet tiles next to the match).
function fmtDateShort(s) {
  if (!s) return '';
  const d = s.length <= 10 ? new Date(s + 'T00:00:00') : new Date(s);
  if (isNaN(d)) return s;
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  const yy = String(d.getFullYear()).slice(-2);
  return `${mm}.${dd}.${yy}`;
}
