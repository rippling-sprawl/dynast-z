-- Migrate the users table from the old claim-code model to username + password,
-- with roles and a backend-only active status. Run once in the Supabase SQL editor.
-- Pre-existing user data is intentionally wiped.

-- Wipe existing user data (allowed) and reshape the users table.
truncate user_data, users cascade;

alter table users rename column display_name to username;
alter table users drop column if exists claim_code;
alter table users add column if not exists password_hash text        not null default '';
alter table users add column if not exists role          text        not null default 'user';
alter table users add column if not exists status        boolean     not null default true;
alter table users add column if not exists created_at    timestamptz not null default now();

-- After registering yourself through the new flow, promote to admin:
--   update users set role = 'admin' where username = '<your-username>';
