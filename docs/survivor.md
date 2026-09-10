# NFL Survivor Pool

A survivor pool at `/football/survivor`. Pick **one team a week to win outright**,
never reuse a team, and one wrong pick ends your season. Rules follow the
standard format described in
[PoolGenius's survivor primer](https://poolgenius.teamrankings.com/nfl-survivor-pool-picks/articles/how-nfl-survivor-pools-work-rules-formats-tips/).

It shares a board with the [Pick 'Em](pickem.md) — `pickem_games`, filled and
graded by `scripts/pickem_capture.py` — and shares its skin. Two games, one
slate.

## Rules as implemented

| Rule | Choice | Why |
| --- | --- | --- |
| Grading | **Straight up**, off the score | This is what a survivor pool *is*. The spread is still shown, greyed, because it remains the best one-number answer to "who wins". |
| Team reuse | **Once per season** | The rule that makes it a season-long game rather than eighteen coin flips. |
| Tie | **Counts as a loss** | The default the big contests run (Circa says so in as many words), and the only reading under which "survive" means what it says. |
| Missed week | **Elimination**, once every game of the week has kicked off | At that moment there is no pick left to make. Triggered on the last *kickoff*, not the last whistle, so the standings and the pick page agree about when the week is over. |
| Lock | **Per game, at its own kickoff** | Same as the Pick 'Em. You may change your mind all week as long as *your* game has not started. |
| Entries | **One per account**, no buybacks, no strikes | There is no roster and no sign-up step, so an entry is an account. |
| Entry start | **Your first pick** | A player who joins in week 4 is not retroactively eliminated for the three weeks before they had an account. From that pick onward every week counts. |
| End of season | Survivors after week 18 split; if the field is wiped in one week, they split | Standard. Not modelled in code — there is nothing to compute. |

## Decisions

- **Elimination is derived, never stored.** There is no `eliminated` column and
  there must not be one. An entry's fate is a function of its picks and the
  scores, both already in the database; a stored verdict is a second copy of an
  answer that can go stale. A game re-graded after a scoring correction would
  otherwise leave a player marked dead with a winning pick on the board and
  nothing would notice. `rules.walk_entry()` replays the season every time it is
  asked — at most eighteen rows, one pass.
- **The two structural rules are the two keys.** One pick per week is the
  primary key `(user_id, season, week)`; a team spent once is the unique index
  `(user_id, season, team)`. Python checks both so the error is a sentence
  rather than a 23505, but the database is what makes them *true* — two tabs
  racing a save cannot produce a second pick or a second use of a team.
- **A game with no frozen line is still pickable here.** The Pick 'Em drops it
  because there is nothing to grade it against; Survivor grades on the score, so
  it is on this board like any other. This is why the payload has no `n`: every
  game in the week is pickable, always. `pickem_capture.grade_season()` already
  writes the score for such a game and leaves `result` null, which is exactly
  what this needs.
- **`result` is not read.** That column is the *ATS* verdict against the frozen
  line — the Pick 'Em's answer. `rules.winner()` reads `away_score`,
  `home_score` and `status` itself. Reusing `result` would silently make a
  line-less game unpickable and a push look like a tie.
- **No save button.** The Pick 'Em holds a working set and commits it on Save
  because a week there is a permutation of sixteen confidences that has to move
  as a unit. Survivor is one team: there is no half-made state, and a Save
  button could only add a way to leave the page believing you had picked when
  you had not — the most expensive mistake this game has. A tap **is** the pick,
  written immediately and reverted on screen if the server refuses it.
- **A separate table, not a column on `pickem_picks`.** Sharing would mean a
  nullable confidence, a nullable team and a discriminator every query has to
  remember. The thing worth sharing is the *board*, and that is shared.
- **One read of the board serves the whole page.** `store.load_season_games()`
  (narrow columns) rather than the Pick 'Em's wide per-week read: Survivor needs
  none of the `jsonb`, and it *does* need the rest of the season, because the
  used-team rule and the elimination walk are both season-long.

## The lock and the reveal

**Invariant, identical to the Pick 'Em: another entry's pick for a game that has
not kicked off is never *selected* from the database.**

- **Read** — `store.visibility_clause()` builds the filter from games whose
  kickoff has passed by the server's clock. It is expressed in two halves and
  OR'd: a week where *every* game has kicked off is named by week (one short
  clause), and a week still in progress has its kicked-off games named
  individually. Over a season the first half absorbs seventeen weeks and the
  second never holds more than one slate, so the URL stays short instead of
  growing a 272-id `in.()` list by December.
- **Write** — a pick may be set, changed or cleared right up until the game it
  names kicks off, and not one second after. Both directions are the same
  retro-edit and both 409.
- **Standings DO carry picks**, unlike `api/pickem-standings.py`, and that is
  the whole content of the page. So this endpoint takes on the visibility rule
  instead of avoiding it. The one exception is the requester's own row, read in
  full and flagged `hidden` per cell so the page can say "only you can see this".

**The entry is not the secret — the pick is.** A pick is two facts: *that* you
picked, and *what* you picked. Only the second can be kept, and the first cannot:
the rules require a pick every week from everyone still alive, so the field is
common knowledge the moment the pool exists. Withholding it protected nobody and
made the page wrong about the size of the pool — in week 1 of 2026, seven entries
all read as a one-entry pool to each other, because the only game that had kicked
off was the Thursday nighter and nobody had picked it.

So `store.load_entry_weeks()` reads `select=user_id,week` — **no `team`, no
`game_id`**, which is exactly why it is the one read in that file allowed to skip
the reveal filter. Every entry gets a standings row; a week it names but may not
read carries a teamless cell flagged `masked`, rendered as a lock. The distinction
the table now draws is the one that was missing: 🔒 is "their pick is in", `·` is
"they have not picked". `walk_entry()` grades a masked cell `pending` and stops
there — the same place it stopped when the pick was absent entirely — so masking
changes the **count** and never a **status**.

The board endpoint takes the same read for the same reason, but only for
`pool.entries`: `chips()` keys a name to a game by `game_id` and a masked pick has
none, so it attaches to nothing. Naming the field is fine; naming which of sixteen
games each of them took is not.

**The property that makes this cheap:** an entry's fate turns only on weeks that
have been played, and a played week has kicked off — so every pick that could
change who is alive is one the request is already allowed to see. Hidden picks
sit on games that have not started, which `walk_entry()` stops at regardless.
The visible set is therefore not an approximation of the standings; it **is**
the standings. An entry whose only pick is a hidden one still appears — as a row
with a masked cell and nothing survived — because who is in the pool was never
the part under the lock.

## Schema

`scripts/sql/survivor_picks.sql`, run once in the SQL editor. No second table —
the board is `pickem_games`.

`game_id` is stored alongside `team` and is not redundant: the reveal filter is
a WHERE on `game_id`, and deriving the game from `(season, week, team)` at read
time would mean joining the board to decide what may be shown, which is the
shape that leaks. Same `bigint` in SQL / **string** on the wire boundary as the
Pick 'Em, converted in `store._shape` and `store.save_pick` only.

## Backend

- **`api/_survivor/rules.py`** — pure, stdlib-only, no I/O. `winner()`,
  `outcome()`, `closed_weeks()`, `walk_entry()`, `rank_rows()`,
  `validate_pick()`. The whole game is in this file.
- **`api/_survivor/store.py`** — PostgREST access and `visibility_clause()`. It
  **imports** `api/_pickem/store.py` rather than restating it: "has this game
  kicked off?" has one implementation and both games consult it.
  `load_visible_picks()` is the only path by which a team reaches a caller;
  `load_entry_weeks()` names the field without reading one.
- **`api/survivor.py`** — `GET` the week board, `PUT` one pick
  (`team: null` clears).
- **`api/survivor-standings.py`** — `GET` the field. Its own file so its
  warm-instance memo does not evict the week board's.
- No capture script. `scripts/pickem_capture.py` already writes the scores this
  reads, including for games it cannot grade against the spread.

## Frontend

- **`scripts/primary/survivor-api.js`** — four calls, write awaited and its
  error surfaced. Every rejection the server can produce is written to be shown
  verbatim, so the pages print `err.message` rather than inventing copy.
- **`scripts/primary/survivor.js`** — rows, the spent strip, the standings grid.
  It loads *alongside* `pickem.js` and reuses `pkEsc`, `pkKickoffLabel`,
  `pkSpreadFor`, `pkSpreadLabel`: the crest, the Eastern kickoff and the way a
  spread is written are not different here, and a second implementation would
  drift.
- **`styles/primary/survivor.css`** is a **layer over** `pickem.css`, not a
  skin. Views link `pickem.css` first and `survivor.css` second, and several
  rules win on source order alone (`.sv-game`'s single-column grid over
  `.pk-game`'s three). Swapping the two links re-lays-out the board. Two
  `<link>`s rather than an `@import` because `build.py` only hashes literal
  `href`/`src`, so an `@import` target never gets a `?v=`.
- **`views/football/survivor{,-pick,-standings}.html`**.

## Security model

Identical to the Pick 'Em's, including the `X-User-Id` tradeoff and the
`load_usernames()` exposure — see
[pickem.md § Security model](pickem.md#security-model-accepted-tradeoff-app-wide).
Forging the header is competitively valuable here too, and no more so.

## Verification checklist

1. **Schema** — run the SQL file; confirm the table, the PK, **both** indexes
   (`survivor_picks_team_idx` is the reuse rule) and RLS enabled-and-closed.
2. **The walk** — a win chain, a loss, a tie, a missed shut week, a late joiner,
   a pick made after elimination (renders `void`, changes nothing), and an entry
   with no picks at all (not an entry). Then the same set with a masked cell
   appended: every status, `out_week` and `survived` must come back identical,
   and `teams` must never contain a null.
3. **Tie ≠ pending** — a 20–20 final eliminates; the same row with `status`
   still `'live'` does not.
4. **Reuse** — picking a spent team → 400 naming the week it went in.
   Re-picking the team already down for *this* week → 200, idempotent.
   Then force it past Python and confirm the unique index refuses it.
5. **Line-less game** — set `spread_home` null on one game: it is still on the
   board, still pickable, and grades normally off the score.
6. **Write lock** — with a picked game's `kickoff` in the past, changing it →
   409; clearing it → 409; picking a *different* unlocked game that week → 200.
7. **Eliminated entry** — any `PUT` → 409 naming the week it went out; `GET`
   still 200 and the board renders read-only.
8. **Isolation / reveal, the critical one** — as B pick a Sunday game, then as A
   `GET /api/survivor-standings`: the raw body contains none of B's
   abbreviations for that week, but it **does** contain B's row, with that week
   `masked: true` and `team: null`. Put that `kickoff` in the past in SQL: the
   mask drops and the team appears. A's own hidden pick comes back flagged
   `hidden: true` for A and `masked: true` for B — never the abbreviation.
9. **Active gate** — `users.status = false`: `PUT` → 403, `GET` → 200.
10. **Ownership** — a `PUT` naming a game B picked only ever writes under A's
    `user_id`.
11. **Standings** — alive outranks a longer run that ended; ranking is
    competition-style (1, 1, 3); a missed week renders `✕` and a post-mortem
    pick renders drained.
12. **Routing** — all four page URLs including bare `/football/survivor/pick`,
    in dev and on a preview deploy. Confirm `/api/survivor-standings` is not
    served the week board (`"/api/survivor-standings".startswith("/api/survivor")`
    is `True`, which is why both branches match on the exact path).
13. `python3 build.py --check` passes.
