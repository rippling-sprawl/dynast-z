-- The Action Network book: one row per page of it.
--
-- Written by scripts/build_action.py (via PUT /api/action-ingest), read by
-- api/action.py. `etag` is the sha256 of the canonical JSON of `data`, computed
-- by the builder -- it is the page's HTTP validator, which is what lets an
-- unchanged page cost a 304 instead of a re-render.
--
-- Artwork is NOT here. It lives as committed, content-addressed files under
-- assets/action/<sha8>.png and is served straight off the CDN as immutable.

create table if not exists action_pages (
  slug        text primary key,
  data        jsonb       not null,
  etag        text        not null,
  updated_at  timestamptz not null default now()
);

-- Reads are always by primary key, so no extra index is needed. Access is
-- entirely application-level via the service key, as with every other table
-- here (see api/odds-ingest.py, api/sync.py): the endpoint decides who may
-- write, and PUT /api/action-ingest requires an active admin.
