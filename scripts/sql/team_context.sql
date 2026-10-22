-- Every offense's season, game by game: plays, the opening line, and each skill
-- player's snap share, carries and targets. One row per (season, team).
--
-- Written by scripts/build_team_context.py (Tuesdays 5:00am ET and daily, see
-- .github/workflows/team-context.yml), read by api/player-projections.py
-- (?context=) and turned into the team-context factors at
-- /football/player-projections.
--
-- Run once in the Supabase SQL editor.

create table if not exists team_context (
  season      int         not null,
  team        text        not null,           -- the offense, e.g. 'CHI'
  games       int         not null default 0, -- completed games counted
  data        jsonb       not null,
  updated_at  timestamptz not null default now(),
  primary key (season, team)
);

-- Reads go through the endpoint (service key), so RLS can stay closed.
alter table team_context enable row level security;
