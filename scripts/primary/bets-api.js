// Bets network layer — bridges the bets.js store with the /api/bets endpoint.
// Mirrors scripts/base/sync.js: identity is the X-User-Id header (dz_user_id),
// every request is scoped to that user server-side. Writes are fire-and-forget.

// Build the auth headers. X-User-Id is always the signed-in user (used for auth).
// When an admin is managing another user, X-Audit-User-Id names the target and
// the server operates on that user's rows after verifying admin role.
function betsApiHeaders(user, base) {
  const headers = Object.assign({ 'X-User-Id': user.user_id }, base || {});
  const target = typeof getAuditTarget === 'function' ? getAuditTarget() : null;
  if (target && typeof isAdmin === 'function' && isAdmin()) {
    headers['X-Audit-User-Id'] = target.user_id;
  }
  return headers;
}

// Fetch all of the signed-in user's bets. Returns an array (empty on failure).
async function betsApiList() {
  const user = getUser();
  if (!user) return [];
  try {
    const resp = await fetch('/api/bets', {
      headers: betsApiHeaders(user),
    });
    if (!resp.ok) return [];
    const arr = await resp.json();
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}

// Create or update one bet. Fire-and-forget (the local cache is the source of
// truth for the UI; the server is the source of truth on next load).
function betsApiUpsert(bet) {
  const user = getUser();
  if (!user) return;
  fetch('/api/bets', {
    method: 'PUT',
    headers: betsApiHeaders(user, { 'Content-Type': 'application/json' }),
    body: JSON.stringify(bet),
  }).catch(() => {});
}

// Create or update one bet and report whether the server accepted it. Used by
// workflows that must not update the UI until persistence is confirmed.
async function betsApiUpsertAwaited(bet) {
  const user = getUser();
  if (!user) throw new Error('You must be signed in to settle bets.');
  const resp = await fetch('/api/bets', {
    method: 'PUT',
    headers: betsApiHeaders(user, { 'Content-Type': 'application/json' }),
    body: JSON.stringify(bet),
  });
  if (!resp.ok) {
    let message = 'The server rejected the update.';
    try {
      const body = await resp.json();
      if (body && body.error) message = body.error;
    } catch (_) {}
    throw new Error(message);
  }
  return bet;
}

// Delete one bet by id. Fire-and-forget.
function betsApiDelete(id) {
  const user = getUser();
  if (!user) return;
  fetch(`/api/bets?id=${encodeURIComponent(id)}`, {
    method: 'DELETE',
    headers: betsApiHeaders(user),
  }).catch(() => {});
}
