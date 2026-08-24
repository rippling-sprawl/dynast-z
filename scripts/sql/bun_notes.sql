-- Baker's Buns notes. Unlike `bets`, this store is global rather than per-user:
-- anyone signed in writes, everyone reads, so there is no user_id in the key.
-- A note still has an owner — `data->>'authorId'`, stamped on create and
-- carried forward on edit — which is what api/bun-notes.py checks before a
-- write: its author or an admin. The seeded doc imports have a null authorId
-- and so are admin-only. One row per note; the full note object lives in `data`
-- (jsonb) per the repo's convention. `team` and `week` are promoted to columns
-- for indexing and ordering. Run once in the SQL editor.
create table if not exists bun_notes (
  id         text        primary key,             -- 'n_...' from the client, 'seed_...' from the seeder
  team       text        not null default '',     -- NFL abbr ('CHI'); '' means league-wide
  week       text        not null default 'all',  -- all | pre | 1..18 | wc | div | conf | sb
  data       jsonb       not null,                -- the full note object
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists bun_notes_team_idx on bun_notes (team);

-- Reads are public and writes are ownership-gated, both in Python against the
-- service key, so RLS stays closed.
alter table bun_notes enable row level security;
