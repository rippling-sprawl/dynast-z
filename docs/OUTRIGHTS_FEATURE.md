# Outrights, Awards & Futures + Milestones

Summary of the feature that surfaces sportsbook **outright** markets — season
awards, team futures, statistical leaders, and DraftKings milestone lists — from
DraftKings (DK), FanDuel (FD), and theScore (SCORE), merged into one file and
rendered as sortable candidate tables with a fair-value consensus column.

Scoped by `data/prompts/outrights-awards.md`. For the capture/import plumbing
this rides on, see [ODDS_AUTOMATION.md](ODDS_AUTOMATION.md).

## What it covers

- **Awards** — MVP, OPOY/DPOY, OROY/DROY, Coach of the Year, Comeback of the Year.
- **Team futures** — Super Bowl winner, conference & division winners, make/miss
  playoffs, No. 1 seed.
- **Statistical leaders** — most passing / rushing / receiving yards, most wins,
  most rookie receiving yards.
- **Milestones** — DK's "Player to Have X+ Regular Season {Passing|Rushing|
  Receiving} {Yards|TDs}" lists, surfaced two ways (see below).

DK 17 canonical markets + 14 milestone thresholds, SCORE 5, FD 23 — all unioned.

## Data pipeline

Three book-specific parsers feed **one** merged file, `data/outrights.json`,
through a shared common module. Run order doesn't matter.

| File | Role |
|---|---|
| `scripts/outright_common.py` | 32-team canonicalizer, `norm_name`, `norm_american`, the `CANON` market registry, blocklist, never-clobber merge (`upsert_market` / `upsert_milestone`), load/save. |
| `scripts/parse_dk_outrights.py` | DK outright markets + milestone lists from `data/imports/dk.json`. |
| `scripts/parse_score_outrights.py` | theScore `LIST` markets from `data/imports/score.json`. |
| `scripts/parse_fd_outrights.py` | FD "field" coupons from the **parsed** `data/fd.json` (so prices match the tick-refreshed Player Props view). |

### Canonicalization

A single `CANON` registry maps each canonical key → `(title, kind, group)`, so
the three parsers can't disagree on a market's identity. Candidates merge across
books by key:

- **Teams** — by nickname (the last word is unique across all 32 NFL teams), with
  a SCORE abbreviation fast-path and aliases (JAC→JAX). So "BUF Bills" (DK),
  "Buffalo Bills" (FD), "LA Rams" (SCORE) collapse to one row; digits preserved
  for "49ers".
- **Players/coaches** — `norm_name` (lowercase, strip punctuation + Jr/Sr/II–V).

Cross-book unification examples (verified): DK "Winner" ≡ SCORE "Super Bowl
Winner" ≡ FD "Super Bowl LXI Winner"; FD's split "To Make the Playoffs AFC/NFC"
(16+16) collapse into one 32-team `make_playoffs`; DROY (rookie) kept distinct
from DPOY.

### Never-clobber merge

Each parser upserts only **its own book's** name+price per candidate, keyed by
(canonical market, candidate key). It never deletes another book's column,
another candidate, or another market — same partial-capture safety as the
player-prop files. Idempotent (byte-identical on re-run). Candidates stored
best-price-first.

File shape:

```
{
  markets: { <key>: { title, kind, group, candidates: [
    { key, names: {fd, dk, score}, prices: {fd, dk, score} }
  ] } },
  milestones: { <stat>: { title, thresholds: { <n>: { candidates: [...] } } } }
}
```

## Consumer (`views/odds.html`)

Loads `/data/outrights.json` into `OUTRIGHTS`. Two new top-level tabs:

- **Awards & Futures** — canonical markets grouped Awards / Team Futures /
  Statistical Leaders. Each opens a candidate table.
- **Milestones** — DK's threshold markets as their own section.

### FMV consensus column

Each table has an **FMV** column: the average of the books' implied
probabilities (American → probability), reconverted to American. It's a
vig-inclusive consensus (a per-market de-vig would give truer fair value — see
ODDS_AUTOMATION pending). The shortest (best) price per row is highlighted.

### Sortable tables

`buildOutrightTable(title, candidates, nameLabel)` is shared by both tabs and
renders in the **same `.odds-coupon.is-ou` style as the Player Props coupons** —
one strip per candidate (pinned name column, then hairline-divided borderless
badge columns for FMV + each book) under a single heading row, instead of a
separate bordered-box field layout. The best (shortest) book price per row is
highlighted; FMV is muted.

- **Default** — by FMV, favorites first (highest probability / shortest odds),
  nulls last. FMV header shows ▲/▼.
- **FMV header click** — toggles direction (favorites ⇄ longshots).
- **Name/Team header click** — cycles alphabetical **asc → desc → none**, where
  *none* reverts to the FMV default. Header labeled "Player" or "Team" per the
  market's `kind`.

### Milestones merged into Player Props

Besides the standalone Milestones tab, milestones merge per-player into the
existing Player Props markets: where a book has no Over/Under line for a stat, it
shows the milestone threshold nearest the player's FD/SCORE line as an over-only
cell (the "O "/"U" prefixes are dropped — milestones are yes-prices, not O/U
lines). Milestone-only players are added as rows via `synthesizeUnion`. The
threshold is excluded from the FMV line average so it doesn't distort it.

## Notes

- The original brief predated the FD capture; since `data/fd.json` now exists and
  carries the richest award set (MVP/OPOY/DPOY that DK lacks), all three books
  are wired in from the start.
- `SUPABASE_KEY` is server-side only and never reaches the browser.
