-- The /power-rankings card deck. One row per deck (today only 'jhbc'); the
-- whole controlled model — title, tiers, cards, unassigned — lives in `data`.
--
-- This table, not data/power_rankings_seed.json, is the copy of record. The
-- seed file is read only while the table has no row for the deck: the first
-- admin to open the page saves it here, and from then on deploys never touch
-- the cards. Local dev (.env) and production point at this same table.
--
-- `version` is the optimistic lock: a save names the version it was edited
-- from, and api/power-rankings.py only writes when that still matches, so a
-- stale tab or script gets a 409 instead of overwriting newer cards.
--
-- Every save is also appended to power_rankings_history, so any earlier
-- version can be restored by hand.
--
-- Run once in the Supabase SQL editor.

create table if not exists power_rankings (
  id          text        primary key,           -- deck id, 'jhbc'
  version     int         not null default 1,
  data        jsonb       not null,
  updated_by  text,                              -- writer's username
  updated_at  timestamptz not null default now()
);

create table if not exists power_rankings_history (
  id          text        not null,
  version     int         not null,
  data        jsonb       not null,
  updated_by  text,
  updated_at  timestamptz not null default now(),
  primary key (id, version)
);

-- Reads and writes go through the endpoint (service key), so RLS can stay closed.
alter table power_rankings enable row level security;
alter table power_rankings_history enable row level security;
