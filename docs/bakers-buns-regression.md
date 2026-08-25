# Baker's Buns — Stats & Regression

A block inside every team card on `/football/bakers-buns`, between **Notes** and **Inputs**.

Everything else on that card is an argument about what a team *is* — the offense tier, the
offensive line, the schedule, the rest. This block is the only one that looks backwards, and it asks the
other question: **which parts of last season were the team, and which parts were the bounce of
the ball.**

Three parts, each showing a 2025 number, what it is made of, and where it ranks in the field of 32
— plus, in the middle, four seasons of the two numbers that only mean anything as a pair.

---

## Three parts, because these are three kinds of number

### The two that regress

Tiles, and they carry a lean: ↑ positive regression, ↓ negative regression, or nothing.

| Tile | The read |
|---|---|
| **One-score games** | Over time every team is about .500 in games decided by a possession. 11-2 is not a skill. |
| **4th down rate** | Roughly two dozen attempts in a season. There is no sample there to be good at. |

### The trend — havoc rate and turnover margin, four seasons, by rank

Not tiles. A chart, under its own heading, and the centre of gravity of the block. **The lines are
NFL rank, 1 to 32, not the numbers themselves** — see below for why.

| Series | The read |
|---|---|
| **Havoc rate** | The sticky one — pressure is the stickiest thing a defense does, so it *repeats*. |
| **Turnover margin** | The noisy one — fumble recoveries are close to a coin flip and interception rate barely correlates season to season. A margin far from zero is the loudest single regression signal there is. |

Both were tiles once, the margin up with the regression calls and the pressure rate demoted below
them. As tiles each could state a level and neither could state the thing that actually matters
about them: **one of them holds and the other does not.** A team 3rd in pressure for four straight
years beside a margin that has been 4th, 27th, 2nd, 22nd is the whole argument in one picture, and
no pair of single-season boxes can make it. High pressure beside a poor margin is a bill coming
due; beside a good one, a margin that holds up — and *that* is the read the chart hands over
directly.

The tiles' values, ranks, counts and league middles did not go anywhere: they are the legend above
the chart, which is what keeps this from having traded numbers for a picture. **What is drawn is
the placing; what is printed is the number.**

### And two that don't regress at all

Set apart under a dashed rule and a **More Stats** heading, in a flatter treatment. Neither is a
regression call, so neither carries a lean; each carries a league comparison instead.

| Tile | Why it isn't a regression call |
|---|---|
| **Run stuff rate** | The opposite problem to the tiles above: it is *sticky*. A front that met a fifth of carries at the line will do it again, so there is no bounce here to warn about. Carried because havoc rate covers only the pass rush, and the two halves of a front come apart — the 2025 Rams were 4th in pressure rate and 31st in this. |
| **2026 dead cap** | Already spent. Nothing about it regresses. It is carried as the answer to what everything above it raises — *can this actually be fixed this year?* |

Note the two get here by opposite routes. Dead cap does not regress because it has already happened;
stuff rate does not regress because it is a real property of the defense that will still be there in
September. What they share is that neither is a finding about next season, which is the only thing
the lean arrow is for.

Dead cap originally sat in the row above with the same green-or-orange arrow, which made findings of
one type out of a list that was never one. Whether a context number is good news depends entirely on
what sits above it, which is the reader's call to make and not the tile's. Stuff rate was put here
from the start for the same reason: an arrow on a sticky number tells the reader to expect a change
that is not coming.

### Why the chart plots rank and not the numbers

**A rate in percent and a margin in whole turnovers do not share a number line.** Drawing both
meant two scales, one per side, and where two scales cross is an artefact of where each was pinned
rather than a fact about the team — the standard objection to a dual axis, and correct.

Rank is the one unit both already have. One axis, one meaning for height, and a crossing that
finally says something real: the season the defense started getting home faster than the ball was
bouncing for it.

It also settles what four seasons of raw numbers could not. **The league moves under both of
these** — pressure rates drift with the rules and with how quickly the ball comes out — so 14.2% is
not the same thing in 2022 as in 2025, while 9th is. A line that climbs here is a team climbing
past other teams, which is the only reading a multi-season view was wanted for in the first place.

**The bounds are 1 to 32 and cannot be anything else.** That is the constant frame every card is
drawn in: a flat line is a team that held its place, and two cards opened one after the other
compare directly. **1 is at the top**, and the axis says so (`NFL RANK · 1 BEST`) rather than
leaving it to be inferred from the tick column.

Gridlines are at 1 / 8 / 16 / 24 / 32 — quarters of the field, because that is where "top ten" and
"bottom third" actually fall. The numbers are mirrored to **both edges of the plot**: that is not a
second axis, it is the same axis put where the reader's eye already is when it reaches the most
recent season.

Because both series are ranks, the axis belongs to neither and is drawn in plain ink. The two
colours are spent entirely on the lines.

Colours are `--series-a` (blue, havoc) and `--series-b` (orange, margin) — deliberately **not**
`--good`/`--orange`, which this page spends on direction everywhere else and which sit 5.7 ΔE apart
under deuteranopia. The pair here clears 24 ΔE under every simulated deficiency in both themes, and
carries shape as a second channel: a circle on a solid line, a square on a dashed one.

Hovering a season gives that season's raw numbers back — `2023 · havoc 15th (15.6%) · turnover
margin 11th (+4)` — since the chart itself now shows only the placing.

### Colour semantics

The palette is the **Luck column's**, not the z-score columns'. Green is a tailwind into 2026;
orange is 2025 flattery unlikely to come again.

That inversion matters more here than anywhere else on the page, because **the orange tiles are
frequently the good numbers**. A 13-win team living off one-score games is exactly the thing this
block exists to flag — colouring its record green would say the opposite of what is meant. Denver's
11-2 in one-score games reads ↓ orange, sitting above a Context row that shows the league's best
pressure rate: a very good team, with the softest part of its record named.

### Lean thresholds

The two lean tiles only. Deliberately quintile-ish: anything tighter is inside the noise the block
exists to warn about, and gets no arrow at all — most teams are unremarkable on both of these, and
a card of coloured tiles would say nothing.

| Tile | ↑ positive | ↓ negative |
|---|---|---|
| One-score games | win pct ≤ .375 | win pct ≥ .625 |
| 4th down rate | ≤ 45% | ≥ 65% |

The turnover margin used to carry a lean here too, inverted against its own rank — ranking 1st was
the thing most likely to be handed back. Four seasons of the line say that better than one arrow
did, so it is now made by the chart rather than stated by a tile.

---

## Havoc also feeds the score

Since the Projections table gained a **Havoc** column, the pressure rate in this file is no longer
only a card number. `scripts/build_bun_havoc.py` reads the `history` block written here, blends
**75% of the most recent season with 25% of the one before**, z-scores that against the field, and
writes it into `data/nfl_projections_2026.json` as a fifth model input carrying **15%** of the
score — taken 10 points off O-Line (40 → 30) and 5 off SoS (25 → 20). Both land lower still once
the other add-on scripts take their own points: O-Line at 25% after `build_bun_coaches.py`, SoS at
15% after `build_bun_luck.py`.

Two seasons, weighted toward the recent one, because pressure is sticky but a roster is not. One
season alone takes every injury and every soft schedule at face value; an even split argues that a
two-year-old front tells you as much as the current one, which is more than the numbers support.

The weight is still short of the line's on purpose. This is a *floor* on pressure — hurries are
hand-charted and in no free feed — and one defensive number is not a defense. 15% says the model
was blind on this side of the ball and is now looking: enough to move a team a place or two, never
enough to carry one.

**The published score is moved, not rebuilt.** The sheet computes it from full-precision z-scores
while the JSON rounds each z to one decimal, so recomputing the whole sum would land every team
about 0.01 off its own published figure for nothing. Each team's score takes
`0.15·z_havoc − 0.10·z_oLine − 0.05·z_sos`, rounded to the two decimals the score is quoted in,
which leaves the four original terms at exactly the precision the sheet computed them with. The
script records what it did in `havocInput` and reverses itself exactly on a re-run, so it is safe
to run again every time this file is refreshed — and `--remove` puts the score back as it was.

Note the two havoc numbers on the page are **not** the same number and are not meant to be: the
table's column is the blend the model scores on, and the card's chart is each season's own placing,
which is how you see what the blend was arrived at. The Notes standout follows the table.

---

## Standouts — the Notes lead

**A standing arrangement, not part of this feature alone:** a team's **Notes** section opens with
every metric on the page it is **top five or bottom five** of the league in. Every data source
added to Baker's Buns from here on gets an entry in `STANDOUTS`, so being extreme in it surfaces
automatically instead of waiting for someone to write the note by hand.

The middle of a distribution is not worth a sentence — a team 17th in havoc is a team you learn
nothing about by being told so — but the tails are the whole reason a metric was collected, and
before this they were only findable by opening a card and reading every block against a memory of
the other 31 teams.

Registered today, in card order:

| Metric | Source | Rank from |
|---|---|---|
| Offensive line | PFF board | published `oLineRank` |
| Schedule | odds-based SoS | published `sosRank` (1 = easiest) |
| Rest | Sharp Football rest disparity | value, net days |
| Offense | Action Network offense tiers | published `eyeTest` tier (1 = best) |
| Havoc rate | projections file | value, the 2-season blend the score uses |
| Run stuff rate | regression file | published rank |
| Turnover margin | regression file | published rank |
| One-score record | regression file | published rank |
| 4th down rate | regression file | published rank |
| Dead cap | regression file | published rank (1 = least) |
| Markets | de-vigged outrights | value, one collapsed line |

### Adding a metric

Two ways to supply one, and the choice is not stylistic:

- **`rank()`** — the source already publishes a rank. Use it. Re-ranking the values here would be
  a second opinion that can drift from the block printing the first one.
- **`value()`** — the source publishes numbers only. Higher sorts toward 1st, so a metric whose
  good end is low is negated rather than handled by a direction flag.

`hi` and `lo` are the adjectives for the two ends. The phrase is always written from the end the
team is actually on, so a bad dead-cap number reads *"2nd highest"* rather than *"31st lowest"*,
and rank 1 drops the ordinal entirely: *"best in the league"*, not *"1st best"*.

### The tie rule

A tied block must fit **entirely inside** the five, not merely start inside it. A coarse metric
hands the same number to a whole block of teams — the offense tiers arrive in blocks of four and
five — and a plain `rank <= 5` reported every one of them as *2nd-highest in the league*. A block
that overruns the five is not a top five; it is a metric too coarse to have one, and the right
output is silence. `placeIn()` enforces this for every metric including
the markets, where books routinely hang the same price on four teams.

The field size also comes from the metric's own scores rather than `teams.length` — five of
thirty-two is a different claim from five of twelve, and a metric missing teams gets the smaller
field it earned.

### Correlated metrics collapse

The five outright markets are five prices on one opinion: a team the market loves is top five in
most of them at once. A bullet apiece would say the same thing five times and drown the metrics
that are genuinely independent, so they share one line — *"Market **top five** conference, Super
Bowl"*, or *"Every market **bottom five**"* when the board sweeps. The two ends get separate lines
rather than one sentence with a "but": top five to win a division and bottom five to win the Super
Bowl is a real read about a weak division, not a contradiction to smooth over.

### Styling

Only the discriminating part is lit. There can be six or more standouts on one team, which rules
out the whole-bullet tint the luck and staff calls get — that works for one line and turns a run of
six into a wall. The metric name stays the ordinary note colour, the **placing is cyan** because it
is the new information and the only part a reader scans for, and the value trails in grey as the
receipt.

Cyan rather than green or orange on purpose: **a placing is not a verdict**. Being first in
turnover margin is bad news for next season and first in dead cap is good news, and one colour has
to carry both.

### Known overlap

Several teams carry hand-filed notes that restate their schedule and rest standing (*"4th-easiest
schedule in the league by Vegas win totals"*, *"Net rest −9 days, 29th in the league"*). Those were
written per team before this existed, so for the extreme teams they now appear twice — once
generated, once filed. The filed versions usually say more than the generated line does, so nothing
is deleted automatically; they can be cleared by hand from the note store if the duplication
grates.

---

## Definitions, and the judgement calls behind them

**Regular season only, throughout.** The playoff field is not the league; a seven-game postseason
sample would make the twelve teams that reached it incomparable with the twenty that did not.

- **Pressure** is a dropback on which the quarterback was **sacked or hit**. This is a *floor*, not
  PFF's number: hurries are charted by hand and are in no free feed, so a pressure here is one that
  put a defender's hands on the passer. The rate is per **dropback** — scrambles included, since a
  scramble is a dropback that broke down — which is the denominator that keeps a team facing 700
  dropbacks comparable with one facing 550.
- **A stuff** is a carry the defense held to **zero yards or fewer**. Zero and not minus one: a run
  met at the line for no gain is the same defensive win as one met a yard behind it, and drawing
  the line at zero nearly doubles the sample — about 2,030 stuffs in 2025 against the 1,195 plays
  nflverse flags `tackled_for_loss`, every one of which lost yardage. That column is accurate but
  it answers a different question, which is why this is computed from `yards_gained` instead.

  The denominator is **running-back and fullback carries only**, joined by `rusher_player_id`
  against nflverse's players release. Scrambles are obviously somebody else's stat, but so are
  designed quarterback runs: a team that keeps the ball with its quarterback twenty times a game is
  describing its own offense, not the defense that met it. Leaving them in moves teams a mean of
  1.75 places and the 2025 Broncos nine of them. It is also what the published versions of this
  metric do — filtered this way the 2025 Rams come out second-lowest at 12.1%, which is where FTN
  has them, and that agreement is the check that the definition is right rather than merely
  arithmetically consistent.
- **Turnovers** are counted **from scrimmage**: interceptions and fumbles lost on run or pass plays.
  Muffed punts and kick fumbles are left out on purpose — on a kicking play nflverse's `posteam` is
  the kicking team, so the muff belongs to the side listed as the defense, and attributing it
  correctly costs more than the one or two plays a year it moves.
- **One-score** is a final margin of **eight points or fewer** — a touchdown and the two-point
  conversion, the largest deficit that is still one possession.
- **4th down** counts only the plays a team *chose to run*: pass and run attempts on fourth down.
  Punts and field goals are not conversion attempts, and a kneel is not one either.
- **Dead cap** is cap charged in the current league year to players no longer on the roster. The
  tile compares against the league **median**, not the mean — see below.

---

## Data sources

| Source | Feeds | URL |
|---|---|---|
| nflverse play-by-play | Havoc, run stuff rate, turnovers, one-score, 4th down | `github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{season}.csv.gz` |
| nflverse play-by-play, ×3 prior seasons | The trend's havoc and turnover margin | same URL, one release per season |
| nflverse players | Ball-carrier position, for the stuff-rate denominator | `github.com/nflverse/nflverse-data/releases/download/players/players.csv` |
| Over The Cap | Dead cap, cap space, active spending | `overthecap.com/salary-cap-space` |

The players file is all-time and about 7 MB, so it is fetched **once per run** and handed to every
season's pass rather than pulled per season. It exists only because the play-by-play names the ball
carrier with a `gsis_id` and never a position, and stuff rate cannot tell a running back's carry
from a quarterback's without that join.

### Why nflverse and not ESPN

ESPN's team-statistics endpoint carries `sacks`, `hurries`, `turnOverDifferential` and
`fourthDownConvPct` already, and would have been one small GET per team. It was rejected because it
publishes **season totals with no play table**, and a *rate* needs a denominator ESPN does not
expose — opponent dropbacks faced. Deriving one by summing each opponent's full-season pass
attempts overcounts, because a team plays most opponents once.

nflverse ships the plays themselves, which makes every number here exact rather than approximate,
and it is **the only free feed carrying `qb_hit`** — without which the pressure column cannot be
computed at all. The same argument covers stuff rate, which needs per-play rushing yardage that no
box-score API exposes.

The rest of the field was checked and rejected for the stuff-rate column specifically:

| Rejected | Why |
|---|---|
| nflverse `stats_team` | Has `def_tackles_for_loss`, but as a season total that folds in sacks and ships no run denominator. Not convertible to a rate. |
| nflverse `ftn_charting` | Carries `n_defense_box`, `n_blitzers` and similar — good run-defense *context* for some later feature, but no run outcome. |
| nflverse `pbp_participation`, `pfr_advstats` | Personnel and coverage respectively. Neither carries run outcomes. |
| FTN adjusted line yards | The canonical published Stuffed Rate, and the number this column agrees with — but the page 403s to scripts and sits behind a subscription. |
| PFF run-defense win rate, ESPN run stop win rate, TruMedia | All paywalled, no public API. |

### Why the OTC page and not a dead-money page

`overthecap.com/salary-cap-space` publishes three league years as three tables under one URL
(2026 / 2027 / 2028 tab strip), and the Dead Money column is already in each. The season is picked
**by position in the tab strip**, not by reading a year off a row — the rows carry none. OTC names
teams by nickname alone, so the nickname is the join key back onto this site's abbreviations.

---

## Fetching mechanism

One script, run by hand, writing one committed JSON snapshot the page fetches from the CDN.

```
scripts/fetch_nfl_regression.py  ──▶  data/nfl_regression_2026.json
                                      data/nfl_regression_2026_meta.json
```

```bash
python3 scripts/fetch_nfl_regression.py                  # last season + this cap year
python3 scripts/fetch_nfl_regression.py --season 2024 --cap-season 2025
python3 scripts/fetch_nfl_regression.py --history 1      # skip the trend downloads
python3 scripts/fetch_nfl_regression.py --reuse-cap      # keep the dead money already on disk
python3 scripts/fetch_nfl_regression.py --keep-pbp       # leave the CSVs in /cache
```

**Defaults** resolve to the last *finished* season and the following league year. A season is named
for the year it starts, so the last completed one is this year only once we are past the February
that ended it.

**The download** is ~19 MB gzipped, parsed streaming through `csv.DictReader` over a
`gzip`/`io.BytesIO` wrapper — it is never fully expanded to disk or held in memory as text. It
lands in `cache/pbp_{season}.csv.gz` and is **deleted on success** unless `--keep-pbp` is passed; a
finished season's play-by-play never changes, so a second run in the same afternoon reuses the
cached copy rather than pulling 19 MB again.

**One pass over the season** feeds every counter. A play increments both sides of it — the
offense's giveaway is the defense's takeaway — so the league's margins sum to zero by construction
rather than by coincidence.

**The trend costs one download per extra season** and nothing else. `--history N` sets the span
(default 4, the current season included); the current season is *not* re-downloaded, because it has
already been tallied for the worksheet. Each prior season goes through the same `tally()` and then
through `season_trend()`, which keeps only the two numbers the chart plots and **ranks each within
that season's field** — four seasons of the full block would be four times the file for numbers no
card reads. The ranks are computed here, by the same `rank_by()` the worksheet uses, rather than
derived in the page at render time: a rank recomputed at render is a second opinion that can drift
from the one printed beside it in the legend. A season that will not parse, or
that fails the 32-team or margins-sum check, is **skipped rather than fatal**: the card plots
whatever seasons it is handed, and one bad 2022 is no reason to refuse to publish 2025. The count
is printed, because a silently two-year "last four years" is worse than a loud one.

**`--reuse-cap`** takes dead money from the JSON already on disk instead of scraping Over The Cap,
and rebuilds every on-field number as normal. OTC has no API and drops connections from whole
networks, which would otherwise make a machine that can reach nflverse unable to rebuild anything
at all. It is a flag and not a silent fallback: the money is the one column here that moves between
runs, and a run that quietly shipped March's cap sheet in September would be worse than one that
failed.

**Both fetches shell out to `curl -sL`.** Over The Cap serves an interstitial to curl's default
user-agent, so that request passes a browser string; the nflverse asset redirects to a signed S3
URL and does not care either way. (Note the opposite constraint in `fetch_nfl_schedule.py`, where a
browser UA gets you an Akamai "Access Denied" page from ESPN.)

**Abbreviation fixes:** nflverse writes `LA` and `WAS`; this site uses `LAR` and `WSH`. Everything
else already agrees across the schedule, logo and projection files.

### Verification before writing

The script refuses to overwrite a good file unless all of these hold:

- 32 teams
- 272 scored games
- **league turnover margins sum to exactly 0** — if they do not, a play was attributed to one side
  and not the other
- every team has a dead-money figure
- **every team faced at least 200 running-back carries**, and **no more than 25 ball carriers went
  unmatched** against the players file

The last one is there because the stuff-rate denominator is the only number in the block that
depends on a second file, and its failure mode is silent. A `players.csv` that arrived empty, or
that has drifted off the play-by-play's ids, matches nobody — every carry is skipped, every team
ships a tidy `0.0%`, and every other gate on this page passes. So both ends are checked: that
carriers were found at all, and that the ones that were not are a handful rather than the league.
The floors are loose on purpose — a real team faces around 370 carries and the thinnest in 2025
faced 299, while 2025 matched every single id.

And, once the trend is built, `verify_history()` checks that **the last point of every line is the
worksheet's number and rank exactly** — value and placing, both series, all 32 teams. Both are
computed from the same tally by the same helpers, so a mismatch means one of the two paths was
edited and the other was not, which would put a chart on the card that quietly disagrees with the
legend directly above it. That is the one failure here a reader would never catch.

### Output shape

```jsonc
{
  "statsSeason": 2025,
  "capSeason": 2026,
  "note": "…definitions, in the file itself…",
  "sources": { "onField": "…", "players": "…", "deadCap": "…",
               "trend": ["…", "…", "…", "…"] },
  "league": { "pressureRate": 14.9, "sackRate": 6.5, "stuffRate": 17.1,
              "fourthDownPct": 55.9, "oneScoreGames": 9.1,
              "deadCap": 43720809, "deadCapMedian": 35230539 },

  // The chart's series, oldest season first, keyed by team rather than by
  // season because that is how a card reads it: one team's four points, not
  // four leagues. The chart plots the two *Rank* fields; the raw values ride
  // along for the hover tooltip. For the current season `havoc`/`havocRank`
  // must equal `pressureRate`/`rank` below, and `margin`/`marginRank` must
  // equal `diff`/`rank` — verify_history() refuses to write a file where they
  // disagree.
  "historySeasons": [2022, 2023, 2024, 2025],
  "history": {
    "SEA": [{ "season": 2022, "havoc": 15.8, "margin":  2, "havocRank": 12, "marginRank": 13 },
            { "season": 2023, "havoc": 15.0, "margin":  4, "havocRank": 18, "marginRank": 11 },
            { "season": 2024, "havoc": 17.5, "margin": -1, "havocRank":  3, "marginRank": 17 },
            { "season": 2025, "havoc": 16.0, "margin":  0, "havocRank": 13, "marginRank": 13 }]
  },

  "teams": {
    "SEA": {
      "havoc":      { "pressureRate": 16.0, "sackRate": 6.8, "pressures": 111,
                      "sacks": 47, "dropbacks": 693, "rank": 13 },
      // rushes is RB/FB carries faced, not every run play — see Definitions.
      "runDefense": { "stuffRate": 19.7, "stuffs": 69, "rushes": 350, "rank": 7 },
      "turnovers":  { "diff": 0, "takeaways": 26, "giveaways": 26, "rank": 13 },
      "oneScore":   { "w": 6, "l": 3, "t": 0, "games": 9, "pct": 0.667, "rank": 7 },
      "fourthDown": { "pct": 58.3, "conv": 7, "att": 12, "rank": 15 },
      "deadCap":    { "amount": 655535, "capSpace": 20512959,
                      "spending": 293245279, "rank": 1 }
    }
  }
}
```

`rank` is **1 = highest value** in every block except `deadCap`, where **1 = lowest** (the team
paying the least). `havocRank` and `marginRank` follow the same rule and the same tie handling —
1 is the highest pressure rate and the best margin. The rank is a statement about the field, so it is computed after the whole field
is built. Ties share the better number and the ones behind them skip — two teams at −2 are both
18th and the next is 20th, the way a standings table reads.

`league` carries the middle of each column so a card can say "against a league average of …"
without every card recomputing it from 32 objects.

**Dead money carries a median as well, and the median is what the page shows.** The on-field
columns are near enough symmetric for a mean to describe them — pressure rate runs about 9% to 22%
around a middle of 15 — but dead money is a long right tail. The 2026 spread runs from Seattle's
$0.7M to Miami's $179M, and that one figure drags the mean ($43.7M) about $9M above the team
actually sitting 31st; the median is $35.2M. A tile comparing a team against a number no team is
near would be worse than showing nothing.

### When to re-run

- **Once, after a season ends**, for the on-field half — after that its numbers are static forever.
- **Whenever dead money moves** (releases, trades, June 1 designations) for the cap half. Both
  halves are rebuilt together; the on-field pass is idempotent, so re-running for cap reasons costs
  nothing but the download.

---

## Rendering

| File | What it holds |
|---|---|
| `views/football/bakers-buns.html` | `REG_TILES`, `CONTEXT_TILES` (run stuff rate, then dead cap), `regTile()`, `regRow()`, `regressionInner()`, and the `REG_URL` fetch |
| `styles/primary/bakers-buns.css` | `.tc-reg-block`, `.tc-reg-grid`, `.tc-reg-tile`, `.lean-up` / `.lean-down`, `.tc-reg-context`, `.tc-reg-vs` |

The file joins the page's existing `Promise.all` rather than chaining after it, and **swallows its
own failure** — the same contract the coaching staffs use. It is one block of a card, not the page,
so a file that never arrives drops that block rather than the table. It is whole-block-or-nothing:
half a worksheet would read as a team with nothing to say about it rather than as a file that did
not arrive.

One builder per tile, each handed the team's row and the league's middle, returning the tile rather
than its markup — so the lean rules stay together and readable, which is where the block's whole
argument lives and the part most likely to be argued with. Both rows share one `regTile()`, because
they differ in a single line: a regression tile closes on its lean, a context tile closes on the
league's middle. Two near-identical builders would have made that difference harder to see than it
is. Each tile carries a `title` explaining the metric and why it does or does not repeat.

Tiles are `auto-fit, minmax(…, 1fr)` rather than a fixed column count — the card is a dialog
ranging from a phone's full width to 760px, and the rows have to fall to two columns and then one
without any of it being placed by rule. The context row uses a wider `210px` minimum than the
regression row's `148px`, so it never goes more than two across and reads as a footnote to the row
above rather than as a second set of findings.

The value stays the same near-white in every regression tile; the lean is carried by a left edge, a
faint wash, and the caption. A tinted number would put value and direction on the same channel and
make an orange 11-2 look like a bad record. The context tiles have all three of those signals taken
away — no accent edge, no wash, no arrow, and a lighter value — leaving a plain bordered box. The
dashed rule and the `More Stats` heading do the actual separating, because tile styling alone was too
quiet to carry it: a grey tile is also what a regression tile with nothing to say looks like.

---

## Sources section

Both feeds are documented on the page itself under **Sources**, alongside the inputs that actually
feed the composite score — with the definitions restated there, since a reader questioning a number
looks there rather than here.
