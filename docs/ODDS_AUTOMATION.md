# Odds Automation — Recorder Bookmarklet & Import Pipeline

Working notes for automating the DraftKings (DK), FanDuel (FD), and theScore
(SCORE) odds sources. Data is season-long NFL futures (slow-moving, refreshed
~weekly), so no always-on scraper is needed.

## Architecture (decided)

- **Capture:** browser bookmarklet → clipboard. **No 3rd-party extension** (hard
  constraint). The bookmarklet runs in the logged-in sportsbook tab, monkeypatches
  `fetch` + `XHR`, and records JSON API responses. Because it's a real logged-in
  session it inherits live cookies + PerimeterX / Cloudflare / Akamai tokens —
  there is no bot to detect. It only reads same-page responses and writes to the
  clipboard, so the book's CSP (which blocks cross-origin POST) is never in the way.
- **Persistence destination (target):** Supabase / blob storage (not git commit).
  `SUPABASE_URL` + `SUPABASE_KEY` live in `.env`; the key is **server-side only**
  and must never reach the browser. Accessed via `supabase_request()` in
  `server.py` (PostgREST, Bearer key).

## Anti-bot landscape

| Book | Protection | Tokens / notes |
|---|---|---|
| FanDuel | PerimeterX | `x-px-context`, `_px3`/`_pxvid` cookies, `_ak` app key — all session-bound secrets |
| DraftKings | Akamai Bot Manager | the source with many missing markets |
| theScore | Cloudflare | GraphQL persisted-query endpoints on `sportsbook.us-nc.thescore.bet` |

theScore Bet GraphQL endpoints seen: `CompetitionDrawerContent`,
`SeeAllLinesModal`, `CompetitionPageSectionOtherTabsNode`. Market types:
**TOTAL** (Over/Under lines) and **LIST** (outright/award markets).

## Blocklist

A domain blocklist is applied in **both** the live Recorder (skip recording) and
the import parser (drop on parse). User curates the list; `datadoghq.com` was the
first entry, `launchdarkly.com` added as the other pure-telemetry host.

Hostname matching has three cases — exact, dot-subdomain (`.datadoghq.com`), and
**hyphen sibling** (`-datadoghq.com`). The hyphen case is essential:
`browser-intake-datadoghq.com` joins with a hyphen, not a dot, so a dot-only
check silently misses the main ingest host (was leaking ~48 captures).

## Files

- `scripts/odds-recorder.js` — readable bookmarklet source. Floating panel with
  Copy bundle / Download / Clear / Close. Bundle shape:
  `{capturedAt, page, host, captures:[{url,method,status,contentType,body}]}`.
- `scripts/odds-recorder.bookmarklet.txt` — minified `javascript:` one-liner
  (generated from the source; regenerate after editing the source).
- `scripts/odds-recorder.install.html` — drag-to-install page.
- `scripts/parse_score_import.py` — parses `data/imports/score.json` →
  `data/score/<stat>.json`. Transforms into the exact shape `buildScoreIndex`
  already reads, so **no frontend changes** are needed.
- `scripts/parse_dk_import.py` — parses `data/imports/dk.json` → `data/dk.json`
  in DK's native `markets`+`selections` shape that `buildDkIndex` reads.
- `scripts/parse_fd_import.py` — parses `data/imports/fd.json` → `data/fd.json`
  in FanDuel's native `{layout, attachments}` shape (see below).
- `data/imports/` — raw captured bundles (one per book).
- `data/score/*.json` — per-stat consumer files:
  `passing_yards, passing_tds, rushing_yards, receiving_yards, receiving_tds, wins`.

## Consumer contract (`views/odds.html`)

- Reads `/data/fd.json`, `/data/dk.json`, and `/data/score/<n>.json` for
  `SCORE_FILES = [passing_yards, passing_tds, receiving_yards, receiving_tds, rushing_yards, wins]`.
- `buildScoreIndex(files)` expects `file.data.page` with `page.title` (→ statKey),
  then `pageChildren[].sectionChildren[].marketplaceShelfChildren[].markets[]`.
  Per market the name is stripped via
  `.replace(/\s+Total\s+.*$/i,'').replace(/\s+Regular Season.*$/i,'')`; per
  selection it reads `s.name.cleanName` (Over/Under), `s.points.decimalPoints`,
  `s.odds.formattedOdds`.

## FanDuel parser (`parse_fd_import.py`)

FanDuel is the **primary** source: `odds.html` loads `data/fd.json` as the base
layout (`data.layout` + `data.attachments.markets`) and only then unions DK and
theScore prices on top via `synthesizeUnion()`. So the parser's only job is to
regenerate `data/fd.json` in FanDuel's own native shape — no frontend changes.

Two endpoints in the bundle are consumed (everything else, incl. PerimeterX /
Amplitude / Spotify / Datadog telemetry, is ignored or blocked):

- `content-managed-page?...customPageId=nfl` — the **complete** page snapshot.
  Its body *is* the `{layout, attachments}` shape of `data/fd.json` (all 11 tabs,
  ~283 markets), regardless of which tab was open when captured.
- `getMarketPrices` — live odds ticks. Folded into the matching runners by
  `selectionId`, refreshing `winRunnerOdds` so prices are as fresh as the capture.

Consumer reads only `layout.{tabs,cards,coupons,tabsDisplayOrder,defaultTab}` and
per runner `runnerName` (`"Lamar Jackson Over 3200.5"`) +
`winRunnerOdds.americanDisplayOdds.americanOdds`.

Note: unlike DK/theScore (per-subcategory captures), FD's snapshot is the whole
page. We still **merge by id** rather than replace, for consistency and safety —
a narrower future capture can only add/update, never drop markets. (Trade-off: a
market FanDuel genuinely pulls down won't disappear until a manual clear.)

## Outright / award / futures pipeline (`data/outrights.json`)

The player-prop parsers above keep only Over/Under markets. The **outright**
markets every book also serves — season awards (MVP, OPOY/DPOY, OROY/DROY, Coach
/ Comeback of the Year), team futures (Super Bowl, conference & division winners,
make/miss playoffs, No. 1 seed), statistical leaders (most passing/rushing/
receiving yards, most wins), and DK's "Player to Have X+" milestone lists — are
handled by a parallel set of parsers that all feed **one** merged file,
`data/outrights.json`, read by the "Awards & Futures" + "Milestones" tabs.

- `scripts/outright_common.py` — shared helpers: the 32-team canonicalizer
  (teams merge by nickname — the last word is unique across the league — with a
  SCORE abbreviation fast-path), player/coach `norm_name`, American-odds
  normalization, the **canonical-market registry** (`CANON`: the single source
  of a market's title/kind/group, so the three parsers can't disagree), and the
  never-clobber merge into `data/outrights.json`.
- `scripts/parse_dk_outrights.py` — DK outright markets + milestone lists.
- `scripts/parse_score_outrights.py` — theScore LIST markets.
- `scripts/parse_fd_outrights.py` — reads the **parsed** `data/fd.json` (its
  field markets), not the raw bundle, so FD outright prices match the
  tick-refreshed prices the Player Props view already shows.

Run order doesn't matter; each parser merges only **its own book's** name+price
per candidate, keyed by (canonical market, candidate key), and never deletes
another book's column, another candidate, or another market — the same
partial-capture safety as the player-prop files. Candidates are stored
best-price-first. File shape: `{markets:{<key>:{title,kind,group,candidates:[
{key,names:{fd,dk,score},prices:{fd,dk,score}}]}}, milestones:{<stat>:{title,
thresholds:{<n>:{candidates:[…]}}}}}`.

Cross-book unification examples (verified): DK "Winner" ≡ SCORE "Super Bowl
Winner" ≡ FD "Super Bowl LXI Winner"; FD's split "To Make the Playoffs AFC/NFC"
(16+16) collapse into one 32-team `make_playoffs`; DROY (rookie) is kept distinct
from DPOY (player of the year). Counts: DK 17 canonical markets + 14 milestone
thresholds, SCORE 5, FD 23.

**Consumer (`views/odds.html`).** Loads `/data/outrights.json` into `OUTRIGHTS`.
The "Awards & Futures" tab lists canonical markets grouped Awards / Team Futures
/ Statistical Leaders; each opens a candidate table with an **FMV** consensus
column (average of the books' implied probabilities, reconverted to American)
plus a column per book, best (shortest) price highlighted. The "Milestones" tab
lists DK's threshold markets. Milestones are also **merged per-player into Player
Props**: where a book has no Over/Under line for a stat it shows the milestone
threshold nearest the player's FD/SCORE line as an over-only cell (no "O "/"U"),
and milestone-only players are added as rows. The threshold is excluded from the
FMV line average (it's a yes-price, not an O/U line).

FanDuel note: the brief that scoped this work predated the FD capture; since
`data/fd.json` now exists and carries the richest award set (MVP/OPOY/DPOY that
DK lacks), all three books are wired in from the start rather than left as a TODO.

## Merge semantics (important)

Partial captures must **never delete** markets. The parsers union by id (FD) or
market name (DK/SCORE): existing entries load, freshly-captured ones override on
conflict, nothing is dropped. This is why a capture that only expanded 5 of 32
team-wins drawers still preserves all 32 — it refreshes the 5 and keeps the 27.

## Status

**Done:** all three books parse to their consumer files.
- theScore → 6 `data/score/*.json`: passing_yards 12, passing_tds 22,
  rushing_yards 20, receiving_yards 37, receiving_tds 27, wins 32 (all teams
  preserved; 5 refreshed). 48 Datadog/LaunchDarkly noise captures blocked.
- DraftKings → `data/dk.json` (native `markets`+`selections`).
- FanDuel → `data/fd.json`: 283 markets / 792 coupons / 11 tabs, all ids
  preserved on merge; 74 live `getMarketPrices` ticks folded into runners.

**LIST/award + outright markets** are now parsed too — see the outright pipeline
section above (`data/outrights.json`, "Awards & Futures" / "Milestones" tabs).

### Pending

- Build DK + FD endpoint manifests for a streamlined "capture everything" pass.
- Stand up Supabase `odds_data` table + `POST /api/odds/import` endpoint.
- Switch `odds.html` read path to `GET /api/odds/fd|dk|score` (server reads
  Supabase with cache).
- To fully refresh `wins`, re-capture expanding all 32 team-wins drawers (merge
  fills in over time regardless).
- Outright FMV is a vig-inclusive consensus of book prices; a per-market de-vig
  (normalize a winner market's prices to sum to 1) would give a truer fair value.
