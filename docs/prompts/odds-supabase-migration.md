# Prompt: finish the /odds Supabase migration (and ship the pending DK fix)

_Saved 2026-06-12 for later. Paste this to a fresh session to resume._

## Context

The paste-and-PUT odds ingest pipeline is **built but dormant**. The live `/odds`
page still reads static `/data/*.json`. Background reading:
- [../odds-pipeline-overview.md](../odds-pipeline-overview.md)
- [../odds-ingest.md](../odds-ingest.md) (setup + odds.html migration snippet)

Already in place (no need to rebuild):
- `scripts/odds_merge.py` — `detect_book` + `ingest(bundle, state)`, the shared
  merge core (verified byte-identical to the old file pipeline).
- `scripts/parse_*.py` — refactored into importable `merge_*` / `apply_*_outrights`
  functions with thin CLI wrappers.
- `api/odds-ingest.py` — `PUT` (auth'd, additive, idempotent) + `GET`.
- `scripts/sql/odds_state.sql`, `scripts/seed_odds_state.py`.
- `vercel.json` bundles `scripts/**` into the function.

## Uncommitted working-tree change to be aware of

There is an **uncommitted** DK fix already applied to the working tree (NOT yet
committed, by request):
- `scripts/parse_dk_outrights.py` — extended `DK_EXACT` + prefix/suffix stripping
  in `canon_key` (maps DK's `Regular Season MVP`, OPoY, DPoY, CoY, CPoY,
  `To Miss Playoffs`, `Most Regular Season Wins`, AFC/NFC 1-Seed).
- `data/outrights.json` — now carries DK columns for those 9 markets (MVP = 121
  prices, etc.), ingested from a one-off DraftKings awards bundle that has since
  been deleted. **This data lives only in the uncommitted `data/outrights.json`** —
  don't discard the working tree without committing it first.

## Decide which path, then do it

### Path A — just ship the fix (no Supabase)
1. `git checkout -b odds-dk-awards` (don't commit to main directly).
2. Commit `scripts/parse_dk_outrights.py` + `data/outrights.json` (+ the rest of
   the pipeline refactor if not already committed) and push. Vercel redeploys;
   static files update. Done.

### Path B — actually migrate to Supabase (these need the human's dashboards)
Human does first:
1. Run `scripts/sql/odds_state.sql` in the Supabase SQL editor.
2. Seed: `SUPABASE_URL=… SUPABASE_KEY=… python3 scripts/seed_odds_state.py`
   (this pushes the current `data/*.json`, **including** the DK fix above).
3. Set `ODDS_ADMIN_USER_IDS` (comma-separated `users.id` values) in Vercel env.

Then the agent does:
4. Rewire `views/odds.html` `init()` to fetch `GET /api/odds-ingest` instead of
   the 4 static fetches (snippet in odds-ingest.md). Keep a fallback to the static
   files if the endpoint errors, so the page degrades gracefully.
5. Confirm on a Vercel preview that the endpoint import resolves (the
   `includeFiles: scripts/**` bundling) and the page renders FD/DK/SCORE columns.
6. After cutover, future updates are: paste a Recorder bundle → `PUT
   /api/odds-ingest`. Optionally build a small authed paste UI (textarea →
   PUT → show the returned skip report).

## Still-open data gaps (from the audit, unrelated to plumbing)
- theScore is still missing ORoY/DRoY/CoY/CPoY/Make-Miss-Playoffs — needs those
  shelves *recorded* (not a mapping issue yet). If a future Score bundle shows
  them under names `SCORE_MARKETS` doesn't have, add them there (mirror the DK fix).
- `data/fd.json` is ~3 MB shipped per load — trim unused FD fields in
  `parse_fd_import.py`, or rely on the cached GET once on Path B.

## Verify before declaring done
- `python3 scripts/odds_merge.py` smoke-test runs clean.
- Re-running all six `scripts/parse_*.py` against `data/imports/*` leaves `data/`
  byte-identical EXCEPT the intended DK columns in `outrights.json`.
- `/odds` shows DK prices for MVP and the other awards/futures markets.
