// Sync layer — bridges localStorage with server storage

async function syncPull(sport, key) {
  const user = getUser();
  if (!user) return null;
  try {
    const resp = await fetch(`/api/sync?sport=${encodeURIComponent(sport)}&key=${encodeURIComponent(key)}`, {
      headers: { 'X-User-Id': user.user_id },
    });
    if (!resp.ok) return null;
    return resp.json();
  } catch { return null; }
}

function syncPush(sport, key, data) {
  const user = getUser();
  if (!user) return;
  fetch('/api/sync', {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      'X-User-Id': user.user_id,
    },
    body: JSON.stringify({ sport, key, data }),
  }).catch(() => {});
}

async function loadWithSync(sport, key, localStorageKey, defaultValue) {
  // Always return localStorage immediately
  let local;
  try {
    local = JSON.parse(localStorage.getItem(localStorageKey) || 'null');
  } catch { local = null; }

  if (!isLoggedIn()) return local || defaultValue;

  // Pull from server in background
  const remote = await syncPull(sport, key);

  if (remote !== null && remote !== undefined) {
    // Server has data — use it and update localStorage
    localStorage.setItem(localStorageKey, JSON.stringify(remote));
    return remote;
  } else if (local && Object.keys(local).length > 0) {
    // Server empty but localStorage has data — push to server (auto-migration)
    syncPush(sport, key, local);
    return local;
  }

  return local || defaultValue;
}

function saveWithSync(sport, key, localStorageKey, data) {
  localStorage.setItem(localStorageKey, JSON.stringify(data));
  syncPush(sport, key, data);
}
