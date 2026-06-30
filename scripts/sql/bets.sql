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
