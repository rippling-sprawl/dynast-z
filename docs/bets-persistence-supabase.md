# Bets Persistence: localStorage → per-user Supabase

The `/bets` tracker started as a proof of concept persisting only to browser `localStorage`. To
publish it to friends, bets now persist server-side, scoped per user: **a user must be logged in and
active to add/edit bets, and can only see and edit their own bets.** This follows the existing
`user_data` / `api/sync.py` patterns rather than introducing anything new (no Supabase Auth/RLS, no
ORM).

## Decisions

- **Dedicated `bets` table, one row per bet**, with all bet fields kept in a flexible `jsonb` `data`
  column — **no column-schema churn**. Later migrations only need to promote jsonb keys into real
  columns once the schema settles. A natural stepping stone to a long-term transactional model.
- **Composite PK `(user_id, id)` is the ownership guarantee.** Because `user_id` always comes from
  the authenticated header, an upsert or delete can **never** touch another user's row even if a
  malicious client supplies someone else's bet `id`.
- **`localStorage` (`dz_bets_v1`) stays as an offline read cache.** `bets.js` remains the single
  storage chokepoint; `initBets()` hydrates the cache from the server (source of truth) on page load,
  and the synchronous read accessors are unchanged. Writes stay fire-and-forget, preserving the
  current "save then redirect" UX.

## Architecture mirrored (do not deviate)

- **Service-key REST, RLS closed.** All Supabase access is server-side via the service key
  (`SUPABASE_KEY`); the `bets` table has RLS `enable`d but closed. Authorization is enforced in
  Python, not in the DB.
- **Identity = `X-User-Id` header.** The client sends `dz_user_id` as the `X-User-Id` header.
  Ownership is enforced by filtering every query on that `user_id`.
- **"Active" = `users.status is True`, gated on writes only.** Reads are not status-gated; every
  write calls `fetch_user(user_id)` and returns `403` unless `status is True`.
- **Two runtimes kept in parity.** Production uses `api/*.py` serverless functions (auto-routed by
  the `"/api/:path*"` rewrite in `vercel.json` — no config change needed). Local dev re-implements
  the same handlers inline in `server.py`. Every endpoint change lands in **both**.

## Schema

`scripts/sql/bets.sql` (run once manually in the Supabase SQL editor):

```sql
-- Per-user bet tracker store. One row per bet; all bet fields live in `data`
-- (jsonb) so the column schema stays uncommitted. Run once in the SQL editor.
create table if not exists bets (
  user_id    uuid        not null references users(id) on delete cascade,
  id         text        not null,              -- client-generated "b_..." id
  data       jsonb       not null,              -- the full bet object
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (user_id, id)                     -- scopes every bet to its owner
);

create index if not exists bets_user_idx on bets (user_id);

-- Reads/writes go through the service-key endpoint, so RLS stays closed.
alter table bets enable row level security;
```

## Backend changes

- **`api/bets.py`** (new) — modeled on `api/sync.py`. Has its own `supabase_request` that tolerates
  empty response bodies (`return=minimal`).
  - **`do_GET`** — require `X-User-Id` (401 if missing). No status gate (read).
    `GET bets?user_id=eq.{uid}&select=data&order=created_at` → returns `[row["data"], ...]`, a plain
    array of bet objects; `[]` when empty.
  - **`do_PUT`** — require `X-User-Id`; then `fetch_user` + `status is True` or `403`. Body is a bet
    object (must include `id`). Upserts `POST bets?on_conflict=user_id,id` with body
    `{user_id, id, data: bet, updated_at: "now()"}` and `Prefer: resolution=merge-duplicates,return=minimal`.
  - **`do_DELETE`** — require `X-User-Id`; same active gate. Reads `id` from the query string and
    `DELETE bets?user_id=eq.{uid}&id=eq.{id}`.
  - **`do_OPTIONS`** — `Access-Control-Allow-Methods: GET, PUT, DELETE, OPTIONS`.
- **`server.py`** (dev parity) — added `/api/bets` branches to `do_GET` and `do_PUT`, plus a new
  `do_DELETE` method. Reuses the module-level `supabase_request` / `fetch_user`. Uses
  `Prefer: ...return=representation` (not `minimal`) because `server.py`'s shared `supabase_request`
  parses every response body. `do_OPTIONS` allowed methods updated to include `DELETE`.

## Frontend changes

- **`scripts/primary/bets-api.js`** (new) — thin network layer mirroring `scripts/base/sync.js`
  (uses `getUser()` / `X-User-Id`):
  - `betsApiList()` → `GET /api/bets`; returns array or `[]` on any failure.
  - `betsApiUpsert(bet)` → `PUT /api/bets`, fire-and-forget.
  - `betsApiDelete(id)` → `DELETE /api/bets?id=...`, fire-and-forget.
- **`scripts/primary/bets.js`** — added `async initBets()` (overwrites the `localStorage` cache with
  the server result when logged in). `upsertBet` and `deleteBet` now also push to the API after
  `saveBets(...)`. Read accessors unchanged.
- **`views/bets/{index,place,history,settle}.html`** — each now gates with
  `if (!isLoggedIn()) { location.href = '/account'; return; }`, calls `await initBets()` before
  rendering, and includes `bets-api.js` before `bets.js`.

## Security model (accepted tradeoff, app-wide)

`X-User-Id` is a client-supplied, unauthenticated identifier — the same trust model used across the
entire app today (golf picks via `/api/sync` have identical exposure). A leaked/guessed `user_id`
could read or edit that user's bets. Active status is re-checked server-side on every write, so
deactivation takes effect immediately. Hardening to real session tokens would be a separate,
app-wide change and is out of scope here.

## Verification checklist

1. **Schema** — run `scripts/sql/bets.sql`; confirm the `bets` table and `bets_user_idx` exist.
2. **Local end-to-end** (`python3 server.py`):
   - Visit `/bets` logged out → redirected to `/account`.
   - Register/log in, add a bet at `/bets/place` → appears on `/bets`; reload → still there (now
     from Supabase). Confirm a `bets` row with the correct `user_id` and the bet object in `data`.
   - Edit then delete the bet → row updates then disappears.
   - **Isolation** — log in as a second user → none of the first user's bets are visible.
   - **Active gate** — set `status=false` for the test user; retry add/edit/delete → `403`.
   - **Ownership guard** — `PUT`/`DELETE /api/bets` with another user's bet `id` only ever
     creates/affects a row under *your* `user_id`, never theirs.
3. **Production** — deploy; confirm `/api/bets` is reachable (auto-routed via `vercel.json`) and the
   same flow works on dynastz.com.
