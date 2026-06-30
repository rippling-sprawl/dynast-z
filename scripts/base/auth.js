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
