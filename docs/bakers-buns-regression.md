# Baker's Buns — Stats & Regression

A block inside every team card on `/football/bakers-buns`, between **Notes** and **Inputs**.

Everything else on that card is an argument about what a team *is* — the eye test, the offensive
line, the schedule, the rest. This block is the only one that looks backwards, and it asks the
other question: **which parts of last season were the team, and which parts were the bounce of
the ball.**

Five tiles in **two rows**, each showing a 2025 number, what it is made of, and where it ranks in
the field of 32.

---

## Two rows, because these are two kinds of number

### Row one — the three that regress

These carry a lean: ↑ positive regression, ↓ negative regression, or nothing.

| Tile | The read |
|---|---|
| **Turnover margin** | Fumble recoveries are close to a coin flip and interception rate barely correlates season to season. A margin far from zero is the loudest single regression signal there is. |
| **One-score games** | Over time every team is about .500 in games decided by a possession. 11-2 is not a skill. |
| **4th down rate** | Roughly two dozen attempts in a season. There is no sample there to be good at. |

### Row two — the two that don't

Set apart under a dashed rule and a **Context** heading, in a flatter treatment. Neither is a
regression call, so neither carries a lean; each carries the league's middle instead.

| Tile | Why it isn't a regression call |
|---|---|
| **Havoc rate** | The opposite case — pressure is the stickiest thing a defense does, so it *repeats*. It is what says whether the turnover margin above it was earned or borrowed: high pressure beside a poor margin is a bill coming due; beside a good one, a margin that holds up. |
| **2026 dead cap** | Already spent. Nothing about it regresses. It is carried as the answer to what the three above raise — *can this actually be fixed this year?* |

These two originally sat in the same row with the same green-or-orange arrow. That made five
findings of one type out of them, and quietly claimed that a low pressure rate predicts decline,
which it does not. Whether a context number is good news depends entirely on the row above it,
which is the reader's call to make and not the tile's.

### Colour semantics

The palette is the **Luck column's**, not the z-score columns'. Green is a tailwind into 2026;
orange is 2025 flattery unlikely to come again.

That inversion matters more here than anywhere else on the page, because **the orange tiles are
frequently the good numbers**. A 13-win team living off one-score games is exactly the thing this
block exists to flag — colouring its record green would say the opposite of what is meant. Denver's
11-2 in one-score games reads ↓ orange, sitting above a Context row that shows the league's best
pressure rate: a very good team, with the softest part of its record named.

Turnover margin is the one tile whose lean is inverted against its own rank: ranking 1st is the
thing most likely to be handed back.

### Lean thresholds

Row one only. Deliberately quintile-ish: anything tighter is inside the noise the block exists to
warn about, and gets no arrow at all — most teams are unremarkable on most of these, and a card of
three coloured tiles would say nothing.

| Tile | ↑ positive | ↓ negative |
|---|---|---|
| Turnover margin | diff ≤ −7 | diff ≥ +7 |
| One-score games | win pct ≤ .375 | win pct ≥ .625 |
| 4th down rate | ≤ 45% | ≥ 65% |

Across the 96 regression tiles in the league this lands at **26 up / 23 down / 47 neutral** — the
tiles that light up mean something.

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
| Eye test | the sheet | value, 0-10 |
| Havoc rate | regression file | published rank |
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

A tied block must fit **entirely inside** the five, not merely start inside it. The eye test is
scored in whole numbers, so eight teams can share a 7 — and a plain `rank <= 5` reported all eight
as *2nd-highest in the league*. Eight teams tied is not a top five; it is a metric too coarse to
have one, and the right output is silence. `placeIn()` enforces this for every metric including
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
| nflverse play-by-play | Havoc, turnovers, one-score, 4th down | `github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{season}.csv.gz` |
| Over The Cap | Dead cap, cap space, active spending | `overthecap.com/salary-cap-space` |

### Why nflverse and not ESPN

ESPN's team-statistics endpoint carries `sacks`, `hurries`, `turnOverDifferential` and
`fourthDownConvPct` already, and would have been one small GET per team. It was rejected because it
publishes **season totals with no play table**, and a *rate* needs a denominator ESPN does not
expose — opponent dropbacks faced. Deriving one by summing each opponent's full-season pass
attempts overcounts, because a team plays most opponents once.

nflverse ships the plays themselves, which makes every number here exact rather than approximate,
and it is **the only free feed carrying `qb_hit`** — without which the pressure column, the one
sticky number in the block, cannot be computed at all.

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
python3 scripts/fetch_nfl_regression.py --keep-pbp       # leave the CSV in /cache
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

**Both fetches shell out to `curl -sL`.** Over The Cap serves an interstitial to curl's default
user-agent, so that request passes a browser string; the nflverse asset redirects to a signed S3
URL and does not care either way. (Note the opposite constraint in `fetch_nfl_schedule.py`, where a
browser UA gets you an Akamai "Access Denied" page from ESPN.)

**Abbreviation fixes:** nflverse writes `LA` and `WAS`; this site uses `LAR` and `WSH`. Everything
else already agrees across the schedule, logo and projection files.

### Verification before writing

The script refuses to overwrite a good file unless all four hold:

- 32 teams
- 272 scored games
- **league turnover margins sum to exactly 0** — if they do not, a play was attributed to one side
  and not the other
- every team has a dead-money figure

### Output shape

```jsonc
{
  "statsSeason": 2025,
  "capSeason": 2026,
  "note": "…definitions, in the file itself…",
  "sources": { "onField": "…", "deadCap": "…" },
  "league": { "pressureRate": 14.9, "sackRate": 6.5, "fourthDownPct": 55.9,
              "oneScoreGames": 9.1,
              "deadCap": 43720809, "deadCapMedian": 35230539 },
  "teams": {
    "SEA": {
      "havoc":      { "pressureRate": 16.0, "sackRate": 6.8, "pressures": 111,
                      "sacks": 47, "dropbacks": 693, "rank": 13 },
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
paying the least). The rank is a statement about the field, so it is computed after the whole field
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
| `views/football/bakers-buns.html` | `REG_TILES`, `CONTEXT_TILES`, `regTile()`, `regRow()`, `regressionInner()`, and the `REG_URL` fetch |
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
dashed rule and the `Context` heading do the actual separating, because tile styling alone was too
quiet to carry it: a grey tile is also what a regression tile with nothing to say looks like.

---

## Sources section

Both feeds are documented on the page itself under **Sources**, alongside the inputs that actually
feed the composite score — with the definitions restated there, since a reader questioning a number
looks there rather than here.
