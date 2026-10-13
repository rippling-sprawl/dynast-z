-- What every defense has given up to the players it faced: one row per
-- (season, team), where `team` is the DEFENSE and `data.rows` are the opposing
-- ball-carriers and pass-catchers, one row per player per game.
--
-- Written by scripts/build_defense_vs_players.py (Tuesdays 5:00am ET, see
-- .github/workflows/defense-vs-players.yml), read by api/defense-vs-players.py
-- and rendered at /football/defense-vs-players.
--
-- WHY THIS IS NOT COMPUTED PER REQUEST
--
-- The source is the box score inside each game_odds bundle, and a season of
-- those is hundreds of megabyte-sized rows. Projecting just `player_stats` out
-- of them is cheap enough for a weekly job and far too slow for a page load, so
-- the job does it once and stores the answer -- the same push-not-deploy split
-- game_odds and pickem_games use.
--
-- Run once in the Supabase SQL editor.

create table if not exists defense_vs_players (
  season      int         not null,
  team        text        not null,           -- the defense, e.g. 'DAL'
  games       int         not null default 0, -- completed games counted
  data        jsonb       not null,
  updated_at  timestamptz not null default now(),
  primary key (season, team)
);

-- Reads go through the endpoint (service key), so RLS can stay closed.
alter table defense_vs_players enable row level security;
