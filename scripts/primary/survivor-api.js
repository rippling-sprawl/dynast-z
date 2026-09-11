// Survivor network layer — the three calls the pages make, and nothing else.
//
// Identity is the X-User-Id header (dz_user_id), the same as
// scripts/primary/pickem-api.js and scripts/base/sync.js. Every request is
// scoped to that user server-side; nothing here decides what the caller may
// see, and in particular nothing here decides which of somebody else's picks
// are visible — that is a WHERE clause in api/_survivor/store.py.
//
// The write is AWAITED and its error surfaces, for the reason pickem-api.js
// gives and then some: a survivor pick that fails to save silently is not a
// lost week, it is a lost season. Every rejection this can produce is a
// sentence written to be shown verbatim — the team is already spent, the game
// has kicked off, the entry is out — so the pages print err.message rather
// than inventing their own copy.

// Every response is JSON, including the errors, so one reader handles both.
async function survivorFetch(url, options) {
  const user = typeof getUser === 'function' ? getUser() : null;
  if (!user) throw new Error('Sign in to make a pick.');
  const resp = await fetch(url, Object.assign({}, options, {
    headers: Object.assign({ 'X-User-Id': user.user_id },
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
    // A 409 is one of the two things that move under an open page: the game
    // kicked off mid-edit, or the entry was eliminated by a result that landed
    // while the tab sat there. Both carry what the page needs to explain it.
    err.locked = (body && body.locked) || null;
    err.entry = (body && body.entry) || null;
    throw err;
  }
  return body;
}

// One week's board: every game in the week, your pick, the teams you have
// already spent, where your entry stands, and the other entries' picks for the
// games that have kicked off. Omit `week` for the current one.
function survivorLoadWeek(season, week) {
  const q = new URLSearchParams();
  if (season) q.set('season', season);
  if (week) q.set('week', week);
  const query = q.toString();
  return survivorFetch('/api/survivor' + (query ? '?' + query : ''));
}

// Set the week's pick. One team, one game — there is no partial state to send,
// which is why this is a single value rather than the whole-week payload the
// Pick 'Em has to submit.
function survivorSave(season, week, gameId, team) {
  return survivorFetch('/api/survivor', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ season: season, week: week, game_id: gameId, team: team }),
  });
}

// Take the week's pick back off the board. `team: null` is the clear — the same
// endpoint, because clearing is subject to exactly the same lock as setting and
// splitting it into a DELETE would invite that check to be written twice.
function survivorClear(season, week) {
  return survivorFetch('/api/survivor', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ season: season, week: week, team: null }),
  });
}

// The board of who is left. Carries picks, unlike the Pick 'Em standings —
// see the header of api/survivor-standings.py for why that is safe here.
function survivorStandings(season) {
  const q = new URLSearchParams();
  if (season) q.set('season', season);
  const query = q.toString();
  return survivorFetch('/api/survivor-standings' + (query ? '?' + query : ''));
}
