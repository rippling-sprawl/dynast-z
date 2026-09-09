-- The Survivor pool: one row per user per week, naming the team that entry is
-- riding that week. Written by api/survivor.py; read by api/survivor.py and
-- api/survivor-standings.py. Run once in the SQL editor.
--
-- WHY THIS IS NOT pickem_picks
--
-- They are different games played off the same board. A Pick 'Em pick is graded
-- against the frozen spread and there are sixteen of them a week; a Survivor
-- pick is graded straight up, there is exactly one a week, and it carries a
-- constraint that spans the whole season rather than the week. Sharing a table
-- would mean a nullable confidence, a nullable team and a discriminator column
-- that every query has to remember to filter on. Two games, two tables; the
-- board they are both played on (pickem_games) is the thing that is shared.
--
-- THE TWO RULES ARE THE TWO KEYS
--
-- Survivor has exactly two structural rules, and both of them are indexes here
-- rather than checks in Python:
--
--   one pick per week          primary key (user_id, season, week)
--   a team is used once        unique (user_id, season, team)
--
-- Python checks them too, because a 23505 is not a sentence anybody wants to
-- read. But the database is what makes them true: two tabs racing a save, or a
-- retried request, cannot produce a second pick for a week or a second use of a
-- team, whatever the application layer believes.
--
-- game_id is stored alongside `team` and is not redundant. The lock is per game
-- -- a pick is editable until *its own* game kicks off, and visible to everyone
-- once it has -- so the reveal filter in api/_survivor/store.py is a WHERE on
-- game_id. Deriving the game from (season, week, team) at read time would mean
-- joining the board to decide what may be shown, which is the shape that leaks.
create table if not exists survivor_picks (
  user_id    uuid        not null references users(id) on delete cascade,
  season     int         not null,
  week       int         not null,
  game_id    bigint      not null references pickem_games(game_id) on delete cascade,
  team       text        not null,      -- NFL abbr, e.g. 'CHI'; one of the two
                                        -- playing in game_id, checked in Python
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (user_id, season, week)   -- one pick per week, per entry
);

-- No reusing a team. The rule that makes survivor a season-long game rather
-- than eighteen independent coin flips, enforced where it cannot be raced.
create unique index if not exists survivor_picks_team_idx
  on survivor_picks (user_id, season, team);

-- The standings sweep reads a season and the reveal filter narrows by game.
create index if not exists survivor_picks_season_idx on survivor_picks (season, week);
create index if not exists survivor_picks_game_idx   on survivor_picks (game_id);

-- Reads are visibility-filtered and writes are owner-scoped, both in Python
-- against the service key, so RLS stays closed. Same posture as pickem_picks.
alter table survivor_picks enable row level security;
