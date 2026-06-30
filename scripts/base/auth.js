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
}

function isLoggedIn() {
  return !!localStorage.getItem('dz_user_id');
}

function isAdmin() {
  return localStorage.getItem('dz_role') === 'admin';
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
