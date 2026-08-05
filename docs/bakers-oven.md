# The Baker's Oven — live Sleeper draft companion

A big board for the **Keepers & Weepers** league (`1384025526670233600`) that updates itself
against the live Sleeper draft. Players cross off as they're picked or kept, your next pick
tracks its own position down the board, and the players you're high and low on show as
warm and cool regions.

Routes:

| URL | Page |
|---|---|
| `/the-bakers-oven` | Draft status, CSV import, 12-team picker |
| `/the-bakers-oven/{rosterId}` | The big board for that team (baker28 = roster 1) |

`{rosterId}` is the Sleeper **roster_id**, not the draft slot and not a user id.

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
| `views/football/oven-index.html` | Team picker, draft status, CSV import |
| `views/football/oven-board.html` | The board; boot sequence and poller wiring |
| `styles/primary/bakers-oven.css` | All `.oven-*` styles |
| `scripts/primary/oven-config.js` | `window.OVEN` — league id, identity, tuning constants |
| `scripts/primary/oven-csv.js` | `window.OvenCSV` — RFC-4180 parser, template, export |
| `scripts/primary/oven-draft.js` | `window.OvenDraft` — Sleeper client, pick math, poller |
| `scripts/primary/oven-board.js` | `window.OvenBoard` — merge, heat, render, patch |
| `scripts/fetch_fp_redraft.py` | Offline FantasyPros half-PPR scrape |
| `data/fp_redraft.json` · `data/fp_redraft_meta.json` | Generated, committed |

Modified: `vercel.json` (rewrites), `server.py` (2 view branches + `/api/football/resolve` +
a `log_message` fix), `scripts/base/nav.js`, `views/home/football.html`.

`draft_id` is derived at runtime from the league object — not hardcoded — so a new season or a
redraft needs no code change.

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
| `Grade` | `Like`, `Opinion` | `love` / `like` / `fade` / `avoid` |
| `Note` | `Notes`, `Comment` | Free text, shown on the row |

The parser is a real RFC-4180 state machine, not `split(',')` — quoted commas, embedded
newlines, `""` escapes, CRLF/LF/CR, and a UTF-8 BOM all round-trip. **Download template** builds a
starter file from the current FantasyPros top 250, so the first upload is one edit away.

### Hot and cold

An explicit `Grade` wins. Without one, heat is `fpRank - myRank` — positive means you're higher
on him than consensus. Colors are the source spreadsheet's own endpoints (`#57BB8A` /
`#EB9891`) via `window.Heatmap.diverging`, in two channels: a full-saturation 4 px left rail
(the per-player signal) and a low-alpha row wash from a 5-row rolling mean (the *region*, so a
run of your guys reads as one continuous band).

The sheet's pale mid-tones are alpha-over-white; over this app's `#0f1117` the same hues
composite dark. Hue and ordering are faithful, luminance is inverted for dark mode — do not try
to reproduce the light-mode hex values literally.

### Expected-pick markers

The spreadsheet's sparse column-3 markers, recomputed live. For your k-th upcoming pick, the
marker sits after `pickNo - onTheClock` still-available players — "if the board goes chalk,
you're choosing from here." Unlike the static column, this honors keepers, traded picks, and
every pick actually made, and the markers rise up the board as players come off. Rows above the
first marker get a faint hatch: likely gone before you're up.

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

Two-phase, deliberately:

- `render()` — full `innerHTML` build. Boot, CSV import, sort/filter change.
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
1. `/the-bakers-oven` lists 12 teams, baker28's pinned first with a "you" tag.
2. `/the-bakers-oven/1` loads baker28's board; `/the-bakers-oven/11` the trade partner's.
3. "The Baker's Oven" appears in the hamburger drawer and as a card on `/football`.

**CSV**
4. Download the template → re-upload unmodified → 250 rows, 0 warnings, 250 matched.
5. Quoted commas (`"Smith, Jr., Bob"`), `""` escapes, CRLF, and a BOM all survive a round trip.
6. A junk extra column imports fine and is preserved; a file with no `Player` column errors clearly.
7. A misspelled name is **kept** on the board and listed as unmatched, never dropped.

**Draft data** (league is `pre_draft` until 2026-08-31, so this is testable now)
8. All **7** keepers render struck through with a `KEPT · owner` tag.
9. Status bar reads *Pick 1 of 192 · 7 off the board* — proving first-unfilled, not `length + 1`.
10. Next pick reads **2.01 · 10 away** (pick 12 is a keeper; 9 and 12 are filled).
11. Board pick list matches the fixture above.

**Live behavior**
12. When picks land: rows cross off with a flash, the tag shows `R.PP · owner`, **scroll position
    holds**, and the marker's "N away" count drops.
13. A commissioner undo restores the row and hides its tag.
14. DevTools Network: a ~1.2 KB `/draft/{id}` call per tick and **no** `/picks` call until
    `last_picked` changes. Background the tab → polling stops. Foreground → immediate poll.
15. Offline → "Reconnecting (n) · last update Nm ago", backoff widens; online → recovers.

**Sync**
16. Signed in, import on one browser → open another → same board. Signed out → localStorage only,
    still fully functional.

**Degraded**
17. Rename `data/fp_redraft.json` → board still renders from CSV with `—` in ECR.
18. No CSV at all → board seeds from FantasyPros ranks with an import prompt.

**Invariants**
19. `git status` shows no `package.json`, no lockfile, no new entry in `pyproject.toml`'s
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
