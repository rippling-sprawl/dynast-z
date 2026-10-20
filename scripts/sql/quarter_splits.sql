-- Every team's points by quarter, scored and allowed: one row per
-- (season, team), `data.games` one entry per completed game with `pf` and `pa`
-- as [q1, q2, q3, q4, ot].
--
-- Written by scripts/build_quarter_splits.py (Tuesdays 5:00am ET, see
-- .github/workflows/quarter-splits.yml), read by api/quarter-splits.py and
-- rendered at /football/team-stats/quarter-splits.
--
-- The source is the quarter line inside each game_odds bundle. Projecting it
-- out of a season of megabyte-sized rows is fine for a weekly job and too slow
-- for a page load, so the job does it once -- the same push-not-deploy split
-- defense_vs_players uses.
--
-- Run once in the Supabase SQL editor.

create table if not exists quarter_splits (
  season      int         not null,
  team        text        not null,           -- e.g. 'DAL'
  games       int         not null default 0, -- completed games counted
  data        jsonb       not null,
  updated_at  timestamptz not null default now(),
  primary key (season, team)
);

-- Reads go through the endpoint (service key), so RLS can stay closed.
alter table quarter_splits enable row level security;
