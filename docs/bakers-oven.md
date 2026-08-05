# The Baker's Oven — live Sleeper draft companion

A big board that updates itself against a live Sleeper draft. Players cross off as they're
picked or kept, your next pick tracks its own position down the board, and the players you're
high and low on show as warm and cool regions.

Every signed-in account keeps its own list of Sleeper leagues and its own CSV board per league
(see **Leagues & identity** below). Nothing here is hardcoded to one league any more.

Routes:

| URL | Page |
|---|---|
| `/the-bakers-oven` | Your saved leagues + add-a-league. Nothing else. |
| `/the-bakers-oven/{leagueId}` | That league's draft status, **My Rankings** (CSV import), and **Open Draft Board** |
| `/the-bakers-oven/{leagueId}/{rosterId}` | The big board for that team |

Everything league-scoped lives on the league page, including the CSV. There is no team grid —
**Open Draft Board** is a single link to your own team, resolved from the saved league's
`my_roster_id`. The route still accepts any roster id; nothing in the UI offers one.

`{leagueId}` is the Sleeper league id (18-19 digits). `{rosterId}` is the Sleeper **roster_id**,
not the draft slot and not a user id. Both route segments match digits only — a non-numeric
segment 404s rather than booting a page destined to fail against Sleeper.

A bare one-segment `/the-bakers-oven/{rosterId}` is a **legacy link** from before leagues
existed. `oven-league.html` recognizes it by length (≤ 5 digits) and redirects: to
`/the-bakers-oven/{onlyLeague}/{rosterId}` when the account has exactly one saved league,
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
CSV upload ──> POST /api/football/resolve ──> rows carry a Sleeper player_id   (once, at import)
                    └── reuses build_player_resolver() / resolve_player()

draft night ──> browser polls api.sleeper.app directly ──> exact player_id match ──> cross off

static ──> data/fp_redraft.json (committed)  +  /api/players (KTC/FantasyCalc, lazy)
```

Resolving names **once at import** is the load-bearing decision: the live path becomes an
exact ID match, so no fuzzy matching can fail mid-draft.

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
| `scripts/primary/oven-config.js` | `window.OVEN` — storage key bases and tuning constants |
| `scripts/primary/oven-leagues.js` | `window.OvenLeagues` — saved leagues, Sleeper metadata, every storage key |
| `scripts/primary/oven-csv.js` | `window.OvenCSV` — RFC-4180 parser, template, export |
| `scripts/primary/oven-draft.js` | `window.OvenDraft` — Sleeper client, pick math, poller |
| `scripts/primary/oven-board.js` | `window.OvenBoard` — merge, heat, render, patch |
| `scripts/primary/oven-targets.js` | `window.OvenTargets` — mountable Targets & Projections drawer |
| `scripts/fetch_fp_redraft.py` | Offline FantasyPros half-PPR scrape |
| `data/fp_redraft.json` · `data/fp_redraft_meta.json` | Generated, committed |

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

## The CSV

Headers match case- and space-insensitively. **Only `Player` is required.** Unknown columns are
preserved on the row and ignored — you can keep your own working columns.

| Header | Aliases | Meaning |
|---|---|---|
| `Player` | `Name`, `PlayerName` | **Required.** Player, or a team name for a defense |
| `Pos` | `Position` | Helps disambiguate; inferred when blank |
| `Team` | `Tm`, `NFLTeam` | Same |
| `Tier` | — | Your tier band; falls back to FantasyPros' tier |
| `MyRank` | `Rank`, `RK` | Board order; falls back to row order |
| `Grade` | `Like`, `Opinion` | `love` / `like` / `fade` / `avoid` (`hate` → `avoid`) |
| `Note` | `Notes`, `Comment` | Free text, shown on the row |

The parser is a real RFC-4180 state machine, not `split(',')` — quoted commas, embedded
newlines, `""` escapes, CRLF/LF/CR, and a UTF-8 BOM all round-trip. **Download template** builds a
starter file from the current FantasyPros top 250, so the first upload is one edit away.

### Hot and cold

The console's filter block is two rows: positions (a radio group — one at a time, `All` clears),
then **Hide:** `Drafted` and `Fade`, which are independent toggles reading `S.filters.hideDrafted`
and `S.filters.hideFade`. `Fade` hides *both* negative grades, `fade` and `avoid` — they are the
two ways of writing "not for me", and hiding one while leaving the other on the board is never
what you meant. Filtering happens in `visibleRows()` and forces a full `render()`, not a patch.

A graded player also wears a badge, so a saturated rail on a row the market agrees with doesn't
read as a bug: `love` → ❤️ and `like` → 🩷 (`OVEN.GRADE_ICON`), `avoid` stays the word, and `fade` gets no
badge at all — a fade is your disinterest, not a fact about the player, so the row recedes
instead. `OvenBoard.gradeChip()` owns the markup and the Targets drawer calls it, so the two
surfaces can't drift. The emoji carry `role="img"` + `aria-label`, since a glyph has no
accessible name of its own.

An explicit `Grade` wins. Without one, heat is `fpRank - myRank` — positive means you're higher
on him than consensus. It renders through `window.Heatmap.diverging` in two channels: a
full-saturation 3 px left rail (the per-player signal) and a low-alpha row wash from a 5-row
rolling mean (the *region*, so a run of your guys reads as one continuous band).

The ramp is **thermal**, not the source spreadsheet's green/salmon: `--oven-frost` `#6AA9D0`
(the market is higher than you) to `--oven-flame` `#FF7A18` (you are higher than the market).
Endpoints live in `oven-config.js` and must stay in sync with `bakers-oven.css`.

Two reasons the sheet's `#57BB8A` / `#EB9891` did not survive. They were alpha-over-white, so
they composite muddy on a near-black page. And green/red is the single hue pair that collapses
under deuteranopia — on the one screen where color *is* the judgment. Blue↔orange is the
standard safe substitute, and it happens to be what a board called The Baker's Oven should have
been measuring in all along.

### Expected-pick markers — the horizon

The spreadsheet's sparse column-3 markers, recomputed live. For your k-th upcoming pick, the
marker sits after `pickNo - onTheClock` still-available players — "if the board goes chalk,
you're choosing from here." Unlike the static column, this honors keepers, traded picks, and
every pick actually made, and the markers rise up the board as players come off.

This is the page's signature element, so it is built as one: the first marker is full-bleed,
flame, and set in the serif face (used here and on the on-the-clock state, nowhere else). Later
markers are quiet — `Then · 3.12`. The count of players between you and it lives in the pinned
console, not on the marker; the console is always on screen, so printing "N away" in both places
just says it twice.

Rows above the first marker are a **named zone** — a `The chalk · N gone before you're up`
header, plus a diagonal hatch. The hatch is painted at `z-index: -1` so it knocks back the
background without darkening the glyphs: these rows are exactly what you read when the board
*doesn't* go chalk, so recession is carried by texture, never by dimming text below contrast.

---

## Targets & Projections

A right-edge drawer (`scripts/primary/oven-targets.js`), mounted on both the index and the board.
It is a **component, not a page**: it injects its own tab, panel and listeners into `<body>` and
reads everything through one accessor the host supplies.

```js
OvenTargets.mount({ getState: function () { return {
  rows, drafted, picks, plan, teamsCount, rounds, myRosterId
}; } });
OvenTargets.refresh();   // after every poll
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

### View 1 — targets

The queue, grouped by position, ordered by your rank. Each row carries the grade chip and a
window chip fed by the projection below: `R4–R7` (available across that span), `R3 only` (one
shot at him), `yours R2` (the sim already takes him there), `out of reach`, or `gone 3.05` once
he's actually off the board.

### View 2 — projections

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

A board row is one line: heat rail · your rank · position badge · name · taken tag · pin. The
position badge carries the **positional rank** (`RB7`, not `RB`) — it names the position on the
way past, so one colored cell does both jobs — and the NFL team rides the name line as a dim
annotation. There is no sub-line under the name; the same shape is used in the Targets and
Projections drawer. Once a player is drafted or kept (`.gone`), his pin goes `display: none` — it
would queue a target that can never come up, and it's last in the row so it takes nothing with
it.

Neither FantasyPros number has a column. ECR is still loaded and still drives everything that
matters — the heat rail, the row wash, and the projection's market order — but reading a
consensus rank off a row was never the decision, and the printed Δ that replaced it wasn't
either: the heat rail already says *how far apart you and the market are* in a form you can read
at a scroll, and a number restating it in the same row is the same claim charged twice.

The crossed-off rule targets `.oven-name-text`, not the whole name line: `text-decoration`
propagates to descendants and a child cannot opt out, so the team, grade and note sit outside the
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
4. **Recompute heat and re-render.** Heat is `fpRank - myRank`, so moving a player necessarily
   changes his rail and the smoothed wash around him. That is the point: drag someone up and watch
   him go flame.
5. **Hand the rows to the host.** `onReorder(rows)` receives them in the exact shape a CSV import
   writes, and `/the-bakers-oven/{leagueId}/{rosterId}` writes them straight back into the same
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

## Verification

Run `python3 server.py`, open `http://localhost:8000`.

**Routes**
1. `/the-bakers-oven` is the league list; `/the-bakers-oven/1384025526670233600` is that
   league's team picker; `/the-bakers-oven/1384025526670233600/1` is roster 1's board.
   Check with `curl -s localhost:8000/… | grep -c 'id="leagues"'` — only the list page has it.
2. `/the-bakers-oven/abc` and `/the-bakers-oven/{id}/1/2` both 404.
3. Legacy `/the-bakers-oven/1` redirects to `/the-bakers-oven/{onlyLeague}/1` with one saved
   league, and to `/the-bakers-oven` with two.
4. Signed out, every Oven URL bounces to `/account`. Signed in as a **non-admin**, all three
   render, "The Baker's Oven" appears in the hamburger drawer, and `/football` shows its card.

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

**Draft data** (league is `pre_draft` until 2026-08-31, so this is testable now)
17. All **7** keepers render struck through with a `KEPT · owner` tag.
18. `computeClock().onTheClock` is **1**, not 8 — proving first-unfilled, not `length + 1`. (No
   longer visible in the console; check it from the devtools console via `OvenBoard.state.clock`.)
19. Console reads **Your pick / 2.01 / 10 away** (pick 12 is a keeper; 9 and 12 are filled), and
    the board carries a `The chalk · 10 gone before you're up` header above a hatched band that
    ends at the `You choose from here · 2.01` horizon.
20. Board pick list matches the fixture above.

**Live behavior**
21. When picks land: rows cross off with a flash, the tag shows `R.PP · owner`, **scroll position
    holds**, and the marker's "N away" count drops.
22. A commissioner undo restores the row and hides its tag.
23. DevTools Network: a ~1.2 KB `/draft/{id}` call per tick and **no** `/picks` call until
    `last_picked` changes. Background the tab → polling stops. Foreground → immediate poll.
24. Offline → "Reconnecting (n) · last update Nm ago", backoff widens; online → recovers.

**Targets & Projections**
25. The tab sits on the right edge of both `/the-bakers-oven/{leagueId}` and
    `/the-bakers-oven/{leagueId}/1` — but **not** the top-level league list, which has no draft
    context to project from. Opening it on a wide screen leaves the board fully clickable.
26. The pin at the end of a board row adds him: it flips to `✓`, the row gains a flame inner rail,
    and he appears in the queue. Pin again (or `×` in the drawer) removes him. Same on a phone —
    the pin is the only route in, on every device.
27. Dragging a board row does **not** touch the queue: it re-ranks him (checks 32–36).
28. Projections lists **16** rounds. Roster 1's R14 keeper fills round 14 with a `kept` chip;
    made picks show `picked`; the traded-away R7 and R12 read "No pick this round".
29. Round 2 does not recommend the same player round 1 already took — that is the look-ahead.
30. Queue a player who is 40 spots down: he appears in a later round with a 🎯 chip, and his
    targets-view window chip agrees with the round he shows up in.
31. Filter the board → re-render → targeted rows are still marked, and the surviving rows are
    still in ascending personal-rank order.

**Re-ranking**
32. Drag the #40 row up onto the seam above #8: he lands at 8, everyone from 8 down shifts one,
    the `RK` column renumbers 1..N with no gaps, and his heat rail goes flame (he is now 30+ spots
    ahead of consensus). The drawer does not open and the queue is unchanged.
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

**Degraded**
38. Rename `data/fp_redraft.json` → board still renders from CSV, with no heat rail or row wash
    (nothing to disagree with).
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
