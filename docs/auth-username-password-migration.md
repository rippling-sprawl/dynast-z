# Auth Migration: claim-code → username + password

Migrated the sign-in flow from the old "claim code" system (`users(id, display_name, claim_code)`)
to **username + password**, with **roles** and a backend-only **active status**. Pre-existing user
data was wiped (destructive migration was approved).

## Decisions

- **Admin** is granted by a manual SQL `UPDATE` in Supabase after registering — nothing hardcoded.
- **`username` is the single identity field** — also the public display name (header + `/lookup`).
  The old `display_name` column was renamed to `username`; `claim_code` was dropped.
- **odds-ingest** switched from the `ODDS_ADMIN_USER_IDS` env allowlist to a DB `role == 'admin'` check.

## Security model (accepted tradeoff, unchanged from before)

Auth stays stateless: after login the client stores `user_id` in `localStorage` and sends it as the
`X-User-Id` header on writes. This gives "persist until sign out" for free (localStorage has no
expiry). The password only gates the act of logging in; the `user_id` UUID is the de-facto bearer
token. **Status and role are re-checked server-side from the DB on every write**, so deactivation
takes effect immediately.

A future hardening step would be true session tokens, so a leaked `user_id` can't be used to write.

## Schema

`scripts/sql/users_auth.sql` (run manually in the Supabase SQL editor):

```sql
TRUNCATE user_data, users CASCADE;

ALTER TABLE users RENAME COLUMN display_name TO username;
ALTER TABLE users DROP COLUMN IF EXISTS claim_code;
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT    NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS role          TEXT    NOT NULL DEFAULT 'user';
ALTER TABLE users ADD COLUMN IF NOT EXISTS status        BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at    TIMESTAMPTZ NOT NULL DEFAULT now();

-- After registering yourself through the new flow, promote to admin:
--   UPDATE users SET role = 'admin' WHERE username = '<your-username>';
```

## Backend changes

- **`api/auth.py`** — register/login take `username` + `password`. Passwords hashed with stdlib
  `hashlib.pbkdf2_hmac('sha256', …)` (200k iterations), stored as
  `pbkdf2_sha256$<iters>$<salt_hex>$<hash_hex>`, verified with `hmac.compare_digest`. Password min
  length 8. Returns `{user_id, username, role}`; never returns the hash. Inactive users may still
  log in and read.
- **`api/sync.py`** — `do_PUT` looks up the user and returns `403 Account is inactive` unless
  `status === true`. Reads (`do_GET`) unchanged.
- **`api/odds-ingest.py`** — replaced the env allowlist with a DB check requiring `status === true`
  **and** `role === 'admin'`, else `403`.
- **`api/lookup.py`** — queries the renamed `username` column.

> `supabase_request` / `fetch_user` are duplicated per file, consistent with the existing
> self-contained serverless-function style (avoids Vercel bundling surprises).

## Frontend changes

- **`scripts/base/auth.js`** — storage keys `dz_user_id` / `dz_username` / `dz_role`;
  `register`/`login` take a password; added `isAdmin()`.
- **`views/home/account.html`** — username + password forms (`type="password"`); removed the
  sync-code panel and copy button. Keeps golf-data push-on-register / pull-on-login logic.
- **`scripts/base/nav.js`** — header uses `user.username`. `?v=` cache-bust hashes bumped for
  `auth.js` and `nav.js` across all views.

## Verification checklist

1. **Schema** — run `scripts/sql/users_auth.sql`; confirm `users` has the new columns, old rows gone.
2. **Register** — create an account on `/account`; confirm DB row has `role='user'`, `status=true`,
   `pbkdf2_sha256$…` hash (not plaintext).
3. **Promote admin** — `UPDATE users SET role='admin' WHERE username='<you>';`; sign out/in; confirm
   `localStorage.dz_role === 'admin'`.
4. **Persistence** — reload / reopen tab → still signed in. Sign Out → logged-out form.
5. **Wrong password** — bad password → "Invalid username or password".
6. **Active write** — change a golf selection → `sync.js` PUT succeeds (200).
7. **Inactive write** — set `status=false`; trigger a write → `403 Account is inactive`; reads still
   work. Restore `status=true`.
8. **Odds admin gate** — `role='user'` PUT to `/api/odds-ingest` → `403`; `role='admin'` → succeeds.
9. **Lookup** — `/api/lookup?username=<you>` returns picks keyed by the new `username` column.
