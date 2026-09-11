-- One NFL game's odds, props, box score and play log: one row per game.
--
-- Written by scripts/fetch_bdl_game.py --publish, read by api/game-odds.py and
-- rendered at /football/schedule/game/<game_id>. `game_id` is balldontlie's,
-- also the id data/nfl_schedule_*.json carries since the schedule moved to that
-- source -- so a schedule row links straight here with no mapping table.
--
-- WHY THIS IS NOT A COMMITTED FILE
--
-- A single game's bundle is ~900 KB of JSON, most of it player props: 34
-- players x 25 markets x 6 sportsbooks, both sides of every over/under. Two
-- games came to 1.8 MB. At a full 16-game slate that would be ~15 MB a week
-- added to the repo forever, for data that is refetched whenever it changes and
-- is worthless once stale. So it lives here and moves on a push, with no deploy
-- -- the same split as action_pages.
--
-- WHY THE SUMMARY COLUMNS ARE DUPLICATED OUT OF `data`
--
-- The index listing (which games have been captured) must not pull a megabyte
-- of jsonb per row to render a list of matchups. These columns are what the
-- listing selects; `data` is only ever fetched by primary key.

create table if not exists game_odds (
  game_id     bigint primary key,
  season      int,
  week        int,
  phase       text        not null,          -- pregame | live | final
  away        text        not null,
  home        text        not null,
  kickoff     timestamptz,
  title       text,
  label       text,
  has         jsonb       not null default '{}'::jsonb,
  data        jsonb       not null,
  etag        text        not null,
  updated_at  timestamptz not null default now()
);

-- The listing is ordered newest-first; nothing else queries by anything but the
-- primary key.
create index if not exists game_odds_kickoff_idx on game_odds (kickoff desc);

-- Access is application-level via the service key, as with every other table
-- here (see scripts/sql/action_pages.sql): reads go through api/game-odds.py,
-- which is public because the page it feeds is, and writes are done by the
-- fetcher with the service key from .env.
