// Lightweight account system — display name + claim code

function getUser() {
  const id = localStorage.getItem('dz_user_id');
  const name = localStorage.getItem('dz_display_name');
  const code = localStorage.getItem('dz_claim_code');
  if (!id || !name) return null;
  return { user_id: id, display_name: name, claim_code: code };
}

function setUser(u) {
  localStorage.setItem('dz_user_id', u.user_id);
  localStorage.setItem('dz_display_name', u.display_name);
  if (u.claim_code) localStorage.setItem('dz_claim_code', u.claim_code);
}

function clearUser() {
  localStorage.removeItem('dz_user_id');
  localStorage.removeItem('dz_display_name');
  localStorage.removeItem('dz_claim_code');
}

function isLoggedIn() {
  return !!localStorage.getItem('dz_user_id');
}

async function register(displayName) {
  const resp = await fetch('/api/auth', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'register', display_name: displayName }),
  });
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.error || 'Registration failed');
  setUser(data);
  return data;
}

async function login(displayName, claimCode) {
  const resp = await fetch('/api/auth', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'login', display_name: displayName, claim_code: claimCode }),
  });
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.error || 'Login failed');
  setUser(data);
  return data;
}
