-- Backing store for the /odds page's merged artifacts (one row per artifact).
-- Run once in the Supabase SQL editor. The /api/odds-ingest endpoint upserts
-- into this table; reads are served back to the page via GET.

create table if not exists odds_state (
  data_key   text primary key
             check (data_key in ('fd', 'dk', 'score', 'outrights')),
  data       jsonb       not null,
  updated_at timestamptz not null default now()
);

-- Reads go through the endpoint (service key), so RLS can stay closed.
alter table odds_state enable row level security;

-- One-time seed from the committed files (optional). From the repo root:
--   python3 scripts/seed_odds_state.py
-- which PUTs data/fd.json, data/dk.json, data/outrights.json and the six
-- data/score/*.json (bundled as one `score` blob) into the table.
