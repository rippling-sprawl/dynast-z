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
- `scripts/parse_dk_outrights.py` — `DK_EXACT` + prefix/suffix stripping in
  `canon_key` maps DK's `Regular Season MVP`, OPoY, DPoY, CoY, CPoY,
  `To Miss Playoffs`, `Most Regular Season Wins`, AFC/NFC 1-Seed.
- `views/odds.html` — `outrightKeyForFieldCoupon()` now maps award/playoff coupon
  titles (not just team futures), so the **FD field-coupon view** of MVP/awards
  borrows DK/SCORE columns from `outrights.json`. (Without this, only the
  Awards & Futures *table* view showed DK/SCORE; the FD coupon route showed dashes.)

All of the above is **committed to `main`** (`MAJOR | DK data fix`, `vercel fix`,
and the odds.html field-coupon fix). `data/outrights.json` carries the DK award
columns (MVP = 121 prices, etc.). The static-file `/odds` path is fully working;
the Supabase path below is what's left.

⚠️ **vercel.json does NOT declare the function.** The
`functions: {"api/odds-ingest.py": {includeFiles: "scripts/**"}}` block was
**removed** — it failed the deploy ("pattern doesn't match any Serverless
Functions") while the endpoint was dormant. When activating (Path B), in this
order: (1) confirm `api/odds-ingest.py` is in the deploy, (2) re-add the
`functions` block, (3) verify on a **preview deploy** that the build passes and
the endpoint can `import odds_merge` (i.e. `scripts/**` actually bundled). If the
glob still won't match/bundle, fall back to co-locating the lib under `api/`
(e.g. `api/_odds_merge.py` + `api/_outright_common.py`, imported without sys.path
games) so no `includeFiles` is needed.

## Migrate to Supabase (these need the human's dashboards)
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
