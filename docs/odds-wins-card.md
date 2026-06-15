# Regular Season Wins card — main-line selection & milestone ladders

How the per-team **Regular Season Wins** O/U card on `/odds` assembles its
default line and its milestone ladder across all three books (FD / DK / SCORE).

## The problem

Wins markets are published by every book as a **stack of alternate totals**, not
a single line. FanDuel, for instance, lists a team at 2.5 / 3.5 / 4.5 / 5.5 / 6.5
wins, each with its own Over/Under price. DraftKings does the same. There is no
flag in the feed marking which total is "the line" — the book just shows the one
nearest even money in its primary slip.

Two bugs followed from treating these naively:

1. **DK column blank, then wrong.** DK serves wins under
   `marketType/v1/markets` (not the `leagueSubcategory/v1/markets` path the other
   markets use), so the parser skipped them entirely. Once the path was added,
   `buildDkIndex` collapsed all alternates onto the *last* line it saw — a +500
   longshot — instead of the balanced total.
2. **FD default wrong.** `buildOuBody` kept the *first* alternate's number but the
   *last* alternate's prices, producing impossible pairings.

## The rule

> The default (displayed) line is the total whose **Over/Under odds are closest
> to −110 / +110** — the most balanced pair. Every other total is a **milestone**.

Example the user cited: Baltimore Ravens **Over 11.5 +115 / Under 11.5 −135** is
the balanced pair, so 11.5 is the default; 9.5 / 10.5 / 12.5 / 13.5 drop into the
milestone ladder.

"Most balanced" = minimum `|probOver − probUnder|`, with American→implied-prob
via `americanToProb`.

## Where it's implemented (`views/odds.html`)

- **`buildDkIndex`** — groups a market's selections by line (line read from
  `selection.points` when numeric, else parsed from the label; DK wins ship
  `points` as a flat number like `2.5`, unlike Score's `{decimalPoints}`), then
  picks the line with the most balanced O/U as the main line.
- **`buildOuBody`** — `byPlayer` maps `player -> { <line>: { O, U } }`. Per team
  it selects the balanced FD main line for the card, routes the other totals into
  an `fdMilestones` array (`{line, odds}`), and merges those with the DK/Score
  milestone entries:
  ```js
  const milestones = fdMilestones.length
    ? dkMilestones.concat(fdMilestones).sort((a, b) => a.line - b.line)
    : dkMilestones;
  ```
- **FMV** then averages whichever books supplied a default line.

## Milestone ladders (the "Player Props"-style panels)

Wins milestones are first-class, exactly like player-prop milestones — not noise.

- **SCORE** publishes `"<Team> Regular Season Milestone Wins"` LIST markets
  (1+ … 16+ ladders). `parse_score_outrights.py` (`MILESTONE_WINS_RE`) folds each
  into `milestones["wins"][threshold]` keyed by team, via `upsert_milestone`,
  using `FULL_NAME[abbr]` for display.
- **FD** alternates feed the same ladder through `fdMilestones` (above).
- **DK** alternates likewise.
- `buildMilestoneIndex` is book-agnostic (`p.dk || p.score || p.fd`);
  `renderMilestoneStat` special-cases `isWins` for the `" wins"` unit and the
  `Team` column label.

## Parser path note

DK player props **and** outrights now accept both market endpoints:

```python
MARKET_PATHS = ("leagueSubcategory/v1/markets", "marketType/v1/markets")
# kept in sync across parse_dk_import.py and parse_dk_outrights.py
```

## Status

Verified by simulation against committed data: FD main lines land on
Ravens 11.5 (matches the cited example), ARI 4.5, KC 9.5; DK lands on ARI 3.5,
ATL 6.5. `data/dk.json` holds all 32 teams' wins markets.
