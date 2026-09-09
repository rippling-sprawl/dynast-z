# NFL Confidence Pick 'Em

A confidence pool at `/football/pickem`. Pick a side in every game of the week,
rank your picks 1..N, and score a pick's confidence when it lands. Picks are
graded **against the spread**, using the line as it stood at **3:00 AM ET on the
Tuesday** of that week.

## Decisions

- **Against the spread, not straight up.** A straight-up pool makes half the
  slate a formality — nobody agonises over ranking a 13-point favourite. The
  line is what makes every game a real decision, and it is the reason the
  Tuesday freeze exists at all.
- **The line is frozen once and never moves.** Lines drift all week; a pool
  graded on the current line would grade Sunday's picks against a number nobody
  saw when they picked. `pickem_games.spread_home` is written once by
  `scripts/pickem_capture.py` and nothing overwrites it. This is why the board
  is **not** `game_odds`, which `bdl_refresh.py` deliberately overwrites as
  often as every two minutes.
- **Consensus is the modal book price, not the mean.** An even -7.5/-8 split
  averages to -7.75 — a quarter line no book posted, which reads as invented
  and quietly makes a push impossible. The mode always yields a number somebody
  actually hung. Ties break by book priority (DraftKings first). `kalshi` and
  `polymarket` are excluded: their "spread" is derived from contract prices
  rather than posted.
- **Partial weeks allowed, and confidences run 1..N rather than 1..k.** N is
  the week's pickable-game count. A full week uses exactly 1..N; a partial week
  uses any k of those values.

  **This is forced by the per-game lock, not a preference.** A gapless 1..k
  cannot survive locking: pick four games ranked 1-4, let the Thursday game
  holding 4 kick off, then drop a Sunday game holding 2 — the remainder
  {1, 3, 4} has a hole only the locked pick could fill, and it must not be
  renumbered. The two rules cannot both hold. Widening the range dissolves it,
  costs nothing (a full week is still exactly 1..N), and creates no perverse
  incentive: 16 correct at 1..16 is 136, three correct at 14–16 is 45, so
  picking everything still dominates.
- **Per-game lock at kickoff**, ESPN-style, rather than one lock for the week.
  It is what people expect, and it means a Thursday result is visible while the
  Sunday slate is still live.
- **Points are computed at read time; the ATS verdict is stored.** The verdict
  is a pure function of two frozen inputs and never changes, so storing it makes
  a row auditable. Storing *points* would make the scheduled job fan writes
  across every user's pick rows — a cron reaching into per-user tables, which is
  the boundary the ownership model exists to keep clean — and would turn a
  scoring change into a backfill. If the pool ever outgrows read-time scoring,
  the escape hatch is a `pickem_standings` summary row written by the same job.
- **A game with no line is off the board.** Grading it straight up would be a
  different rule for one game on the slate. `n` shrinks instead, and the row
  says why.

## Architecture mirrored (do not deviate)

Same posture as [bets-persistence-supabase.md](bets-persistence-supabase.md):

- **Service-key REST, RLS closed.** All Supabase access is server-side via
  `SUPABASE_KEY`; both tables have RLS enabled and no policies. Authorization is
  enforced in Python.
- **Identity = `X-User-Id`.** The client sends `dz_user_id`; every pick row is
  written under that id.
- **"Active" = `users.status is True`, gated on writes only.** Reads are not
  status-gated — a deactivated account can still see where it finished.
- **Two runtimes kept in parity.** `api/pickem.py` + `api/pickem-standings.py`
  in production, mirrored in `server.py`. The mirror **delegates** to the same
  module rather than re-implementing it (`pickem_api()` / `pickem_standings_api()`,
  the `bun_notes_api()` pattern), because this is the one feature where the two
  runtimes drifting means leaking somebody's picks.
- **Shared code lives under `api/`, never `scripts/`.** Vercel does not bundle
  `scripts/**` with a function. `api/_pickem/` is the `api/_action/` pattern.
  The one crossing is `scripts/pickem_capture.py` importing
  `api/_pickem/scoring.py` — a local script reaching into `api/`, the safe
  direction.

## The lock, which is the load-bearing part

**Invariant: another user's pick for a game that has not kicked off is never
*selected* from the database.** Filtering after loading was rejected as a
design — it works until somebody adds a field to the response.

- **Read** — `store.load_visible_others()` builds `game_id=in.(<ids already
  kicked off>)` from the kickoff column of rows the request already read,
  against the server's clock. A hidden pick never enters a Python object.
- **Write** — `apply_week_picks()` requires a submitted week to reproduce every
  already-kicked-off pick exactly. Adding, changing and **omitting** one are all
  retro-edits and all 409. Unlocked games in the same payload are freely
  editable, which is what lets someone re-save on Sunday after the Thursday game.
- **Standings** carry points and never a pick, so they are safe at any lock
  state. Keep it that way: a `pick` field there would need the whole visibility
  rule and would not have it.

## Schema

`scripts/sql/pickem_games.sql` and `scripts/sql/pickem_picks.sql`, run once each
in the SQL editor. `pickem_games` is keyed by balldontlie's `game_id` — the same
id `data/nfl_schedule_*.json` and `game_odds` use, so nothing needs a mapping
table. `pickem_picks` uses the composite PK `(user_id, game_id)`, which **is**
the ownership guarantee, and one row per game rather than a per-week blob so the
reveal rule can be a WHERE clause.

**Type boundary:** `game_id` is `bigint` in SQL and a **string** on the wire
(JavaScript cannot hold a bigint exactly, and the schedule file has always
carried these as strings). The conversion happens in `store._shape_game` and
`store.save_week_picks`, nowhere else.

## Backend

- **`api/_pickem/scoring.py`** — pure, stdlib-only, no I/O. `grade()`,
  `points_for()`, `score_pick()`, `score_set()`, `rank_rows()`,
  `validate_week_picks()`. Imported by both handlers *and* the capture script,
  so the rule that grades a game has one definition.
- **`api/_pickem/store.py`** — PostgREST access and the visibility rule.
- **`api/pickem.py`** — `GET` the week board, `PUT` a whole week. The week is
  submitted as a unit because confidences are a permutation: no single pick is
  valid on its own.
- **`api/pickem-standings.py`** — `GET` the leaderboard. Its own file so its
  warm-instance memo does not evict the week board's.
- **`scripts/pickem_capture.py`** — freeze + grade.
  `.github/workflows/pickem-capture.yml` runs it half-hourly, with a dense
  window over both 07:00Z and 08:00Z on Tuesdays so the deadline is hit in EDT
  and EST alike.

## Frontend

- **`scripts/primary/pickem-api.js`** — three calls. **The write is awaited and
  its error surfaces**, a deliberate departure from `bets-api.js`: a bet that
  fails to save is still in the form it was typed into, a week of picks that
  fails silently is discovered in February.
- **`scripts/primary/pickem.js`** — rows, and the confidence model. The three
  mutations make an invalid state *unreachable* rather than merely rejected:
  picking takes the highest free value, un-picking releases its value without
  renumbering anything (which is what makes it safe once a game has locked),
  and choosing a taken value swaps. The server validates again regardless.
- **`views/football/pickem{,-picks,-standings}.html`**, `styles/primary/pickem.css`.

## Security model (accepted tradeoff, app-wide)

`X-User-Id` is a client-supplied, unauthenticated identifier — the same trust
model as `/api/sync` and `/api/bets`. A leaked or guessed `user_id` lets someone
read that user's *unlocked* picks by sending it as their own header.

This is the first feature where forging that header is **competitively**
valuable rather than merely nosy, so it is worth stating plainly. It is still
out of scope: hardening to real session tokens is an app-wide change.

One new exposure that is not a tradeoff but a decision: `/api/pickem-standings`
returns the usernames of every active account, because a leaderboard names the
people on it. `api/users.py` stays admin-only.

## Verification checklist

1. **Schema** — run both SQL files; confirm both tables, all three indexes, and
   RLS enabled-and-closed.
2. **DST** — `python3 scripts/pickem_capture.py --dry-run --replay --now
   2026-09-22T07:05:00Z` and `--now 2026-01-06T08:05:00Z`. The printed deadline
   must be Tue 03:00 ET in both, i.e. 07:00Z in EDT and 08:00Z in EST. This is
   the single most important check here.
3. **Freeze** — freeze a week; confirm rows with `spread_home` on the half-point
   grid, `frozen_at` set, `data.books` carrying every vendor row. Run it again:
   "already frozen", zero writes, zero balldontlie requests. `--force`
   re-freezes and leaves `result` and the scores intact.
4. **Tier failure** — run with a free or absent key: non-zero exit, nothing
   written, the tier message rather than a traceback.
5. **Grading** — against a finished season, hand-verify the ATS verdict on a few
   games including an exact push.
6. **Local end-to-end** (`python3 server.py`) — logged out, `/football/pickem`
   redirects to `/account`. As user A, pick a full week: rows appear with
   confidences 1..N, no repeats; reload and they survive. Un-pick three: those
   rows are gone, not orphaned, and nothing else renumbers.
7. **400s** — duplicated confidence; a confidence above N; 0; a game from
   another week; a team not in the game.
8. **Isolation / reveal, the critical one** — as B pick differently, then as A
   `GET /api/pickem?week=N` before any kickoff: `others` is `[]`, and the raw
   body contains none of B's abbreviations. Put one game's `kickoff` in the past
   in SQL: **only that game** appears under B.
9. **Write lock** — with that kickoff past, changing A's pick on it → 409;
   omitting it → 409; changing a *different* unlocked game in the same payload →
   200, locked pick untouched.
10. **Active gate** — `users.status = false`: `PUT` → 403, `GET` → 200.
11. **Ownership** — a `PUT` naming games B picked only ever writes rows under
    A's `user_id`; B's rows are unchanged.
12. **Standings** — totals hand-verify; a points tie breaks on `correct` and
    ranks competition-style (1, 1, 3); a `push` scores 0 for everyone and counts
    as neither correct nor pending; **no standings response contains a `pick`
    field anywhere**.
13. **Routing** — all four page URLs including bare `/football/pickem/picks`, in
    dev and on a preview deploy. Confirm `/api/pickem-standings` is not served
    the week board (`"/api/pickem-standings".startswith("/api/pickem")` is
    `True`, which is why both branches match on the exact path).
14. `python3 build.py --check` passes.
