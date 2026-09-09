-- One user's pick on one game. Follows scripts/sql/bets.sql exactly: the
-- composite PK (user_id, game_id) IS the ownership guarantee. Because user_id
-- always comes from the authenticated X-User-Id header, an upsert or a delete
-- can never touch another user's row even if a malicious client supplies a
-- game somebody else picked. Run once in the SQL editor.
--
-- WHY ONE ROW PER GAME AND NOT ONE BLOB PER (user, week)
--
-- Picks are secret until their game kicks off, and the lock is per game. With
-- one row per game that rule is a WHERE clause -- `game_id=in.(<ids already
-- kicked off>)` -- so a pick that must stay hidden is never selected at all.
-- With a per-week blob the server would have to load every other user's blob
-- and strip the unkicked games afterwards, which is the shape that leaks the
-- first time somebody adds a field to the response.
--
-- `pick` and `confidence` stay inside `data` rather than being promoted:
-- nothing indexes or orders by them. The reveal filter is on game_id and the
-- standings aggregate is on (season, week), which is what the columns are for.
create table if not exists pickem_picks (
  user_id    uuid        not null references users(id) on delete cascade,
  game_id    bigint      not null references pickem_games(game_id) on delete cascade,
  season     int         not null,      -- promoted: the standings aggregate
  week       int         not null,      -- promoted: the week board query
  data       jsonb       not null,      -- {"pick": "GB", "confidence": 12, "updatedAt": ...}
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (user_id, game_id)        -- scopes every pick to its owner
);

create index if not exists pickem_picks_week_idx   on pickem_picks (season, week);
create index if not exists pickem_picks_season_idx on pickem_picks (user_id, season);

-- Reads are ownership-filtered and writes are owner-scoped, both in Python
-- against the service key, so RLS stays closed.
alter table pickem_picks enable row level security;
