-- The Pick 'Em board: one row per NFL game that can be picked, carrying the
-- spread as it stood at the Tuesday 3:00am ET freeze and, later, the ATS
-- verdict. Written by scripts/pickem_capture.py; read by api/pickem.py and
-- api/pickem-standings.py. Run once in the SQL editor.
--
-- WHY THIS IS NOT game_odds
--
-- game_odds is a *current* bundle. scripts/bdl_refresh.py overwrites it on a
-- cadence that drops to two minutes during a live game (refresh_plan() in
-- scripts/fetch_bdl_game.py). A frozen line is the opposite kind of object: it
-- is written exactly once and must never move again, because it is what a week
-- of picks was graded against. Two lifecycles, two tables.
--
-- WHY THE SCORE LIVES HERE AND NOT IN data/nfl_schedule_<season>.json
--
-- The committed schedule only gains `score` when a human runs
-- scripts/fetch_nfl_schedule.py, commits and deploys. Standings that cannot
-- move without a deploy are the wrong product, so the same job that freezes the
-- line writes the final score back here and the leaderboard is current on the
-- next request.
create table if not exists pickem_games (
  game_id      bigint      primary key,   -- balldontlie's id, the same one
                                          -- data/nfl_schedule_*.json carries
  season       int         not null,
  week         int         not null,
  away         text        not null,      -- NFL abbr, e.g. 'CHI'
  home         text        not null,
  kickoff      timestamptz not null,      -- THE lock instant, evaluated server-side
  spread_home  numeric(4,1),              -- consensus from the home side:
                                          -- -3.5 means the home team lays 3.5
  deadline_at  timestamptz,               -- nominal Tuesday 03:00 America/New_York
  frozen_at    timestamptz,               -- when the capture actually ran; a
                                          -- non-null value is what makes a
                                          -- re-run a no-op
  away_score   int,
  home_score   int,
  status       text        not null default 'scheduled',  -- scheduled|live|final
  result       text,                      -- away | home | push | null (ungraded)
  graded_at    timestamptz,
  data         jsonb       not null default '{}'::jsonb,  -- every book's row at
                                          -- freeze time, the consensus workings,
                                          -- and the line_status flag
  updated_at   timestamptz not null default now()
);

-- The week board is the hot query; the standings sweep filters by season.
create index if not exists pickem_games_week_idx on pickem_games (season, week, kickoff);

-- Reads and writes both go through the service-key endpoints, so RLS stays closed.
alter table pickem_games enable row level security;
