-- One-time password reset codes, issued by an admin from /account and redeemed
-- by the locked-out user on the same page. Accounts have no email on file, so
-- the admin is the out-of-band channel: they read the code off their screen and
-- hand it to the user however they already talk.
--
-- The code itself is never stored — only its SHA-256 — so a leaked dump of this
-- table can't be replayed against /api/auth. Run once in the Supabase SQL editor.

create table if not exists password_resets (
  code_hash  text        primary key,             -- sha256(normalized code)
  user_id    uuid        not null references users(id) on delete cascade,
  expires_at timestamptz not null,                -- issuer stamps now() + 30 min
  used_at    timestamptz,                         -- null until redeemed; single use
  created_at timestamptz not null default now()
);

create index if not exists password_resets_user_idx on password_resets (user_id);

-- Issuing a new code and changing a password both retire that user's
-- outstanding codes, so at most one is live per account at any time.

-- Reads/writes go through the service-key endpoint, so RLS stays closed.
alter table password_resets enable row level security;
