// Pick 'Em network layer — the three calls the pages make, and nothing else.
//
// Identity is the X-User-Id header (dz_user_id), the same as scripts/base/sync.js
// and scripts/primary/bets-api.js. Every request is scoped to that user
// server-side; nothing here decides what the caller may see.
//
// Unlike bets-api.js, the write here is AWAITED and its error surfaces. A bet
// that fails to save can be re-entered from the form it is still sitting in; a
// week of picks that fails silently costs the week, and the player finds out on
// the standings page. So pickemSave rejects with the server's own message and
// the page is responsible for showing it.

// Every response is JSON, including the errors, so one reader handles both.
//
// A read goes out without the header when there is no session, because the hub
// and the standings are public — /api/pickem and /api/pickem-standings answer an
// anonymous GET with the same board and a field whose names and ids have been
// replaced server-side (api/_pickem/store.py, anonymise). A write still needs
// one, and is refused here rather than at the server so the message is the one
// the page wants to print.
async function pickemFetch(url, options) {
  const user = typeof getUser === 'function' ? getUser() : null;
  const method = ((options || {}).method || 'GET').toUpperCase();
  if (!user && method !== 'GET') throw new Error('Sign in to make picks.');
  const resp = await fetch(url, Object.assign({}, options, {
    headers: Object.assign(user ? { 'X-User-Id': user.user_id } : {},
                           (options || {}).headers || {}),
  }));
  let body = null;
  try {
    body = await resp.json();
  } catch {
    body = null;
  }
  if (!resp.ok) {
    const err = new Error((body && body.error) || `Request failed (${resp.status})`);
    err.status = resp.status;
    // The 409 carries the game ids that moved out from under the edit, which is
    // what lets the page say which rows it is about to reload.
    err.locked = (body && body.locked) || null;
    throw err;
  }
  return body;
}

// One week's board: games, frozen lines, your picks, and everyone else's picks
// for the games that have kicked off. Omit `week` for the current one.
function pickemLoadWeek(season, week) {
  const q = new URLSearchParams();
  if (season) q.set('season', season);
  if (week) q.set('week', week);
  const query = q.toString();
  return pickemFetch('/api/pickem' + (query ? '?' + query : ''));
}

// Replace your picks for one week. `picks` is the complete intended set — a
// game left out is a game un-picked — which is the only shape that can carry a
// permutation of confidences without a half-applied swap in the middle of it.
function pickemSave(season, week, picks) {
  return pickemFetch('/api/pickem', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ season: season, week: week, picks: picks }),
  });
}

// The leaderboard. `week` narrows it to a single week's board.
function pickemStandings(season, week) {
  const q = new URLSearchParams();
  if (season) q.set('season', season);
  if (week) q.set('week', week);
  const query = q.toString();
  return pickemFetch('/api/pickem-standings' + (query ? '?' + query : ''));
}
