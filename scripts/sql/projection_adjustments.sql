-- Hand adjustments to /football/player-projections' team context: one row per
-- team per week. A teammate marked out, a share or snap rate set by hand, the
-- game's spread or total, linemen out, auto factors switched off. Every
-- player on the team reads the same row, so marking the starting back out
-- moves his backup's projection without touching the backup.
--
-- Written and read by api/player-projections.py: anyone may read; role
-- 'admin' or 'editor' may write. `updated_by` is the writer's username, shown
-- under the adjustments.
--
-- Run once in the Supabase SQL editor.

create table if not exists projection_adjustments (
  season      int         not null,
  week        int         not null,
  team        text        not null,
  data        jsonb       not null default '{}'::jsonb,
  updated_by  text,
  updated_at  timestamptz not null default now(),
  primary key (season, week, team)
);

-- Reads and writes go through the endpoint (service key), so RLS can stay closed.
alter table projection_adjustments enable row level security;
