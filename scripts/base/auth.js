// Lightweight account system — username + password

function getUser() {
  const id = localStorage.getItem('dz_user_id');
  const username = localStorage.getItem('dz_username');
  const role = localStorage.getItem('dz_role');
  if (!id || !username) return null;
  return { user_id: id, username, role: role || 'user' };
}

function setUser(u) {
  localStorage.setItem('dz_user_id', u.user_id);
  localStorage.setItem('dz_username', u.username);
  localStorage.setItem('dz_role', u.role || 'user');
}

function clearUser() {
  localStorage.removeItem('dz_user_id');
  localStorage.removeItem('dz_username');
  localStorage.removeItem('dz_role');

  // Per-user caches must not outlive the session on a shared browser. The Oven
  // keys are namespaced per user id (see OvenLeagues.localKey), so a stale one
  // can no longer be read by the next account — but sweeping them also clears
  // the pre-namespacing globals dz_oven_board_v1 / dz_oven_targets_v1, which
  // loadWithSync would otherwise migrate into whoever signs in next.
  // Iterate downwards: removeItem reindexes localStorage.key(i).
  for (let i = localStorage.length - 1; i >= 0; i--) {
    const k = localStorage.key(i);
    if (k && k.indexOf('dz_oven_') === 0) localStorage.removeItem(k);
  }
  if (typeof clearAuditTarget === 'function') clearAuditTarget();
}

function isLoggedIn() {
  return !!localStorage.getItem('dz_user_id');
}

function isAdmin() {
  return localStorage.getItem('dz_role') === 'admin';
}

// Page gate for admin-only routes. Bounces signed-out visitors to sign-in and
// signed-in non-admins to `fallback`, and returns false so the caller can stop
// initializing the page. UI-level gating only — the static pages and their
// data files are still served to anyone who requests them directly.
function requireAdmin(fallback) {
  if (isLoggedIn() && isAdmin()) return true;
  location.replace(isLoggedIn() ? (fallback || '/') : '/account');
  return false;
}

// Page gate for account-scoped routes — anything whose data is stored per user
// and is meaningless without an identity (Baker's Oven). Same UI-level
// caveat as requireAdmin: the real enforcement is the X-User-Id check in the
// Python endpoints.
function requireLogin() {
  if (isLoggedIn()) return true;
  location.replace('/account');
  return false;
}

// ---- audit / "manage on behalf" session ------------------------------------
// When an admin selects a user in /bets/audit, that user becomes the "audit
// target". Stored in sessionStorage so it auto-clears when the tab closes. The
// bets data layer (betsKey) and API layer (X-Audit-User-Id header) read this so
// every read/write transparently targets that user instead of the admin (the
// admin stays X-User-Id for auth).

function getAuditTarget() {
  const id = sessionStorage.getItem('dz_audit_uid');
  const username = sessionStorage.getItem('dz_audit_username');
  if (!id || !username) return null;
  return { user_id: id, username };
}

function setAuditTarget(user_id, username) {
  sessionStorage.setItem('dz_audit_uid', user_id);
  sessionStorage.setItem('dz_audit_username', username);
}

function clearAuditTarget() {
  sessionStorage.removeItem('dz_audit_uid');
  sessionStorage.removeItem('dz_audit_username');
}

async function register(username, password) {
  const resp = await fetch('/api/auth', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'register', username, password }),
  });
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.error || 'Registration failed');
  setUser(data);
  return data;
}

async function login(username, password) {
  const resp = await fetch('/api/auth', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'login', username, password }),
  });
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.error || 'Login failed');
  setUser(data);
  return data;
}

async function changePassword(currentPassword, newPassword) {
  const me = getUser();
  if (!me) throw new Error('Not signed in');
  const resp = await fetch('/api/auth', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-User-Id': me.user_id },
    body: JSON.stringify({
      action: 'change_password',
      current_password: currentPassword,
      new_password: newPassword,
    }),
  });
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.error || 'Could not change password');
  return data;
}

// Admin-only. Returns { code, username, expires_in_minutes }; the code is shown
// once and stored only as a digest, so there is no way to read it back later.
async function issueResetCode(username) {
  const me = getUser();
  if (!me) throw new Error('Not signed in');
  const resp = await fetch('/api/auth', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-User-Id': me.user_id },
    body: JSON.stringify({ action: 'issue_reset', username }),
  });
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.error || 'Could not issue a reset code');
  return data;
}

// Redeeming a code signs you in, so a locked-out user lands back in the app
// rather than at a sign-in form they'd have to fill again.
async function resetPassword(username, code, newPassword) {
  const resp = await fetch('/api/auth', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      action: 'reset_password', username, code, new_password: newPassword,
    }),
  });
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.error || 'Could not reset password');
  setUser(data);
  return data;
}
