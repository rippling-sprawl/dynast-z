# Odds pipeline — overview & change log

_2026-06-12._ Summary of the `/odds` data audit and the move to a paste-and-PUT
ingest flow. Details live in the linked docs.

## The data flow

```
Recorder bundle (FD / DK / theScore)
   → scripts/parse_*.py  (CLI)   ──┐   additive merge, never deletes
   → api/odds-ingest PUT (paste) ──┴─→ scripts/odds_merge.ingest
                                         ├─ prop feed:  fd / dk / score
                                         └─ outrights:  shared awards/futures
   → data/*.json  (committed, static)   OR   Supabase odds_state (new path)
   → views/odds.html
```

Books: **FD** (FanDuel, primary layout), **DK** (DraftKings), **SCORE** (theScore).
`/data/score/*.json` is still used — all six stat files are fetched at runtime.

## 1. Audit: missing FD/DK/Score odds

Full writeup: [bugs/odds-missing-fd-dk-score.md](bugs/odds-missing-fd-dk-score.md).

Verdict: the missing DK/Score columns are mostly **"not supplied in the Recorder"**
— each was recorded from a single narrow page, so only that page's markets landed
in the bundle. FD is complete because it was recorded across the whole futures
page. A second cause — **"named differently"** — was later confirmed (see §3).

## 2. New ingest pipeline (paste a bundle, no file commits)

Full writeup + setup: [odds-ingest.md](odds-ingest.md).

- The six `scripts/parse_*.py` were refactored into pure, importable
  `merge_*` / `apply_*_outrights` functions; CLI wrappers preserve the local
  workflow (verified byte-identical via empty `git diff` after regenerating all
  of `data/`).
- `scripts/odds_merge.py` (`detect_book` + `ingest`) is the shared core; replaying
  the import bundles through it matched every committed artifact byte-for-byte.
- `api/odds-ingest.py` — `PUT` a bundle (auth'd, additive, idempotent, returns a
  skip report) → Supabase `odds_state`; `GET` serves the merged state back.
- Schema `scripts/sql/odds_state.sql`, seed `scripts/seed_odds_state.py`,
  bundling wired in `vercel.json`.
- `.vercelignore` drops `data/imports/` (~5.5 MB) and dev artifacts from deploy.

## 3. Open items

- **DK market-name mapping is incomplete.** Running a fresh DK *awards* bundle
  through `ingest()` populated nothing: the markets are present but named
  differently than `DK_EXACT`/`canon_key` in
  [../scripts/parse_dk_outrights.py](../scripts/parse_dk_outrights.py) expect —
  e.g. `Regular Season MVP`, `Offensive/Defensive Player of the Year`,
  `Coach of the Year`, `Comeback Player of the Year`, `To Miss Playoffs`,
  `NFL 2026/27 - Most Regular Season Wins`, `... AFC/NFC 1 Seed` (note the
  inconsistent `NFL 2026/27 - ` prefix). Until the map learns these, re-recording
  won't fill the DK columns.
- **`views/odds.html` not yet migrated** to the GET endpoint — both paths
  coexist; static `/data/*.json` remain live.
- **`data/fd.json` is ~3 MB** shipped on every `/odds` load — trimming unused FD
  fields (or serving via the cached GET) is the biggest remaining perf win.
