# Baker's Oven — live Sleeper draft companion

A big board that updates itself against a live Sleeper draft. Players cross off as they're
picked or kept, your next pick tracks its own position down the board, and the players you're
high and low on show as warm and cool regions.

Every signed-in account keeps its own list of Sleeper leagues and its own CSV board per league
(see **Leagues & identity** below). Nothing here is hardcoded to one league any more.

Routes:

| URL | Page |
|---|---|
| `/bakers-oven` | Your saved leagues + add-a-league. Nothing else. |
| `/bakers-oven/{leagueId}` | That league's draft status, **My Rankings** (CSV import), and **Open Draft Board** |
| `/bakers-oven/{leagueId}/{rosterId}` | The big board for that team |

Everything league-scoped lives on the league page, including the CSV. There is no team grid —
**Open Draft Board** is a single link to your own team, resolved from the saved league's
`my_roster_id`. The route still accepts any roster id; nothing in the UI offers one.

`{leagueId}` is the Sleeper league id (18-19 digits). `{rosterId}` is the Sleeper **roster_id**,
not the draft slot and not a user id. Both route segments match digits only — a non-numeric
segment 404s rather than booting a page destined to fail against Sleeper.

The route used to be `/the-bakers-oven`. `vercel.json` and `server.py` both 301 the old prefix
to the new one, path and query preserved, so shared board links and bookmarks still land.

A bare one-segment `/bakers-oven/{rosterId}` is a **legacy link** from before leagues
existed. `oven-league.html` recognizes it by length (≤ 5 digits) and redirects: to
`/bakers-oven/{onlyLeague}/{rosterId}` when the account has exactly one saved league,
otherwise back to the league list. The redirect can't live in `vercel.json` or `server.py` —
which league a bare roster id belongs to is per-account data the server never sees.

Access is `requireLogin()` — any signed-in account, no role needed. It was admin-only when the
league was a constant; now that the data is per-account, the role gate bought nothing.

---

## Architecture

The browser talks to Sleeper **directly**. `api.sleeper.app` sends `access-control-allow-origin: *`,
so there is no CORS reason to proxy — and proxying would be actively harmful, because
`server.py`'s Sleeper helpers are cache-first (`LEAGUE_DATA_TTL = 3600`). An hour-old cache on a
live draft is a bug factory. Going direct also means the rate limit applies per client IP.

```
CSV upload ──> merge into the board ──> POST /api/football/resolve ──> rows carry a
                                        (only rows with no id yet)     Sleeper player_id
                    └── reuses build_player_resolver() / resolve_player()   (once, at import)

draft night ──> browser polls api.sleeper.app directly ──> exact player_id match ──> cross off

static ──> data/fp_redraft.json (committed)  +  /api/players (KTC/FantasyCalc, lazy)
```

Resolving names **once at import** is the load-bearing decision: the live path becomes an
exact ID match, so no fuzzy matching can fail mid-draft. It runs **after** the merge and only over
rows still lacking an id — the resolver should see a row's merged position and team (a sheet that
left `Pos` blank resolves better once it has landed on the board row that already knows he's an
RB), and a cancelled file should cost nothing. On a re-import that's usually just the new rows.

### Polling — why a heartbeat, not conditional requests

Sleeper's CORS preflight advertises `access-control-allow-headers` **without `if-none-match`**,
so a hand-set conditional header fails preflight. (Verify with
`curl -X OPTIONS -H 'Access-Control-Request-Headers: if-none-match' …`.)

Instead the poller fetches the **draft object** (~1.2 KB), which carries `status` and
`last_picked`, and only refetches the **picks array** (~80 KB at a full draft) when one of them
changes. That's ~66× less data than polling picks directly, and "did anything change" becomes an
explicit check rather than a bet on browser cache behavior.

Cadence: `drafting` 8 s · `pre_draft` 60 s · `paused` 15 s · `complete` stops.
Self-rescheduling `setTimeout` (never `setInterval` — at 8 s a slow request would stack
overlapping fetches), paused on `visibilitychange`, immediate re-poll on `visible` / `online` /
bfcache `pageshow`, exponential backoff with jitter to a 60 s cap on error.

**Rate limits.** Sleeper documents "stay under 1000 API calls per minute."

| Scenario | Requests / 2 h | Per minute | % of limit |
|---|---|---|---|
| 8 s heartbeat (this design) | 900 | 7.5 | **0.75 %** |
| Naive 8 s full-picks polling | 900 | 7.5 | 0.75 % (but ~66× the bytes) |
| Aggressive 1 s polling | 7 200 | 60 | 6 % |

Not a bottleneck by roughly three orders of magnitude.

---

## Files

| Path | Role |
|---|---|
| `views/football/oven-leagues.html` | Saved leagues, add-a-league |
| `views/football/oven-league.html` | One league: draft status, My Rankings import, Open Draft Board |
| `views/football/oven-board.html` | The board; boot sequence and poller wiring |
| `styles/primary/bakers-oven.css` | All `.oven-*` styles |
| `scripts/primary/oven-config.js` | `window.OVEN` — storage key bases, tuning constants, the lineup-slot vocabulary and `startablePositions()` |
| `scripts/primary/oven-leagues.js` | `window.OvenLeagues` — saved leagues, Sleeper metadata, every storage key |
| `scripts/primary/oven-csv.js` | `window.OvenCSV` — RFC-4180 parser, template, export |
| `scripts/primary/oven-draft.js` | `window.OvenDraft` — Sleeper client, pick math, poller |
| `scripts/primary/oven-board.js` | `window.OvenBoard` — the two merges (`buildBoard` against FantasyPros, `mergeImport` against an incoming CSV), render, patch, re-rank |
| `scripts/primary/oven-targets.js` | `window.OvenTargets` — mountable Targets / Projections / Team drawer |
| `scripts/primary/oven-weekly.js` | `window.OvenWeekly` — last season's finishes, scored by this league |
| `scripts/fetch_fp_redraft.py` | Offline FantasyPros half-PPR scrape |
| `data/fp_redraft.json` · `data/fp_redraft_meta.json` | Generated, committed |
| `scripts/fetch_nfl_weekly.py` | Offline Sleeper weekly stat-line pull |
| `data/nfl_weekly_2025.json` · `data/nfl_weekly_2025_meta.json` | Generated, committed |
| `scripts/fetch_pos_ranks.py` | Offline Sleeper half-PPR positional finishes, last two seasons |
| `data/nfl_pos_ranks.json` · `data/nfl_pos_ranks_meta.json` | Generated, committed |
| `scripts/build_prop_lines.py` | Offline reduction of the three book snapshots to one consensus yards + TD line per player |
| `data/nfl_prop_lines.json` · `data/nfl_prop_lines_meta.json` | Generated, committed |

Modified: `vercel.json` (rewrites), `server.py` (3 view branches + `/api/football/resolve` +
a `log_message` fix), `scripts/base/auth.js` (`requireLogin`, the `clearUser` sweep),
`scripts/base/nav.js`, `views/home/football.html`.

`draft_id` is derived at runtime from the league object — not hardcoded — so a new season or a
redraft needs no code change.

---

## Leagues & identity

A saved league is one entry in a single per-account blob (`sport='football'`,
`data_key='oven_leagues'`), read and written through the existing `loadWithSync` /
`saveWithSync` layer. No new table, no new endpoint.

```js
{ league_id, name, season, sport, avatar, total_rosters, status, draft_id,
  my_roster_id, my_owner_id, my_username, my_team_name,
  added_at, refreshed_at }
```

`league_id` is **always a string** — 19 digits is past `2^53`, so `Number()` would round it and
quietly point at nothing.

**`my_roster_id` is the only authoritative `my_*` field.** The other three are display snapshots
so the leagues page can paint with zero network calls; `refreshFromCtx()` re-derives them from
`ctx.teams` whenever you open a league, and only writes when something actually changed (opening
a board during a live draft must not turn into a write storm).

**Adding a league** calls `/league/{id}`, `/league/{id}/rosters` and `/league/{id}/users`, then
asks which team is yours. Deliberately **not** `/league/{id}/drafts`: that call is what makes
`OvenDraft.loadLeague` throw *"This league has no draft yet"*, and a league whose draft isn't
scheduled must still be addable. The league page handles a draft-less league by rebuilding its
context from `fetchMeta` and showing a `no draft yet` pill.

`OvenDraft.shapeTeams(rosters, users)` is shared by `loadLeague` and `OvenLeagues.fetchMeta`, so
the roster picker's cards and the league page's team grid cannot drift.

**Validation traps.** An unknown-but-well-formed id returns **HTTP 404 with a `null` body**, so
`OvenDraft.api()` throws before any field access — the 404 is mapped to "No Sleeper league with
that ID." rather than surfacing raw. `parseId` also accepts a pasted league URL by extracting the
digit run, and non-NFL leagues are rejected outright because the whole board is built on
`data/fp_redraft.json`.

---

## Storage keys & the shared-browser rule

| Data | `data_key` | localStorage key |
|---|---|---|
| League list | `oven_leagues` | `dz_oven_leagues_v1:{uid}` |
| Rankings CSV | `oven_board:{leagueId}` | `dz_oven_board_v2:{uid}:{leagueId}` |
| Targets queue | `oven_targets:{leagueId}` | `dz_oven_targets_v2:{uid}:{leagueId}` |
| Last league viewed | *(local only)* | `dz_oven_last_league:{uid}` |

Every key is built by `OvenLeagues.localKey()`. This is a correctness rule, not a naming
convention.

**The hazard.** `loadWithSync` (`scripts/base/sync.js`) returns the localStorage value when the
server has no row for the signed-in user — *and pushes it to the server under that user* as an
auto-migration. The Oven's keys used to be fixed global strings (`dz_oven_board_v1`), and
`clearUser()` didn't remove them. So on a shared browser, user B signing in after user A read
A's big board and then permanently adopted it into B's account.

**The fix is the key, not the sync layer.** `sync.js` is shared with bets and golf, and its
migration branch is load-bearing there; it carries a comment stating the invariant instead. With
`{uid}` in the key, the auto-push branch can only ever push data the signed-in user wrote.
`clearUser()` additionally sweeps every `dz_oven_*` key on sign-out — belt and braces, and it
also retires the pre-namespacing globals. The `v1 → v2` bump on the board and targets bases
makes those poisoned keys visibly dead rather than merely unreferenced.

**Still exposed:** `dz_bets_v1` is not namespaced. Same class of bug, out of scope here.

**Why the targets queue is per-league too:** a queued entry is a board key (`RB|bijan robinson`)
that only resolves against the CSV imported for that league, and the projection is built from
that league's round plan and roster count. A global queue reads as "N saved targets aren't on the
current board" the moment you switch leagues.

**Removing a league keeps its rankings.** Nothing deletes `oven_board:{leagueId}` — re-add the
league mid-draft and you want your rankings back, not a blank board.

The **key** stayed `oven_board` when the UI label became *My Rankings*. Renaming it would
orphan every stored row for no functional gain; `board` is still the right word for the thing
the rankings render into.

---

## The league picks the positions

A board is a list of draft decisions, and a league that starts no kicker can never make one about
a kicker. Both sources hand over all six positions regardless — FantasyPros ships 32 defenses and
32 kickers in its 862, and a rankings CSV is usually a general-purpose sheet reused across leagues
— so the league itself has to be the filter. `league.roster_positions` is the only thing that
knows.

`OVEN.startablePositions(rosterPositions)` turns those slots into the set of positions the league
can start, expanding each through `OVEN.SLOT_ELIGIBLE` (`FLEX` → RB/WR/TE, `SUPER_FLEX` →
QB/RB/WR/TE, an unrecognized league-specific label → itself) and skipping `OVEN.NON_STARTING_SLOTS`
(`BN`, `IR`, `TAXI`), which say nothing about which positions a league uses. An 18-team league
rostering `QB RB RB WR WR TE FLEX FLEX` + 6 × `BN` yields `QB, RB, WR, TE` — 64 rows off the board.

Both hosts call `OvenBoard.setPositions(ctx.league.roster_positions)` **before** `buildBoard()`,
which is the one gate everything downstream reads through: the rendered list, the undrafted pool
the horizons count against, and the rows the Targets drawer projects, queues and fills a lineup
from all come off `state.rows`. Filtering once at the build is filtering everywhere — no view
filters for itself, and none of them can drift.

Three rules keep the gate from lying:

1. **Null is not an empty list.** `startablePositions` returns `null` when the league declares no
   starting slot at all — an unloaded league, a league that is all bench. Null means *no opinion,
   show everything*; an empty list would mean *start nobody* and would blank the board.
2. **A blank position is kept.** "Unknown" is not the same claim as "kicker", and dropping a
   player because his sheet had an empty `Pos` cell is the one failure mode that would be
   invisible. Aliases are normalized first, so `PK` and `D/ST` are caught (`normPos`).
3. **Nothing is destroyed.** The dropped rows are held on `state.offBoard` and re-appended by
   `exportRows()`, which is a **write** path — every save the board makes (a drag, a grade) goes
   through it, so dropping them would make the first click on any row quietly delete the kickers
   out of the stored sheet. They keep their own `myRank`: nothing on screen was ordered against
   them, so there is no order to restate, and rewriting a number the user typed to paper over a
   gap in the visible ranks would be the bigger lie. `buildBoard` splits them straight back out on
   the next load, and the same blob imported into a league that *does* start K/DEF shows all 862.

The board page prunes the position chips to match before wiring them — a chip with no rows behind
it isn't a filter, it's a button that empties the board — and says what it held back in the
footnote. The league page's rankings card says it too, as a second sentence: "300 players" is a
fact about the import and stays true; the board is where they went. Both count out loud, because
the alternative is a board that is silently missing players you know you ranked.

The Targets drawer's positional floor (`FLOOR_POS`) is narrowed the same way, so a TE-less or IDP
league can't guarantee a row for a position with nothing behind it. Queue entries saved for a
position the league doesn't start simply don't resolve against the rows and stay dormant — they
come back if the same league ever adds the slot.

## The CSV

Headers match case- and space-insensitively. **Only `Player` is required.** Unknown columns are
preserved on the row and ignored — you can keep your own working columns.

| Header | Aliases | Meaning |
|---|---|---|
| `Player` | `Name`, `PlayerName` | **Required.** Player, or a team name for a defense |
| `Pos` | `Position` | Helps disambiguate; inferred when blank |
| `Team` | `Tm`, `NFLTeam` | Same |
| `Tier` | — | Your tier band; falls back to FantasyPros' tier |
| `MyRank` | `Rank`, `RK` | Board order. With no `MyRank` column at all, file order is used — but only to place rows the board doesn't already have; see [Choosing what imports](#choosing-what-imports) |
| `Grade` | `Like`, `Opinion` | `like` / `fade`. The retired `love` and `avoid` are read as `like` and `fade` (`OVEN.GRADE_LEGACY`), as are the usual synonyms (`hate` → `fade`, `++` → `like`). Also settable on the board — see [Setting a grade](#setting-a-grade) |
| `Target` | `Targets`, `Queued`, `Pin` | Your Targets queue as a column. `Y`/`Yes`/`X`/`1`/`✓` all mark him; blank leaves him off. Exported from the live queue, not from the row — see [Targets in the CSV](#targets-in-the-csv) |

The parser is a real RFC-4180 state machine, not `split(',')` — quoted commas, embedded
newlines, `""` escapes, CRLF/LF/CR, and a UTF-8 BOM all round-trip. **Download template** builds a
starter file from the current FantasyPros top 250, so the first upload is one edit away.

### Choosing what imports

An import used to be a replacement: `board = { rows: parsed.rows }`, the whole blob, every column.
That made the sheet the only place your rankings could live. Push one round of updated grades from
a spreadsheet and you also overwrote every tier and rank on the board — including the ones
you'd set by dragging — and any player you'd trimmed out of the sheet vanished.

It **merges** now, and you say which columns it may touch.

**Two steps.** Dropping a file parses it and renders a confirm panel (`#import-confirm`, its own
element — `#import-msg` beside it is a one-shot `innerHTML` blitz that the next status line blows
away, and controls can't live in something that gets stomped). The panel names the file, counts
the rows, splits them into *already on your board* / *new*, and offers one `.oven-chip` per column
**actually present in the file**. Nothing is written until **Import**. The point of the ordering:
which columns a sheet should apply is a question you can only answer once you know what's in it,
and answering it after the board has been overwritten is no answer at all.

**Player, Pos and Team have no chip.** They're how a row is identified — matched against the board
and sent to the resolver — so switching them off would mean an import that can't say which player
it's talking about. They always apply, and only when the cell is non-blank: a sheet that left `Pos`
empty isn't claiming the player has no position.

**A checked column overwrites, blanks included. An unchecked column is never read.** The blank rule
is what makes export → edit → re-import able to *clear* a grade rather than only ever set one, and
it's the rule `Target` has always followed. It's stated on the panel, because it is the one thing
about the flow you could get wrong.

**Matching** is `OvenBoard.mergeImport(existingRows, incomingRows, selected)`, which lives in
`oven-board.js` and not `oven-csv.js`: it needs `playerKey`, `normName` and `teamFromDefenseName`
(the last two module-private), and its output has to be exactly the `exportRows()` shape, which is
the same blob a drag on the board writes. `oven-csv.js` is deliberately ignorant of board keys —
`boardToCSV(rows, isTarget)` taking a *predicate* is the evidence — and that direction is worth
keeping. Three probes, in order:

1. `playerKey(name, pos, team)`.
2. For a row whose `Pos` cell is blank, `DEF|<team from the nickname>`. `playerKey` only consults
   `DEF_TEAMS` once it already believes the row is a defense, so "Denver Broncos" with no position
   keys as `|denver broncos` and would otherwise look like a brand-new player.
3. `normName`, but **only when exactly one unclaimed board row matches**. This is the case where
   the sheet moved him to WR or still carries last season's team code — the row updates in place
   and its pos/team are relabelled, rather than a duplicate appearing. Merging onto a *guess* would
   overwrite the wrong player, which is the one failure here nobody would ever notice, so an
   ambiguous name is added as its own row and warned about instead.

A `claimed` set means one board row per incoming row. `parseBoard` dedupes only on the exact
lowercased name, so "A.J. Brown" and "AJ Brown" both survive it and both `normName` the same way;
the second becomes its own row with a warning rather than silently landing on top of the first —
folding them would pick a winner between two cells the user wrote, and neither answer would be
discoverable from the board afterwards.

**Nothing is ever removed.** A row in the file updates what it matches; a row that matches nothing
is appended; a player on the board the file never mentions is left exactly as he was. An import can
add and it can overwrite, and that's all — which is what makes dropping a hand-built sheet of
twelve sleepers onto a 300-player board a safe thing to do.

**Ranks.** New players with no rank (MyRank unchecked, or absent from the file) go to the bottom in
file order, after the board's current maximum, so nothing already ranked moves and `buildBoard`'s
sort still has a number to work with. This is why `parseBoard` reports its file-order synthesis as
a `rankSynthesized` **flag** rather than a warning: "using the row order from your file as the
board order" is a plain lie about the 300 rows that were already ranked, so the host phrases it for
its own context.

A file that covers only part of the board **will** produce duplicate rank numbers, and they are
deliberately not renumbered. Three reasons: renumbering would rewrite ranks for players the user
didn't include, which is the same objection that makes the merge additive; collisions are already a
supported stored state (`renumber()` walks only `state.rows` while `exportRows()` concatenates
`state.offBoard` at its pre-drag ranks, so every league hiding K/DEF has been persisting them since
that filter shipped); and `buildBoard`'s comparator is a plain `ar - br` over a stable sort, so ties
resolve to merged-array order — existing rows first, appended rows last — deterministically. The
summary counts them out loud and names the one gesture that does normalize everything to `1..n`:
drag any row.

**Extras.** Every truthy key in the selection that isn't a canonical field *is* an extra column's
own label, so one flat map carries both and no separate label list has to be threaded through.
(`mapColumns` only files a header under `extras` when nothing in `HEADER_ALIASES` matched, so the
two namespaces can't collide.) A checked extra with an empty cell **deletes** the key, which is
load-bearing: `parseBoard` only writes non-empty extras onto a row, so without the delete a checked
extra column could add and update but never clear.

### Targets in the CSV

`Target` is the one column that isn't a property of the row. The queue is its own synced slice
(`TARGETS_STORAGE_BASE`, per league) holding board keys and nothing else, so the two ends of the
round trip go through the queue rather than the board blob:

- **Export** — `boardToCSV(rows, isTarget)` takes a predicate, because `oven-csv.js` has no idea
  which league's queue is loaded. The league page builds it from `OvenTargets.keys()`, matching on
  `OvenBoard.playerKey(name, pos, team)` — the same key the pin button writes.
- **Import** — a checked `Target` column is authoritative **for the rows in the file**, blanks
  included, and for nobody else. It used to replace the queue outright, which was right when an
  import replaced the board; under an additive merge it would empty the queue of every player the
  sheet happened not to list. So the league page computes the next full key list itself —
  `keys().filter(not unqueued by this file)` then append the newly marked — and hands that to
  `OvenTargets.setKeys()`, which already owns the bound-check, dedupe, persist, `markBoard` and
  `render`. Existing queue order survives (it filters rather than rebuilds); new entries append in
  file order. A file *without* the column, or with its chip off, says nothing about targets and
  leaves the queue alone; re-importing a plain ranking list must not silently empty it.

  Keys come off the **merged** row and **after** resolution, not off the CSV row's own fields: a
  line with a blank `Pos` that landed on a defense — or had its position filled in by the resolver
  — keys differently than the file would suggest. That's why `mergeImport` returns `resolved[]` as
  `{ row, isNew }` and not a precomputed key.

Writing the queue needs it **bound**, not mounted. `mount()` only runs on the league page's draft
branch, so gating the import on it would mean a Target column that imports on a league with a
draft scheduled and silently does nothing on one without — a rule nobody could predict from the
file they just uploaded. `OvenTargets.attach({leagueId})` resolves the per-league storage key and
pulls the saved queue while touching no DOM; the league page calls it in its boot `Promise.all`,
alongside the board load, so the queue is live before the import button exists. `mount()` shares
the same `bindKeys`/`loadQueue` pair and is idempotent with it in either order (`state.bound`,
`state.loaded`). With no drawer up, `markBoard` finds no rows and `render` returns at its mounted
check, so an unmounted write is just a write.

### Hot and cold

The console's filter block is two rows: positions (a radio group — one at a time, `All` clears),
then **Hide:** `Drafted` and `Fade`, which are independent toggles reading `S.filters.hideDrafted`
and `S.filters.hideFade`. Filtering happens in `visibleRows()` and forces a full `render()`, not a
patch. It has exactly one exception, and it is not in `visibleRows()`: a Hide toggle that would
leave one of your picks with no players at all hands that pick its best available back — see
[A pick is never empty](#a-pick-is-never-empty--rescued-rows).

A graded player states his grade in a mark, never in color — the two surfaces state it
differently, on purpose. **The board row** shows it
on its grade control (below), which is editable and sits at the end of the row; there is no badge
on the name line, because the control is already right there saying it. **The Targets drawer** is
read-only over the board and has no control, so in all three of its views the badge is the only
thing carrying the grade: `like` → ❤️ and `fade` → ❌ (`OVEN.GRADE_ICON`). A faded row also recedes,
which is the older half of the same statement: the badge names the grade, the opacity is what lets
you skip the row without reading it. `OvenBoard.gradeChip()` owns that markup and the drawer is its
only caller. The emoji carry `role="img"` + `aria-label`, since a glyph has no accessible name of
its own.

#### There is no heat model

There was one, and it is worth knowing what it did, because two things on the board are its
survivors. `computeHeat()` blended a grade (`OVEN.GRADE_HEAT`) and the rank-vs-consensus delta
into **one number per row**, smoothed it over a 5-row window, and pushed the result through
`window.Heatmap.diverging` into two channels: a full-saturation 3 px left rail (the per-player
reading) and a low-alpha background wash (the *region*, so a run of your guys read as one band).

All of it is gone — the function, the export, the `heat` / `heatRegion` / `heatSource` fields, the
`HEAT_*` constants, and the `heatmap.js` include on the board page. Nothing on a board row is
tinted now. A row background means *hovered*, or nothing.

The blend was the flaw. "I have him 24 spots above consensus" and "I clicked Like" produced
**identical color**, and the board could not tell you which one you were looking at — on the one
screen where the color was the judgment. Both facts survive, stated separately and in a form that
can't be confused for the other: the **Δ column** is the market disagreement, as a number, and the
**grade control** is your opinion, as a mark. `GRADE_HEAT` outlived the model it was named for and
is now purely the Targets projection's scoring weight (`adjRank` in `oven-targets.js`).

Flame/frost stayed as the Δ column's two states, and the reasoning that picked them still holds:
the source sheet's `#57BB8A` / `#EB9891` were alpha-over-white, so they composite muddy on a
near-black page, and green/red is the single hue pair that collapses under deuteranopia. Blue↔orange
is the standard safe substitute, and it happens to be what a board called Baker's Oven should
have been measuring in all along. The two values live in `bakers-oven.css` only — `oven-config.js`
no longer carries color constants, because nothing interpolates a ramp any more.

### Setting a grade

The grade used to be a CSV column and nothing else: changing your mind about a player meant
leaving the board, editing a spreadsheet and re-importing it — during a draft. It's now a control
on the row, sitting immediately left of the pin, showing the current grade and opening a three-item
menu: **Like · No grade · Fade** (`OVEN.GRADE_MENU`, `OVEN.GRADE_MARK`).

It was a five-item menu — **Love · Like · No grade · Fade · Avoid** — and the two pairs were near
synonyms whose distinction never survived contact with a live board: mid-draft you know whether you
want him, not whether you want him at strength 1 or 2. `love` merged into `like` and `avoid` into
`fade`. Old boards and old CSVs still carry the retired values, so `normGrade()` in `oven-board.js`
maps them through `OVEN.GRADE_LEGACY` as rows are built, and `OvenCSV.cleanGrade()` does the same on
import. Nothing rewrites storage: a board is normalized as it's read, so a device still running the
old code can't fight it over the same synced key, and the next save persists the merged value.

A menu rather than three inline buttons, because 860 rows × 3 controls is a board you can no longer
scan, which is the board's only job. It stays a menu rather than a click-to-cycle button now that
there are only three states, because cycling makes "fade him" a two-click gesture whose intermediate
state is a wrong grade briefly written to a synced board.

The control is `OvenBoard`'s, not the drawer's — `grade` is a field on `state.rows`, and the
drawer's whole contract is that it reads the board and never writes to it. It's opt-in through
`enableGrading({ onGrade })`, exactly like `enableReorder`, and the board page hands both the
same `saveBoardOrder` writer. That's why grading needed no storage key of its own: it's the same
per-league blob, so a grade set on the board shows up in **Export My Rankings** and follows you to
your phone through sync. It also works on iOS Safari, where drag-to-reorder doesn't fire at all.

**One menu element for the whole board**, parked on `document.body`. Per-row menus would be
4,300 more nodes to rebuild on every render. It can't live inside the row: `.oven-row` sets
`content-visibility`, whose paint containment would clip the menu to the 32 px row, and
`.faded`/`.gone` set `opacity < 1`, which would dim it and trap its `z-index` in the row's
stacking context. It's positioned `absolute` in *document* coordinates, so it travels with its
row and page scroll needs no listener. A poll re-anchors it (`placeMarkers()` shifts every row
below the horizon); a `render()` and a `dragstart` close it.

**Choosing a grade re-renders the whole board rather than patching the row**, which is the one
non-obvious decision here. It used to be justified by the heat wash — grading one player re-tinted
his neighbors, so nothing about it was local. With the wash gone a grade is very nearly a one-row
fact, but not quite: `.faded` moves with it, and under **Hide: Fade** grading someone `fade`
drops him out of `visibleRows()` entirely, which can orphan the tier header he was the only
visible member of. A patch path would therefore still have to know about the filter and about tier
headers — which is to say, restate `render()`. The Δ column does *not* move on a grade; it reads
the two ranks directly. `render()` restores `scrollY`, so the board doesn't jump, and the rebuild
has never been the thing worth optimizing here.

That last case is worth stating plainly: **with `Hide: Fade` on, grading someone `fade`
makes his row disappear.** That's the filter doing exactly what it says — setting the
grade *is* writing him off. Nothing is lost; the grade is saved before the render, and turning
the chip off brings him back with it set.

Grading also refreshes the drawer, because grade weights the projection (`adjRank`) — an open
Projections view has to move him now, not at the next poll. The same call was missing from the
drag-reorder path, which reads `myRank`; it's there now too.

The control stays visible and live on a **drafted** row, unlike the pin, which hides. The pin
hides because it would queue a target that can never come up — an action with no outcome. A grade
isn't an action, it's a fact, and the drafted-row treatment already commits to keeping those
(struck on the name only; the team and grade are still true about him).

### Expected-pick markers — the horizon

The spreadsheet's sparse column-3 markers, recomputed live. For your k-th upcoming pick, the
marker sits after `pickNo - onTheClock` still-available players — "if the board goes chalk,
you're choosing from here." Unlike the static column, this honors keepers, traded picks, and
every pick actually made, and the markers rise up the board as players come off.

**Still-available means the whole board, not the visible rows.** `placeMarkers()` counts down
`state.rows` minus `state.drafted`, carrying a row element per available player and `null` for
anyone a filter is hiding, then anchors each marker to the first player at or past that depth who
is actually rendered. Only drafting removes someone from that count — a filter never does. This
is the difference between the two Hide chips: `Drafted` was always free (drafted players leave the
pool either way), while `Fade` used to *push the horizon down the board*, because the faded
players between you and your pick stopped counting as gone-before-you and the marker had to eat
that many extra visible names to make up the depth. A position filter had the same bug. Hiding is
a view, not a trade.

This is the page's signature element, so it is built as one: the first marker is full-bleed,
flame, and set in the serif face (used here and on the on-the-clock state, nowhere else). Later
markers are quiet — `Then · 3.12`. The count of players between you and it lives in the pinned
console, not on the marker; the console is always on screen, so printing "N away" in both places
just says it twice.

Rows above the first marker are a **named zone** — a `The chalk · N gone before you're up`
header, plus a diagonal hatch. The hatch is painted at `z-index: -1` so it knocks back the
background without darkening the glyphs: these rows are exactly what you read when the board
*doesn't* go chalk, so recession is carried by texture, never by dimming text below contrast.

#### A pick is never empty — rescued rows

The markers cut the board into **windows**: everything between one horizon and the next is what
that pick can realistically reach. A Hide toggle can empty a window outright — a run of players
you all faded, say — and then two markers stack with nothing between them, which reads as *"you
have no pick there"* when the truth is *"everything there is hidden"*. That is the one case where
a filter stops subtracting rows and starts deleting a pick.

So `rescueEmptyWindows()` gives an empty window its **best available** back — the first player at
or past that pick's depth — hidden or not, marked `.rescued` and wearing a `best available` tag
that says why it's on screen. It runs inside `placeMarkers()`, before the markers are placed, so
the horizon anchors to the row it just put back instead of skipping past it.

Three rules keep the toggle honest:

1. **Nobody moves.** The row is reinserted at its real depth in the pool, so every survivor keeps
   the position and the neighbours it had. Same promise the horizons make, for the same reason.
2. **One row per empty window, never more.** Fade three players in a row and you get the first one
   back, not all three. Anywhere the toggle isn't erasing a pick it still means exactly what it says
   — a window with even one survivor is never topped up.
3. **The position filter is not overridden.** `Hide: Fade` says "take these off my board", so
   handing one back is a correction. Filtering to RB says "this screen is running backs" —
   answering *"no RB in that window"* with a receiver would be answering a question nobody asked,
   so an empty window under a position filter is a real finding and is left to stack. With both on,
   the rescue stays inside the position. (`Hide: Drafted` can't empty a window at all — drafted
   players leave the pool on both paths.)

Rescued rows are torn down and rebuilt on every `placeMarkers()`, exactly like the markers they
answer to: one pick landing changes every depth below it, so *which* windows are empty is never
stable enough to patch. `dropRescued()` also removes them from `state.rowEls`, which is what keeps
a grade patch, an open grade menu and `OvenTargets.markBoard()` from holding a detached element.

Two display notes. The row is inserted **above** a tier header it sits before, not under it —
otherwise the band would claim a tier for a row that isn't in it. And `.faded` is an opacity on the
row, which a child cannot un-inherit, so a rescued row moves that recession onto its columns
(`.rescued.faded > *:not(.oven-rescued)`) and leaves the tag at full strength: a label at `.52`
explaining a row at `.52` explains nothing.

---

## Targets, Projections & Team

A right-edge drawer (`scripts/primary/oven-targets.js`), mounted on both the index and the board.
It is a **component, not a page**: it injects its own tab, panel and listeners into `<body>` and
reads everything through one accessor the host supplies.

```js
OvenTargets.mount({ getState: function () { return {
  rows, drafted, picks, plan, teamsCount, rounds, myRosterId, rosterPositions
}; } });
OvenTargets.refresh();   // after every poll

OvenTargets.attach({ leagueId });   // queue only, no drawer — see Targets in the CSV
```

It never writes to the board. The only thing it persists is a list of board keys, under its own
synced slice (`oven_targets` / `dz_oven_targets_v1`) — so queuing a player cannot corrupt the
imported CSV, and the queue follows you from the index to the board to your phone.

### Getting players in

The pin button at the end of a board row, and nothing else. `OvenTargets` owns the handler and it
is inert on a page that doesn't mount the drawer; the pin flips `+` ⇄ `✓`, the row gains a flame
inner rail, and the `×` in the drawer takes him back off.

Dragging a board row used to drop a player in here. It now **re-ranks him on the board** instead
(see [Re-ranking](#re-ranking-drag-a-row-to-move-him)) — the queue never needed the drag, because
it already had an explicit toggle in the row and an explicit remove in the drawer, both of which
also work on a phone, where HTML5 DnD doesn't fire at all.

The drawer is deliberately **non-modal on wide screens**: you queue players off the board with the
drawer open, and a scrim over the board would eat those clicks. Below 720 px it gets the scrim,
because there the drawer covers the board anyway.

### View 1 — projections (the default)

The drawer opens here. Of the three views it's the only one that answers "what happens next",
which is the question you have with the drawer open mid-draft; the queue is something you built
beforehand and can check on demand.

Rounds 1..N, exactly as the draft is structured. Keepers and made picks fill their own round from
`pick.metadata` — not from the board, because a keeper need not be on your CSV at all. Rounds you
traded away say so.

Future picks are simulated forward, and the model is worth stating because every number rests on
it:

1. **The room drafts to consensus.** Between your picks, the top `gap` of the *market-ordered*
   (FantasyPros ECR) pool disappears, where `gap` is the count of genuinely unfilled picks
   between your turns — so keepers and traded picks are honored, same as the horizon markers.
2. **You draft your board.** At each of your picks the sim takes the best remaining player by
   adjusted rank: your rank pulled forward by `PROJ_TARGET_BONUS` (queued) and by the CSV grade
   × `PROJ_GRADE_WEIGHT`. The grade is halved on purpose — an opinion is a thumb on the scale,
   not a replacement for the ranking.
3. **That choice is then removed from the pool.** Round 5 is projected against a board where you
   already took rounds 1–4. This look-ahead is the entire reason the view exists; without it
   every round would recommend the same player.

Each row is chipped with what it is: `proj` (rank order put him here), 🎯 (he's in your
queue — a player can be both), and `top RB` (best remaining at his position).
Past the rank-order entries, every position with a
body left contributes its best remaining player as a **floor**, so a run on your position never
leaves a pick with no answer; those rows are set lighter, since they are fallbacks rather than
recommendations.

The model is exported as `OvenTargets.project(state)` so it can be exercised without mounting.

### View 2 — targets

The queue, grouped by position, ordered by your rank. Each row carries the grade chip and a
window chip fed by the projection above: `R4–R7` (available across that span), `R3 only` (one
shot at him), `yours R2` (the sim already takes him there), `out of reach`, or `gone 3.05` once
he's actually off the board.

### View 3 — team

The lineup as **the league** defines it. Slots come from Sleeper's `league.roster_positions`
verbatim — never a default guessed from the draft's round count — so a superflex or a
second-flex league renders its own shape without a code change. `BN` becomes the bench section;
`IR` and `TAXI` are dropped, because a slot nobody drafts into would read as a lineup hole.

Filling is greedy, one player at a time, **keepers first and then picks in draft order**, into
the most specific empty slot he's eligible for. Specificity is the whole trick: `FLEX` accepts
three positions and `RB` accepts one, so the first RB lands at RB and the flex spots go to
whoever is left over. Filling in pick order alone would drop RB1 into FLEX and spill RB2 onto
the bench.

Ownership of a pick is `pick.roster_id` when Sleeper sets it, and the pick plan (which already
honors traded picks) when it doesn't — mock drafts leave `roster_id` null.

A rostered player carries his board row's grade badge and positional rank when he's on the CSV,
and renders from `pick.metadata` alone when he isn't — a keeper need not be on your board at
all, same as in projections. Made picks are chipped with their `R.PP`; keepers say `kept`.
Bench overflow past the declared `BN` count still renders: a lineup that quietly dropped a
player you drafted would be worse than one that runs long.

Exported as `OvenTargets.team(state)` for the same reason `project` is.

---

## Pick math

`slot_to_roster_id` gives slot → roster; `traded_picks` then overrides ownership. In a
`traded_picks` entry, **`roster_id` is the original owner and `owner_id` is the current owner**
(both roster ids, not user ids) and `season` is a string. Getting this backwards silently puts
"your next pick" on the wrong rows.

Keepers occupy real `pick_no` slots before the draft opens, so the current pick is the **first
unfilled number** — never `picks.length + 1`.

Known-good fixture for baker28 (roster 1, slot 12), verified against the live API:

```
picks: 12, 13, 36, 37, 60, 61, 85, 108, 109, 132, 151, 156, 157, 162, 180, 181
  R14 keeper lands on pick_no 162 (acquired from roster 11, slot 7)
  traded-away R7 (84) and R12 (133) absent
  acquired R13 (151) and R14 (162) present
  on the clock = 1 (not 8, despite 7 keepers already filled)
  first live pick = 13 (pick 12 is the Puka Nacua keeper)
```

---

## Rendering

A board row is one line: your rank · position badge · name · Δ · taken tag · pin. The
position badge carries the **positional rank** (`RB7`, not `RB`) — it names the position on the
way past, so one colored cell does both jobs — and the NFL team rides the name line as a dim
annotation. That rank is **yours**, derived from board order rather than copied off FantasyPros:
the seventh running back down your board is `RB7` whoever the market has there. FP's `pos_rank`
only ever seeded the first ordering, and every drag renumbers the badges along with the ranks —
promoting one WR past four others changes five badges, not one. It counts drafted players too, so
a badge never moves because someone else came off the board. There is no sub-line under the name; the same shape is used in the Targets and
Projections drawer. Once a player is drafted or kept (`.gone`), his pin goes `display: none` — it
would queue a target that can never come up, and it's last in the row so it takes nothing with
it.

**ECR itself has no column; the Δ against it does.** Those are different facts and only one of
them is a decision. A consensus rank of 41 tells you nothing on its own — you'd have to find your
own rank on the same row and subtract. `Δ +12` is the subtraction already done: *you are twelve
spots higher on this man than the market is*, which is the reach-or-wait question stated in one
number. So ECR stays loaded — it is the Δ's other operand and the projection's market order — and
stays off the row, and the Δ is printed.

The Δ is computed in `rowHTML()` from `fpRank - myRank`, and a grade never touches it: "I graded
him Like" is not a claim about where the market has him, so a liked player the market also likes is
Δ 0 and the column says so. Flame when you're higher, frost when you're lower, dim at zero; `—`
means no consensus rank for him at all. It is the row's only colored element (see *There is no heat
model*), so a hue on a board row always means this and only this.

**A drafted or kept player has no Δ.** The number is an argument for a decision — reach, or wait —
and once he is off the table there is no decision left to argue for; a flame `+40` on a player
nobody can pick is the board pulling your eye toward a pick that cannot happen, mid-draft, which is
the worst possible moment for it. The rule is one line of CSS on `.gone` and it's `visibility:
hidden` rather than `display: none`: the 40px slot stays, so a live row's Δ holds the same column
as the rows around it cross off. A column that reflows on someone else's pick would be worse than
one with gaps. Hiding also drops it from the accessibility tree, so nothing reads out a number the
board isn't showing. `.gone` is applied by `applyDraftState()` on every poll and reapplied by
`render()`, so the single rule covers the surgical patch, a full rebuild, and an undone pick.

The crossed-off rule targets `.oven-name-text`, not the whole name line: `text-decoration`
propagates to descendants and a child cannot opt out, so the team sits outside the
struck span rather than being un-struck inside it.

### One order, no sorting

**The board is never re-ordered.** `state.rows` comes out of `buildBoard()` in personal-rank
order and stays that way for the session; the header cells are labels with no `data-sort`, no
click handler, and no hover affordance, and there is no sort state to toggle. Re-ordering the
board mid-draft is the one interaction that can cost you a pick — the horizon markers, the tier
bands, and your own memory of where a player sits are all anchored to rank order, and every one
of them is meaningless under a different sort.

Filtering stayed because it *subtracts* rows without moving the survivors: `visibleRows()`
returns a filtered slice of the same array, in the same order. The page no longer loads
`scripts/components/table-sort.js` at all.

Dragging a row is **not** a sort — see below. It edits the one order rather than replacing it,
which is why nothing anchored to personal rank breaks afterward.

### Re-ranking — drag a row to move him

`OvenBoard.enableReorder({ onReorder })`. Board rows are `draggable="true"`; dropping one on the
seam above or below another row moves that player there. On drop:

1. **Move by key, not by on-screen index.** A position filter may be active, so the row you
   dropped onto is a position in `state.rows` that the visible list only samples. Landing between
   two visible rows leaves every hidden row between them exactly where it was.
2. **Renumber from the top.** Every `myRank` becomes its array position + 1, including rows that
   arrived with no `MyRank` at all — once you have hand-ordered the board there is no longer an
   "unranked, sorts to the bottom" tail worth preserving.
3. **Adopt the destination tier.** Tier belongs to the band, not to the player: the moved row
   takes the tier of whoever he now sits behind (or, dropped at the very top, of whoever he now
   sits in front of). Carrying his old tier along would emit a stray `Tier 6` header in the middle
   of tier 2 — headers fire on first appearance — and would claim something the move just
   contradicted.
4. **Re-render.** The Δ column is `fpRank - myRank` computed at render time, so moving a player
   necessarily restates it — his and everyone he displaced. That is the point: drag someone up and
   watch the number climb into flame.
5. **Hand the rows to the host.** `onReorder(rows)` receives them in the exact shape a CSV import
   writes, and `/bakers-oven/{leagueId}/{rosterId}` writes them straight back into the same
   per-league blob under `oven_board:{leagueId}`. A board still seeded from FantasyPros (nothing
   imported for this league yet) becomes a real saved board on the first move — dragging a player
   *is* authoring your rankings. `Export My Rankings` on the league page then gives you the board
   you are actually looking at.

Persistence is the host's job on purpose (`onReorder` is opt-in): the module owns no storage keys,
and a board nobody can save is a board that silently forgets the order on reload.

Mid-drag the feedback is a single flame rule on the seam the player would land in — `.drop-before`
/ `.drop-after` on the hovered row — and the source row dims to `.is-dragging`. HTML5 DnD does not
fire on iOS Safari, so re-ranking is desktop-only; the CSV is how you author a board anywhere else.

Two-phase, deliberately:

- `render()` — full `innerHTML` build. Boot, CSV import, filter change.
- `applyDraftState()` — surgical class/text patches. Every poll.

A full rebuild on each poll would reset scroll position and kill the cross-off animation while
you're reading the board mid-draft. `content-visibility: auto` on rows buys most of
virtualization's benefit for one CSS line.

All interpolated strings go through `esc()` — CSV content is user-supplied and lands in
`innerHTML`.

Tier headers are emitted **once per tier, on first appearance**. Tiers are only roughly
contiguous in personal-rank order; promoting a player past a tier boundary would otherwise
ping-pong the headers.

---

## Refreshing FantasyPros

```bash
python3 scripts/fetch_fp_redraft.py     # writes data/fp_redraft.json + _meta.json
```

Scrapes the `var ecrData = {…}` blob out of the half-PPR cheatsheet (862 players). Normalizes
into **Sleeper's vocabulary** at scrape time — `DST` → `DEF`, `JAC` → `JAX` (23 players) — so no
consumer downstream has to remember the difference. Fails loudly if the blob moves or fewer than
300 players parse, rather than silently writing bad data.

The board shows the snapshot date and warns past 3 days. **Re-run it the morning of the draft
(2026-08-31).** Committed and CDN-served, matching how `data/fp.json` works; scraping at request
time would likely get a Vercel IP blocked.

---

## Where he finished — the two seasons before this one

Under every name, always on: his **half-PPR positional finish** for Y-1 and Y-2, the same number
Sleeper's player card prints.

```
Christian McCaffrey  SF
2025 RB1  2024 RB71
```

That pair is the argument the row can't otherwise make. RB1 then RB71 is a back who was elite and
then lost a season; RB4 then RB2 (Gibbs) is one who has been elite twice. Same ECR neighborhood,
opposite histories.

It is the **third** thing a row says about a player, and the three do not overlap:

| Where | Claim | Whose scoring |
|---|---|---|
| Δ column | Where the market has him **this** year vs where you do | FantasyPros half-PPR ECR |
| This line | Where he **finished**, last two years | Sleeper half-PPR |
| `2025 weeks` chip | How many weeks he was **startable** last year | **Yours** |

**Deliberately not league-scored**, unlike the weekly counts. A positional finish is a shared
reference — "he was the WR7" means the same thing in every conversation you have had about him —
and half-PPR is the format it gets quoted in. Re-scoring it privately would produce a different
number wearing the same name. The weekly counts already answer the under-my-rules question, and
answering it twice in two grammars on one row makes neither readable.

**Always on, unlike the weekly table.** Two numbers are not the three-plus-a-toggle that chip
exists to keep off the board, and a history you have to remember to turn on is one you won't have
on mid-run, which is the only moment it matters.

### How good the finish was, in four steps

The numbers are graded against **their own position's starter depth**
(`OVEN.POSRANK_STARTERS` — QB 12, RB 24, WR 30, TE/K/DEF 12), because RB4 and WR4 are not the same
achievement and one scale across both would say they were:

| | | RB | WR | reading |
|---|---|---|---|---|
| `t1` | ≤ half the starters | ≤ 12 | ≤ 15 | an every-week guy — the finish you draft for |
| `t2` | ≤ the starters | ≤ 24 | ≤ 30 | a starter, unremarkably |
| `t3` | ≤ twice the starters | ≤ 48 | ≤ 60 | bench, bye-week filler |
| `t4` | beyond | — | — | he was not a fantasy player that year |

**Starters, not a percentile.** 253 wide receivers were ranked last season; a percentile over that
pool puts WR40 — a man nobody started — in the top fifth. Against 30 starting WRs he lands where
he actually was. Fixed at 12 teams and not read from the league, because this grades a season that
has already happened: "RB18 in 2025" meant the same thing to everyone who watched it, and a
10-team league does not retroactively make him worse.

**Four steps, and four is the ceiling** — the same reason `.oven-delta` buckets its opacity instead
of computing one. Nobody resolves more than about four levels in a 10px number.

**Value, not hue, and that's the palette law of this file** (see the header of `bakers-oven.css`).
Flame and frost are the only two colors on the page and the Δ column is the one element allowed to
wear them; when something on a board row is orange it means you and the market disagree, full stop.
A green/red heat scale here would be a third and fourth hue arguing with that on the same row, and
the thing it would shout over is the column you actually act on. Brightness carries it instead —
bone → ash → ash-dim → ash-dim at .62 — which on a near-black page is the strongest channel there
is. On the full 862-row board that lands 101 values in `t1`, 101 in `t2`, 193 in `t3`, 700 in `t4`.

### A season he didn't play is blank, not a dash

The slot still renders and still takes its box — `visibility: hidden` on a slot that keeps its year
and a placeholder — so the second season starts at the same x on every row and the line is one line
tall whether a player has two finishes, one, or none. The slot is a measured 64px, which is the
widest content the full board produces (`2024 WR1338`); a pixel less and 22 rows deep in the board
wobble their second column 2px right.

A dash *is* information — "he wasn't in the league" — but it's information the empty space already
carries, and 200 rookie rows of punctuation is a column of marks the eye has to sort out from the
numbers it came for. The `title` still says `did not play` on the row you stop on. What a blank
never means is a bad season: a 2026 rookie has no 2025 finish, a number there would be fabricated,
and the games-played gate below is what keeps one from appearing.

### Two traps in the fetch

`scripts/fetch_pos_ranks.py` pulls `pos_rank_half_ppr` from `GET /stats/nfl/regular/{season}` (one
request per season, browser UA required, same as the weekly script). Two things about that field
are not what they look like:

- **Sleeper ranks every player in its database, played or not.** All 8,233 rows in the 2025 file
  carry a `pos_rank_half_ppr`, because the zero-point block has to be ordered somehow. Ungated,
  a 2026 rookie shows a 2024 finish in the 500s — a fabricated season. The gate is `gp`: he gets a
  finish for a season he played and a dash for one he didn't. Zero-point seasons survive it —
  playing and scoring nothing is a real, if grim, finish. 8,233 rows → **708 players**, 23 KB.
- **The rank is computed within Sleeper's `position`, not `fantasy_positions`.** Kyle Juszczyk is
  `fantasy_positions: ["RB"]` and `position: "FB"`, and his `pos_rank_half_ppr` of 1 means **FB1**
  — 45 points on the season. Printed as "RB1" that is not a small error. Any player whose two
  positions disagree is dropped (~10/season): the number is true about a pool the board can't
  name, which makes it unusable rather than imprecise.

Joined to the board by `OvenBoard.playerKey()`, exactly like the weekly file — same
`norm_name()`/`player_key()` pair, same must-not-drift rule (see *Joining to the board* below).
Collisions across two seasons of namesakes are reported and resolved to the better finish; there
were 0 among players the board actually shows.

```bash
python3 scripts/fetch_pos_ranks.py                    # last two completed seasons
python3 scripts/fetch_pos_ranks.py --seasons 2025,2024
```

**The file names its own seasons** (`{seasons: [2025, 2024], ranks: {key: [r, r]}}`), and the
renderer takes the labels from the payload. Next August a re-fetch rolls the years forward with no
code change — `OVEN.POSRANK_DATA` is the only constant, and it has no year in it. That is the one
thing to keep true if this file is ever restructured: a year hardcoded in JS is a row that
confidently mislabels 2025's number as 2026's the first summer nobody re-runs the script.

### The row aligns to its first line, not its middle

The name column now carries sub-lines — this one always, the weekly table when its chip is on — so
`.oven-row` is 48px (73px with weekly) while the facts on either side of the name are about its
first line. Centered in the whole row, the position badge floated into the gap between the name and
the finishes and read as belonging to neither.

So the rank, the badge, the Δ and the drafted tag top-align onto a shared **18px first line**
(`.oven-name-main` fixes `line-height: 18px`; the badge's 14px line + 2px padding adds up to the
same 18px, which is what lets them align without a magic offset). Only the two 22px **controls**
stay centered: a button is a place to click, not a fact about the name.

`contain-intrinsic-size` is stated as the **content box** — 33px, and 58px under `.show-weekly` —
which is what makes a skipped row render at exactly the height it occupies once laid out. A stale
estimate on 860 rows makes the scrollbar jump as they render in.

---

## What the market has him doing — the odds half of the same line

To the right of the finishes, on the same sub-line, separated by a hairline: the **consensus
season-long yardage line** and the **consensus season-long touchdown line**, from the three books
this repo already records.

```
Bijan Robinson  ATL
2025 RB3  2024 RB4  │  YDS 1150   TD 9.5
└──── history ────┘     └──── odds ────┘
```

**One line, two data sets, and the layout has to say both at once.** Adjacent because reading it
left to right *is* the argument — what he did, then what he is priced to do — and a third line
under the name would cost a saccade to make the same comparison. Ruled apart because they are not
the same kind of number: the left pair is a settled fact off Sleeper, the right pair is three
sportsbooks' current price on a season nobody has played. Different labels over each group
(`2025`/`2024` vs `YDS`/`TD`) so nothing about them looks averageable.

The `.oven-subsep` rule is an **element**, emitted only when both groups exist — not a border on
the odds group. Seven rows in eight have no market at all, and a border would draw a leading
hairline attached to nothing on every one of them. On phones (`max-width: 560px`) the sub-line
wraps and the rule goes: two lines separate the sets harder than a rule does, and `YDS`/`TD` carry
the second line on their own.

### Consensus means the mean of the books' lines

`scripts/build_prop_lines.py` reads the three snapshots `/odds` already reads —
`data/fd.json` (FanDuel), `data/dk.json` (DraftKings), `data/score/*.json` (ESPN) — and writes
`data/nfl_prop_lines.json`. No new source, no network call: everything is already in the repo,
just spread across three vendor shapes.

Consensus is the **mean of the books' main lines**, which is exactly what `/odds` already calls
FMV, and the two pages are kept in step deliberately — a number that disagreed with the odds page
would make one of them a liar. It is not de-vigged and it is not a probability: an O/U line is
already the market's midpoint estimate of the quantity, and the vig lives in the two prices
flanking it. The prices are read only to pick **which** line is a book's main one — the paired
O/U whose implied probabilities sit closest together, since DraftKings and FanDuel both list
alternates — and then discarded.

### Both numbers are sums across markets

A player is priced on one to three separate markets (passing / rushing / receiving × yards / TDs).
"His yards" is all of them added up:

| | | |
|---|---|---|
| Josh Allen | `YDS 4025` | 3541.8 passing + 483.5 rushing |
| Bijan Robinson | `YDS 1150` | rushing only — the market prices him nowhere else |
| Josh Allen | `TD 35.2` | 24.2 passing + 11.0 rushing |

The alternative — one market chosen per position, QB→passing and RB→rushing — would have thrown
away a real priced market on the six players whose legs are the reason they go early. The
per-market breakdown ships in the file and the row's `title` spells it out, because `4025` beside
`3250` is two different sentences depending on whether the first includes 480 rushing yards.

**Rounded in the file, not at render**: yards to the whole yard (a tenth of a yard across a season
is noise), TDs to a tenth (the lines are half-points, so a tenth is where two books disagreeing —
7.5 and 8.5 → 8.0 — still shows). The renderer's `toFixed` is about *printing*, so a consensus of
8 TDs reads `8.0` beside a `9.5` instead of shrinking to one glyph and breaking the column.

### It joins by NAME, and it is the only thing on the row that does

Every other join on the board goes through `playerKey()` — `POS|normalized name`. This one can't:
a book market says `Lamar Jackson Regular Season Rushing Yards` and nothing else, there is no
position anywhere in the feed, and inferring one from the market would file every rushing line
under `RB` — wrong for exactly the players who matter most. So the file keys on `norm_name()`
alone and the row looks up by name.

`norm_name()` in `build_prop_lines.py` must therefore stay byte-for-byte equivalent to `normName()`
in `oven-board.js`, same as its copies in `fetch_pos_ranks.py` and `fetch_nfl_weekly.py`. A drift
produces a valid-looking file that joins to nothing, silently. Against the current FantasyPros
seed the join is **104 of 104**.

**Blank is the normal state.** The books price ~104 players; the board holds ~860. A player with no
market gets **no group at all** — not an empty box — because 750 rows of reserved empty space is a
column of nothing down the whole board. Within a group that *does* exist, a missing half (a back
with a yardage line and no touchdown market) keeps its slot hidden, exactly as a season he didn't
play does, so the two slots still line up.

### Flat color, deliberately

The finishes spend brightness on a four-step scale graded against starter depth (see above). The
odds don't, and copying it would have been a mistake: 1150 rushing yards and 1150 receiving yards
are not the same achievement, the pools differ by position, and any ramp drawn over them would be
a grade this data can't support. Both numbers sit at `--oven-ash` — brighter than a bad finish,
dimmer than a great one, making no claim of their own.

### Refreshing it

```bash
python3 scripts/build_prop_lines.py
```

Re-run it after any Recorder ingest that updates `data/fd.json`, `data/dk.json` or
`data/score/*.json`, and commit the two generated files. It refuses to overwrite good data if a
book parses to zero markets, if fewer than 40 players come out, or if any number lands outside a
plausible range — a vendor shape moving is a silent parse failure otherwise, and one wrong row in
860 reads as a player nobody likes.

Unlike the pos-ranks and weekly files this one is **not** immutable — the books move their numbers
all summer — but it takes the same one-hour `/data/` cache and the same degrade-to-null on fetch. A
stale line is a line the market held yesterday, which is still usable on draft night; a board that
won't open is not.

---

## Last season's weekly finishes

The **`2025 weeks`** chip opens a small table under each player: how many weeks he finished top
**12 / 24 / 36** at his position last season, each cutoff a heading over its own count.

```
Bijan Robinson  ATL
T12  T24  T36
 11   13   15
```

This is the one number on the board computed under **your league's scoring**. Everything else is
FantasyPros half-PPR ECR: a projection of the coming season, averaged, under someone else's
rules. Four WR8 weeks and twelve WR60 weeks produce the same ECR as a steady WR15, and the two
are not the same pick.

**Under the name, not beside it.** As a right-hand column the three numbers read as a second
ranking to scan down the board — the one thing the board refuses to have a second of (see *One
order, no sorting*). Under the player they annotate him instead.

The cell is a two-row CSS grid with `grid-auto-flow: column`, and each tier emits its heading
immediately followed by its value. Flowing by column means the heading/value pairing is
structural, so a position showing one cutoff instead of three needs no column count handed to
CSS. Fixed `grid-auto-columns` keeps every row's table aligned with the row above it.

Rows grow by a line only while the chip is on, so `.oven-list.show-weekly` also widens
`contain-intrinsic-size` — a stale virtualization estimate on 860 rows makes the scrollbar jump
as they render in.

**TE, K and DEF show `T12` alone** (`OVEN.WEEKLY_SINGLE_TIER_POS`). Every league starts one of
each, so nobody is ever choosing between TE20 and TE30; "top 24 at TE" describes a player you
would not have started in any week of any league, which makes it decoration rather than
information. QB/RB/WR keep all three, because their starter depth actually reaches that far.

There is no games-played denominator. `/16` on every row restated the same fact on every row,
and the counts are already read against each other.

### There is no endpoint for this — don't go looking

Sleeper serves exactly three rank formats: `pos_rank_ppr`, `pos_rank_half_ppr`, `pos_rank_std`.
No league-scored rank exists. Their GraphQL endpoint (`POST https://sleeper.com/graphql`) is open
and introspectable, and **all 56 schema fields that accept a `league_id` were enumerated — not one
returns stats or scoring**. The weekly rank on Sleeper's own player card is computed client-side
by their app. We do the same thing.

It's exact, not an estimate. `scoring_settings` keys are the same vocabulary as the stat keys, so
a player's week is the dot product of the two — verified to the cent against Sleeper's own
`pts_std`.

### How it's split

`scripts/fetch_nfl_weekly.py` ships the raw component stats; `oven-weekly.js` does the dot product
in the browser, where `scoring_settings` already sits in memory (`loadLeague` has always returned
the whole league object — nothing had used that field before). A finished season's stats never
change, so they commit and cache; the scoring is per-league and can't be precomputed. No
`server.py` endpoint and no TTL that could go stale mid-draft.

```bash
python3 scripts/fetch_nfl_weekly.py                 # previous season, weeks 1-17
python3 scripts/fetch_nfl_weekly.py --season 2024
```

Run it once per new season. 704 players, 2.0 MB on disk, ~0.3 MB gzipped on the wire; the whole
computation is ~10 ms. Week 18 is excluded by default — starters rest, and a resting stud's zero
would read as a failed week rather than one he was never asked to play.

Three things in that script are load-bearing:

- **The stats endpoint needs a browser User-Agent.** `urllib`'s default gets a 403 where curl gets
  a 200.
- **`DENY_KEYS` must stay a literal list, never a prefix match.** A `^pts_` filter looks equivalent
  and silently destroys `pts_allow` / `pts_allow_0…35p` — real DST stats that leagues score. A
  dropped key is points that go missing with no error. `verify()` canaries the likely casualties.
- **`TEAM_*` aggregate rows must not survive.** They ride alongside real players carrying inflated
  points and `pos_rank_* = 999`; left in, they sit atop every weekly ranking and push real players
  out of the top 12. They're dropped by not appearing in the players dump's fantasy positions, and
  `verify()` fails the build if any leak through.

### Joining to the board

The file is keyed by `OvenBoard.playerKey()` (`RB|jahmyr gibbs`, `DEF|BUF`), **not by
`player_id`** — `player_id` is `null` on every FantasyPros-seeded row, since only CSV-imported
rows carry one. `norm_name()`/`player_key()` in the Python must stay byte-for-byte equivalent to
`normName()`/`playerKey()` in `oven-board.js`; if they drift, the join returns nothing and every
row renders a dash. Checked at build time: **zero key collisions** among 2025-active players.

A row with no data shows `—`, never `0`. A 2026 rookie and a healthy veteran who never cracked the
top 36 are opposite facts, and a zero would state the second about the first.

### Nothing is emphasized

Headings and values share one color and one weight; no cutoff is singled out. An earlier version
bolded whichever cutoff `starterDepth()` computed as the league's real starter line — QB24 in a
superflex, and so on. It was removed along with the function and `OVEN.FLEX_WEIGHTS` that fed it.

Bolding one column pushed the other two into the background, and the shape *across* the three is
the signal: `11 13 15` and `11 13 14` are a every-week starter and a boom-bust dart, and neither
is legible if one column shouts. Which cutoff matters also varies by position and by league, so
the choice was never as authoritative as its visual weight implied.

`OVEN.WEEKLY_SINGLE_TIER_POS` outlived that removal — it decides which cutoffs a position shows
at all, which is a different question from which one to stress.

**Display only.** No effect on the Δ, on `myRank`, on ordering, or on the Targets projection — the
board's one-order invariant is untouched. The chip toggles a class on the list rather than
re-rendering, so your scroll position survives; it stays hidden entirely until the file has loaded
and been scored, and a 404 on the data file degrades to no column rather than a broken board.

---

## Verification

Run `python3 server.py`, open `http://localhost:8000`.

**Routes**
1. `/bakers-oven` is the league list; `/bakers-oven/1384025526670233600` is that
   league's team picker; `/bakers-oven/1384025526670233600/1` is roster 1's board.
   Check with `curl -s localhost:8000/… | grep -c 'id="leagues"'` — only the list page has it.
2. `/bakers-oven/abc` and `/bakers-oven/{id}/1/2` both 404.
3. Legacy `/bakers-oven/1` redirects to `/bakers-oven/{onlyLeague}/1` with one saved
   league, and to `/bakers-oven` with two.
4. Signed out, every Oven URL bounces to `/account`. Signed in as a **non-admin**, all three
   render, "Baker's Oven" appears in the hamburger drawer, and `/football` shows its card.

**Leagues**
5. Paste `1384025526670233600` → 12-team picker → pick one → the card shows
   `2026 · 12 teams · pre_draft` and your team name. Reload persists it; a second browser signed
   into the same account shows it too.
6. Paste `999999999999999999` → "No Sleeper league with that ID." Paste `hello` → the shape
   error. Paste the full `sleeper.com/leagues/…/team` URL → succeeds. Add the same league twice
   → "Already saved."
7. **Change team** repoints **Open Draft Board** and the drawer's projections. **Remove** drops
   the league from the list but keeps its rankings.
8. Open a league you haven't saved → it still renders, with a "Save league" prompt, and
   **Open Draft Board** reads "Pick your team above" until you claim one.

**Per-league rankings**
9. With two leagues saved, import a different CSV on each league page; each **My Rankings**
   summary reflects only its own league, the two board routes render different boards, and
   devtools shows two distinct `dz_oven_board_v2:{uid}:{id}` keys.
10. Queue players on league A's board, open league B's: the drawer is empty.
    `curl -H "X-User-Id: …" 'localhost:8000/api/sync?sport=football'` lists `oven_targets:{A}`
    and `oven_targets:{B}` as separate rows.

**Cross-account isolation** — the headline fix; see *Storage keys* above
11. Sign in as A, import rankings, sign out → **no** `dz_oven_*` key survives in devtools.
12. Sign in as B on that browser → B has no leagues, and after adding one its **My Rankings**
    reads "No rankings uploaded" with **no** `PUT /api/sync` carrying A's rows in the Network
    tab. Sign back in as A → A's leagues and rankings return from the server.

**CSV**
13. Download the template → re-upload unmodified → 250 rows, 0 warnings, 250 matched.
14. Quoted commas (`"Smith, Jr., Bob"`), `""` escapes, CRLF, and a BOM all survive a round trip.
15. A junk extra column imports fine and is preserved; a file with no `Player` column errors clearly.
16. A misspelled name is **kept** on the board and listed as unmatched, never dropped.

**The import merge** (`scripts/primary/oven-board.js` — `mergeImport` is pure, so most of this is
also checkable headlessly by loading `oven-config.js` + `oven-csv.js` + `oven-board.js` into a
`vm` context and calling it directly, no browser or account needed)
17. Drop a file → the confirm panel appears and **nothing is written**: reload, and the old board
    is intact. Cancel, then drop the *same file again* → the panel reappears (the `file.value = ''`
    reset; without it the second choose fires no `change` event and the drop zone reads as dead).
18. Export the board, edit only `Tier` in a copy, re-import with **only Tier** checked → tiers
    change and ranks/grades/targets are byte-identical on a fresh export.
19. Same file with the `Grade` cells blanked: **checked** clears the grades, **unchecked** leaves
    them. This is the blanks-overwrite rule, and it is the one people will be surprised by.
20. Import 300 rows, then a 5-row sheet with 3 of them plus 2 new → *3 updated · 2 added · 302 on
    your board*, and the 297 untouched rows are unchanged. Delete 200 rows from an exported sheet
    and re-import → still 300. An import never removes.
21. Flip a player's `Pos` from RB to WR in the sheet → he updates in place (added count **0**), not
    duplicated. Blank the `Pos` cell on a defense row → it merges onto the existing `DEF|DEN`.
22. Put "AJ Brown" and "A.J. Brown" in one file → the second lands as a separate row **with a
    warning**, never silently on top of the first.
23. A file with no `MyRank` column → existing board order is unchanged and new players land at the
    bottom in file order. A subset file *with* `MyRank` → collisions are reported, the board sorts
    deterministically, and one drag renumbers to `1..n`.
24. Queue A, B and C in the drawer, then import a file containing only A (`Target=Y`) and B
    (blank) with the chip **on** → A stays, B is unqueued, **C is untouched**. Chip **off** → the
    queue is completely unchanged. Same on a league with **no draft scheduled**, where `mount()`
    never runs — that's the bound-not-mounted path.
25. Network tab: importing into an empty board POSTs all N to `/api/football/resolve`; re-importing
    the same file POSTs a near-empty body; **cancelling a file POSTs nothing**. Block the POST and
    the import still completes with a warning, with every previously matched row keeping its
    `player_id` (the summary's matched count must not drop).

**Draft data** (league is `pre_draft` until 2026-08-31, so this is testable now)
17. All **7** keepers render struck through with a `KEPT · owner` tag, and **their Δ cells are
    blank** — the column stays aligned on the live rows above and below them.
18. `computeClock().onTheClock` is **1**, not 8 — proving first-unfilled, not `length + 1`. (No
   longer visible in the console; check it from the devtools console via `OvenBoard.state.clock`.)
19. Console reads **Your pick / 2.01 / 10 away** (pick 12 is a keeper; 9 and 12 are filled), and
    the board carries a `The chalk · 10 gone before you're up` header above a hatched band that
    ends at the `You choose from here · 2.01` horizon.
20. Board pick list matches the fixture above.

**Live behavior**
21. When picks land: rows cross off with a flash, the tag shows `R.PP · owner`, **the Δ blanks in
    place without the column shifting**, **scroll position holds**, and the marker's "N away"
    count drops.
22. A commissioner undo restores the row, hides its tag, and brings the Δ back.
23. DevTools Network: a ~1.2 KB `/draft/{id}` call per tick and **no** `/picks` call until
    `last_picked` changes. Background the tab → polling stops. Foreground → immediate poll.
24. Offline → "Reconnecting (n) · last update Nm ago", backoff widens; online → recovers.

**Targets & Projections**
25. The tab sits on the right edge of both `/bakers-oven/{leagueId}` and
    `/bakers-oven/{leagueId}/1` — but **not** the top-level league list, which has no draft
    context to project from. It opens on **Projections**, with that tab active. Opening it on a
    wide screen leaves the board fully clickable.
26. The pin at the end of a board row adds him: it flips to `✓`, the row gains a flame inner rail,
    and he appears in the queue. Pin again (or `×` in the drawer) removes him. Same on a phone —
    the pin is the only route in, on every device.
27. Dragging a board row does **not** touch the queue: it re-ranks him (checks 32–36).

**Grades**

27a. The grade control sits immediately left of the pin on every row and reads `·` on an ungraded
     board. Click it → a three-item menu opens under it (Like · No grade · Fade), with the current
     grade carrying a flame inner rail.
27b. Pick **Like** → the menu closes and the button shows ❤️. **Nothing else on the row changes
     color** — no background tint, and his **Δ does not move**: it's rank-vs-ECR, and a grade isn't
     a claim about the market. Neighboring rows are untouched. Scroll position holds.
27c. Reload → the grade is still there. **Export My Rankings** on the league page shows `like` in
     the `Grade` column for him; re-importing that file puts it back.
27d. Set **Fade** → the row dims and the button shows ❌. Set **No grade** → the dimming
     clears and the button returns to `·`. The Δ read the same value through all three.
27e. With **Hide: Fade** on, grading someone `fade` removes his row immediately — that is the
     filter doing what it says. Turn the chip off: he's back, still ❌. Nothing was lost.
27e-ii. Mid-draft, with faded players above your horizon: toggle **Hide: Fade** on and off. The
     `You choose from here` marker lands **in front of the same player both times** — it just has
     fewer rows above it — and `The chalk · N gone before you're up` keeps the same N. Same for
     switching a position filter on: the horizon marks the first player of that position expected
     to survive, not the N-th one. Only a pick actually being made moves the horizon.
27f. Open the drawer (it lands on **Projections**), then grade a mid-board player **Like**: he moves up in the
     simulated rounds without waiting for a poll. **Fade** moves him down. The drawer's own rows
     still wear the ❤️/❌ badge; the board row does not, because its control already says it.
27g. Keyboard: Tab to the control, Enter opens, ↑/↓/Home/End move, Enter picks, Escape closes and
     returns focus to the control. A **second** Escape closes the drawer — not the first.
     VoiceOver reads "Grade for {player}: none, menu button, collapsed."
27h. Open the menu and wait out a poll (8 s while `drafting`): it stays anchored to its row even
     when a horizon marker is inserted above it. Start a drag with the menu open → it closes and
     the drag proceeds normally.
27i. Grade a drafted (struck-through) row → the control is still there and still works; the pin is
     not. A grade is a fact about him, and being drafted doesn't make it untrue.
27j. Never imported a CSV for this league → grade anyone → the league page's summary flips from
     "No rankings uploaded" to a saved board, same as a drag does (check 36).
27k. A board saved before the merge — or a CSV carrying `love`/`avoid` — loads with those rows
     reading **Like** and **Fade**: `normGrade()` maps them on the way in and the next save writes
     the merged value. `hate`, `++`, `-` and the rest of the synonyms still import.
28. Projections lists **16** rounds. Roster 1's R14 keeper fills round 14 with a `kept` chip;
    made picks show `picked`; the traded-away R7 and R12 read "No pick this round".
29. Round 2 does not recommend the same player round 1 already took — that is the look-ahead.
30. Queue a player who is 40 spots down: he appears in a later round with a 🎯 chip, and his
    targets-view window chip agrees with the round he shows up in.
31. Filter the board → re-render → targeted rows are still marked, and the surviving rows are
    still in ascending personal-rank order.

**Team**
31a. The **Team** tab renders the league's own slots — for `1384025526670233600` that is
     `QB · RB · RB · WR · WR · TE · FLEX · K · DEF` plus the bench, matching Sleeper's league
     settings exactly. `IR`/`TAXI` slots never appear.
31b. Roster 1's keepers are placed before any drafted pick, each in his own position —
     verified live: Caleb Williams → `QB`, Javonte Williams → `RB`, Puka Nacua → `WR`, the
     other six slots `Open`, bench `0 of 7`. A keeper who isn't on the imported CSV still
     renders (name and team from `pick.metadata`).
31c. Draft a third RB with both RB slots full → he takes `FLEX`, not the bench, and `WR`/`TE`
     stay `Open`. A fourth goes to the bench.
31d. Unfilled slots read `Open` on a hatched row; the section headers count `n of N`.

**The league's positions**
31e. Open the board for `1340070186379673600` (`QB RB RB WR WR TE FLEX FLEX` + 6 × `BN`, no K, no
     DEF). With no CSV imported it renders **798** rows, not 862; the `K` and `DEF` filter chips
     are gone from the console; the footnote reads "Hiding 64 DEF/K — this league starts none."
     Scroll to the bottom: the tail is receivers, no kickers anywhere. The Targets drawer's
     projections list "the best QB, RB, WR, TE left" and never float a defense as a floor row.
31f. Same board in a league that *does* roster `K`/`DEF` (e.g. `1384025526670233600`) → all 862
     rows, both chips present, no footnote. The gate is per league, not per account.
31g. Grade or drag one player on the 798-row board, then hit `Export My Rankings` on the league
     page → the file still has all 32 kickers and 32 defenses. Re-import it into a K/DEF league →
     they are all there. The write path must never eat the rows the board hid.
31h. A CSV row with a blank `Pos` still appears; one with `PK` or `D/ST` does not.

**Re-ranking**
32. Drag the #40 row up onto the seam above #8: he lands at 8, everyone from 8 down shifts one,
    the `RK` column renumbers 1..N with no gaps, and his Δ jumps to roughly `+32` in flame (he is
    now 30+ spots ahead of consensus). The drawer does not open and the queue is unchanged.
33. He shows the tier of the band he landed in, and no stray `Tier N` header appears mid-board.
34. Reload the page → the new order is still there. `Export My Rankings` on the league page
    matches what the board shows.
35. With **QB** filtered on, drag QB6 above QB2: only the QBs move relative to each other; clear
    the filter and every non-QB is still exactly where it was.
36. Never imported a CSV for this league → drag anyone → the league page's summary flips from "No
    rankings uploaded" to a saved board.

**Sync**
37. Signed in, import on one browser → open another → same leagues, same board, same target
    queue. (Signed out there is nothing to show: every Oven page requires an identity now.)

**Positional finishes**
37a. Every row carries `2025 RB4  2024 RB2` under the name, left-aligned with the name and not
    with the badge. Christian McCaffrey reads `2025 RB1  2024 RB71` — and the RB71 is visibly
    dimmer than the RB1. Ashton Jeanty shows `2025 RB13` with the 2024 slot **blank**, and a 2026
    rookie's line is blank end to end without collapsing the row. Spot-check any number against
    that player's Sleeper card — they're Sleeper's, unmodified.
37c. Scroll to row ~200: the two year columns are still at the same x they were at row 1, no
    wobble, including on the deep rows carrying four-digit ranks.
37b. The badge sits on the name's line, not floating between the name and the finishes, and the
    grade/pin pair stays centered in the row. Toggling `2025 weeks` adds a third line under the
    finishes and moves nothing above it.

**Consensus lines**
37d. Bijan Robinson's row reads `2025 RB3  2024 RB4 │ YDS 1150  TD 9.5`, with a visible hairline
    between the two groups. Cross-check against `/odds` → the FMV column of *Regular Season
    Rushing Yards* and *Rushing TDs* reads `1150.2` and `9.5`: the same mean of the same three
    book lines, differing only by the whole-yard rounding this line applies. Anything further
    apart than that means the two pages have drifted on which line a book's main one is.
37e. Josh Allen reads `YDS 4025  TD 35.2` — the sums of his passing **and** rushing markets. Hover:
    the title breaks out `passing yards 3541.8, rushing yards 483.5, passing TDs 24.2,
    rushing TDs 11.0` and names FanDuel, DraftKings, ESPN in that order.
37f. Patrick Mahomes has **no** odds group at all (the snapshot prices him only in award futures),
    and no empty box is reserved where it would have been. Bhayshul Tuten has `YDS 700` with the
    `TD` slot blank but holding its width — the books give him no touchdown market.
37g. Scroll to row ~200: `YDS` and `TD` are still at the same x they were at row 1, and the odds
    group starts at the same x on every row that has one.
37h. Narrow to a phone width (<560px): the odds wrap under the finishes, the hairline disappears
    rather than dangling at the end of the wrapped line, and nothing overflows the name column.

**Degraded**
38. Rename `data/fp_redraft.json` → board still renders from CSV, with every Δ reading `—`
    (nothing to disagree with).
38a. Rename `data/nfl_pos_ranks.json` → the finish line disappears entirely (not a row of dashes)
    and the board opens normally.
38b. Rename `data/nfl_prop_lines.json` → the odds group and the hairline both disappear, the
    finishes stay put at the same x, and the board opens normally. Rename *both* files → the
    sub-line is gone entirely and the row is one line shorter with no empty gap.
39. No CSV at all → board seeds from FantasyPros ranks with an import prompt.
40. Import a new CSV that drops a queued player: he vanishes from the drawer but stays in storage,
    and the empty state says how many saved targets aren't on the current board.

**Invariants**
41. `git status` shows no `package.json`, no lockfile, no new entry in `pyproject.toml`'s
    `dependencies = []`. Zero dependencies is load-bearing in this repo.

---

## Notes

- `FANTASY_POSITIONS` in `server.py` is `{QB,RB,WR,TE,K}` — deliberately **not** widened to
  include `DEF`, because `/api/players` and the trade calculator depend on that set. Defenses are
  handled separately in `resolve_board_players()`; Sleeper's defense `player_id` is the team
  abbreviation itself (`"SEA"`).
- `norm_name()` in `server.py` is left untouched for the same reason. The Oven adds a looser
  lowercase/punctuation-stripped fallback, tried only after the strict pass misses.
- Not built, worth deciding separately: writing picks back to Sleeper, and a mock-draft rehearsal
  mode.
