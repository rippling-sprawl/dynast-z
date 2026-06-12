# Odds ingest — paste a Recorder bundle instead of committing JSON files

_Added 2026-06-12._

Moves the `/odds` data pipeline off "edit files in `data/`, commit, redeploy" and
onto a **paste-and-PUT** flow that works on Vercel's read-only filesystem. The
merge logic is unchanged — it's the same additive upsert the CLI parsers always
used, now callable in-memory from a serverless endpoint.

## How it works

```
Recorder bundle (paste)
        │  PUT /api/odds-ingest
        ▼
 detect_book → scripts/odds_merge.ingest(bundle, state)
        │        ├─ merge_<book>  (prop feed: fd / dk / score)
        │        └─ apply_<book>_outrights  (shared awards/futures column)
        ▼
 Supabase  odds_state(data_key, data jsonb)   ← only the touched keys are written
        ▲
        │  GET /api/odds-ingest
 views/odds.html
```

**PUT semantics = exactly what you asked for.** A bundle for one book updates
that book's prop feed plus *its column* in the shared `outrights` doc. It never
deletes another book, market, candidate, or field, and you don't have to send
everything at once — paste each page's bundle as you record it and the store
accumulates. Re-pasting the same bundle is a no-op (idempotent).

Two granularities (by design):
- **outrights / milestones** — per-candidate merge across FD/DK/Score.
- **prop feeds** (`fd`/`dk`/`score`) — a PUT replaces *that one book's* snapshot
  (still additive across books, just not per-row within a book).

## The shared library

`scripts/odds_merge.py` is the single source of truth, imported by both the CLI
parsers and the endpoint. The six `scripts/parse_*.py` were refactored into pure,
file-I/O-free functions that `odds_merge` orchestrates:

| Book  | prop feed            | outrights column         |
|-------|----------------------|--------------------------|
| FD    | `merge_fd`           | `apply_fd_outrights`     |
| DK    | `merge_dk_props`     | `apply_dk_outrights`     |
| Score | `merge_score`        | `apply_score_outrights`  |

The CLI scripts still run exactly as before (`python3 scripts/parse_fd_import.py`
…) and produce byte-identical files — verified by regenerating all of `data/`
with an empty `git diff`, and by replaying the three import bundles through
`ingest()` and matching every committed artifact byte-for-byte.

## Setup

1. **Create the table** — run `scripts/sql/odds_state.sql` in Supabase.
2. **Seed from today's files** (optional, recommended):
   ```
   SUPABASE_URL=... SUPABASE_KEY=... python3 scripts/seed_odds_state.py
   ```
3. **Lock down writes** — set `ODDS_ADMIN_USER_IDS` (comma-separated user ids
   from the `users` table) in the Vercel project env. If unset, any authenticated
   user (`X-User-Id` header, as issued by `/api/auth`) may PUT.
4. `vercel.json` already bundles `scripts/**` into the function via
   `functions["api/odds-ingest.py"].includeFiles` — confirm the import resolves
   on the first deploy (the endpoint `import odds_merge` relies on it).

## API

- `PUT /api/odds-ingest` — body is a raw Recorder bundle, or
  `{"bundle": <bundle>, "book": "fd|dk|score"}`. `?book=` also overrides
  auto-detection. Returns `{ok, book, changed, summary}` where `summary` includes
  the per-book counts and the **unmapped/skipped market names** — the same report
  the CLI prints, now live feedback at paste time (this is where the "named
  differently" cases from the audit show up).
- `GET /api/odds-ingest` — `{fd, dk, score, outrights}`, or `?key=<one>`.

## Remaining migration step (not done here)

`views/odds.html` still fetches the static `/data/*.json`. To finish the cutover,
point `init()` at the endpoint:

```js
// was: fetch('/data/fd.json'), fetch('/data/dk.json'), fetch('/data/outrights.json'),
//      fetch('/data/score/<stat>.json') ×6
const all = await (await fetch('/api/odds-ingest')).json();
const data = all.fd;                 // {layout, attachments}
buildDkIndex(all.dk);
buildScoreIndex(SCORE_FILES.map(n => all.score[n]).filter(Boolean));
OUTRIGHTS = all.outrights;
```

Until then both paths coexist; the static files remain the live source.

## Housekeeping shipped alongside

- `.vercelignore` drops `data/imports/` (~5.5 MB of raw bundles, never fetched,
  previously public at `/data/imports/*`) plus `data/fd_layout.png` and
  `data/prompts/` from the deploy.
- Unrelated but noted in the audit: `data/fd.json` is ~3 MB shipped on every
  `/odds` load — trimming unused FD layout/market fields in `parse_fd_import.py`
  (or serving via the cached GET above) is the biggest remaining perf win.
