-- Every team's regular-season totals -- points and net yards, for and against,
-- and games played: one row per season, `data` the whole league as
-- {"season", "source", "fetched_at", "teams": [{abbr, team, conf, div, gp,
-- pf, pa, yf, ya}, ...]}.
--
-- Written by scripts/fetch_team_stats.py (Tuesdays 5:00am ET, see
-- .github/workflows/team-season-stats.yml), read by api/team-season-stats.py
-- and rendered at /football/team-stats/yards-vs-points.
--
-- One row per season rather than per team because the page only ever wants
-- the whole league -- the trend line is fitted across all 32 -- so it is a
-- single primary-key read.
--
-- Run once in the Supabase SQL editor.

create table if not exists team_season_stats (
  season      int         not null primary key,
  data        jsonb       not null,
  updated_at  timestamptz not null default now()
);

-- Reads go through the endpoint (service key), so RLS can stay closed.
alter table team_season_stats enable row level security;
