# Task: Surface outright / award / futures markets (DK + SCORE, then FD)

This is a self-contained brief for a future session. Read it end-to-end before
writing code. The player-prop (Over/Under) pipeline is already done; this task
adds the **outright** markets that both books serve but the UI has no home for
yet — awards (MVP, OPOY, DPOY, ROY), team futures (Super Bowl / conference /
division winner, make playoffs, most regular-season wins), statistical leaders
(most passing/rushing/receiving yards), and milestone "Player to Have X+" lists.

## Why this exists

The odds pipeline captures sportsbook JSON via the Recorder bookmarklet
(`scripts/odds-recorder.js`), saves a bundle into `data/imports/<book>.json`, and
a per-book parser transforms it into the files `views/odds.html` reads. The
existing parsers **deliberately skip** non-Over/Under markets and just *report*
them ("present but NOT written"), because the current odds page only renders
Over/Under cards. Those skipped markets are the subject of this task.

Background/architecture: read `docs/ODDS_AUTOMATION.md` first.

## Where the data is and what it looks like

Both books' outright markets are **already captured** in the bundles on disk:

- DraftKings: `data/imports/dk.json` — `captures[].body` of the
  `leagueSubcategory/v1/markets` responses. Native DK shape: parallel
  `markets[]` + `selections[]` linked by `selection.marketId`. An **outright**
  market is one whose selections have **no `outcomeType`** (player-prop markets
  do). Identify them via `marketType.name` (e.g. "Offensive Rookie of the Year
  Award", "Winner") and the absence of Over/Under.
  - Selection shape: `{ label: "Jeremiyah Love", displayOdds:{american:"+320"},
    participants:[{name, type, metadata:{sdid}}] }`. The candidate name is
    `selection.label`; the price is `displayOdds.american` (note the unicode
    minus `−` U+2212, handled by `fmtDk` already in odds.html).

- theScore: `data/imports/score.json` — GraphQL bodies; walk `body.data` for any
  dict with a `selections` list (see `iter_markets` in
  `scripts/parse_score_import.py`). An outright market has `type == "LIST"`
  (vs `"TOTAL"` for Over/Under).
  - Selection shape: `{ name:{cleanName}, odds:{formattedOdds:"+450"},
    participant:{...} }`. Candidate = `name.cleanName`; price =
    `odds.formattedOdds` ("Even" → "+100", handled by `fmtScore`).

- FanDuel: not captured yet. **Design for three sources from the start** but
  build/verify against DK + SCORE now; wire FD in when its bundle lands.

### The outright markets actually present (from the last parse runs)

DraftKings (31): Winner (Super Bowl, 32 teams), To Make Playoffs (32),
AFC/NFC Winner (conference, 16 ea), AFC/NFC East/North/South/West Winner
(divisions, 4 ea), Offensive Rookie of the Year (51), Defensive Rookie of the
Year (53), Most Regular Season Passing/Receiving/Rushing Yards (38/99/62),
"Player to Have {1000,1250,1500,2000}+ Rushing Yards", "...{1000,1250,1500}+
Receiving Yards", "...{25,30,35,40}+ Passing TDs", "...{3500,4000,4500}+ Passing
Yards" (player lists, not Yes/No).

theScore (5): Most Valuable Player (104), Offensive Player Of The Year (110),
Defensive Player Of The Year (60), Super Bowl Winner (32), Most Regular Season
Wins (32).

**Cross-book overlap to unify:** DK "Winner" ≡ SCORE "Super Bowl Winner";
DK "Defensive Rookie of the Year" is distinct from SCORE "Defensive Player Of
The Year" — do **not** conflate ROY with POY. DK has no MVP/OPOY in this
capture; SCORE has no division/conference winners or milestone lists. So the
two books overlap on a *subset* — the view must handle markets present in only
one book (show a dash for the missing one), exactly like the player-prop union.

## The goal

Render these as **outright cards**: a market title, then a list of candidates
(players or teams) each with a price column **per book** (DK / SCORE / FD),
mirroring how the Over/Under cards already show FMV/FD/DK/SCORE columns. No
line/total — outrights are a single price per candidate. Sort candidates by best
(shortest) price; show the book columns side by side so the user can line-shop.

## Design constraints (match the existing pipeline exactly)

1. **No frontend rewrite if avoidable.** Prefer transforming captures into a
   data shape a *new, small* render function consumes, the way `buildScoreIndex`
   / `buildDkIndex` already do. Add an outrights section to `views/odds.html`
   alongside the OU sections — reuse the column/badge CSS.
2. **Canonical market keys + candidate normalization.** Build a name map so
   "Winner"/"Super Bowl Winner" collapse to one card, and a `normName()`-style
   normalizer so "A.J. Brown" / "AJ Brown" / "A.J.Brown" match across books
   (reuse the existing `normName` in odds.html). Candidates are players *or*
   teams — handle both (teams: full name vs abbreviation like "BUF Bills").
3. **Merge semantics — never clobber.** A partial capture must not delete
   markets or candidates. Union by (canonical market, normalized candidate);
   freshest capture wins on conflict. This is the rule that saved wins.json
   (32 teams) when only 5 drawers were expanded — preserve it.
4. **Blocklist at parse time too.** Reuse `BLOCK = ["datadoghq.com",
   "launchdarkly.com"]` with the exact/dot/**hyphen** host match (the hyphen
   case catches `browser-intake-datadoghq.com` — see ODDS_AUTOMATION.md).
5. **Keep parsers separate per book**, output to a stable location, e.g.
   `data/outrights/<canonical>.json` (or one `data/outrights.json` keyed by
   market — your call, but document it). Don't break the existing
   `data/dk.json` / `data/score/*.json` consumers.
6. **Slim the stored JSON** to only the fields the renderer reads (follow
   `slim_market` in the score parser) so files stay reviewable in git.

## Suggested approach

1. Decide the on-disk shape for unified outrights (one file per canonical market
   is easiest to diff and merge; mirror the score `data/score/<stat>.json`
   layout). Write down the canonical-name map.
2. Extend or add parsers: `scripts/parse_dk_outrights.py` and
   `scripts/parse_score_outrights.py` (or add an `--outrights` mode to the
   existing two — but separate files keep blast radius small). Each reads its
   bundle, filters to outright markets, normalizes candidate + market names,
   slims, and merges into the output by canonical key.
3. Add a `buildOutrightIndex()` + an outrights render block to `views/odds.html`.
   Gate it so it doesn't disturb the player-prop layout. Match existing CSS.
4. Validate (below) before reporting.

## Validation (do this, don't assume)

- Re-run each parser; confirm counts: DK ~31 markets, SCORE 5, and that
  overlapping markets (SB Winner, DPOY-vs-DROY kept distinct) merge into the
  expected number of canonical cards.
- Simulate the new `buildOutrightIndex` in Python/node against the output:
  every candidate has a price for at least one book; no orphaned selections; the
  unicode-minus and "Even" prices format correctly; team vs player candidates
  both resolve.
- Spot-check 2–3 cross-book cards (e.g. Super Bowl Winner) and confirm the same
  team/player lines up in one row across DK and SCORE columns.
- Confirm the existing OU pages still render unchanged.

## Out of scope / open questions to raise with the user

- Whether milestone "Player to Have X+" markets (DK-only, player lists) belong
  in this view or a separate "milestones" view — ask before building.
- FMV/edge math for outrights (the OU cards compute an FMV column). Outrights
  have no obvious FMV source yet — confirm whether to show book prices only.
- FanDuel: incorporate once `data/imports/fd.json` is captured; its award shape
  is unknown until then — leave a clearly-marked TODO, don't guess the schema.

## Definitely don't

- Don't conflate ROY (rookie) with POY (player of the year).
- Don't let a partial recapture shrink a market (merge, never replace-whole).
- Don't expose `SUPABASE_KEY` or any session token to the browser.
- Don't commit unless the user asks.
