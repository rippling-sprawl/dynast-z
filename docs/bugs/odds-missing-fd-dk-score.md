# /odds — Missing FD / DK / Score odds audit

_Date: 2026-06-12_

## Verdict

For the four flagged markets, the missing **DK** and **Score** odds are **almost
entirely root cause #2 — "not supplied in the JSON Recorder,"** not a naming
mismatch. The DK and Score recordings were each captured from a **single narrow
page**, so only the markets that page lazy-loaded were ever in the bundle. The
parsers' "skipped/unmapped" lists contain **none** of these market names — you
can't mis-map a market that was never captured.

Proof is FD: its bundle contains **all** of these markets (under wildly different
names like `MISS_PLAYOFFS_AFC_SGP` and `AP NFL Regular Season MVP 2026-27`), and
FD is fully populated — because FD was recorded across the whole futures page.
The pipeline works; the DK/Score recordings just didn't cover enough pages.

## Recording coverage (the smoking gun)

| Book | Recorded page (`data/imports/`) | Consequence |
|------|------|------|
| FD | full content-managed futures page | 255 markets captured → near-complete |
| DK | `…/nfl?category=futures&subcategory=playoffs&nav_1=`**`to-make-the-playoffs`** | only make-playoffs + division/conf winners + SB + rookie-awards + yard leaders |
| Score | `…/competition/nfl#`**`player_totals`** | only player O/U totals + 5 outright LISTs that happened to load |

## Ground-truth coverage vs. the ticket

From `data/outrights.json`. **⚠️ flags where the ticket disagrees with the data:**

| Market (key) | FD | DK | Score | Ticket said |
|---|---|---|---|---|
| Most Reg. Season Wins (`most_wins`) | ✗ | ✗ | **✓ 32** | "missing DK & Score" — ⚠️ Score is present |
| MVP / OPoY / DPoY | ✓ | ✗ | ✓ | "Awards missing DK & Score" — ⚠️ Score present for these |
| ORoY / DRoY | ✓ | **✓ ~52** | ✗ | ⚠️ DK present for these |
| CoY / CPoY | ✓ | ✗ | ✗ | matches |
| To Make Playoffs (`make_playoffs`) | ✓ | **✓ 32** | ✗ | "missing DK & Score" — ⚠️ DK is present |
| To Miss Playoffs (`miss_playoffs`) | ✓ | ✗ | ✗ | matches ✓ |

## Per-market root cause

**Regular Season Wins** — renders two different ways. As the outright leader board
(`most_wins`), only **Score** publishes it as a single LIST market; FD/DK instead
express it as 32 per-team Over/Under totals (FD: `"Buffalo Bills - Regular Season
Wins 2026-27"`; Score: `"BUF Bills Regular Season Wins"` in `data/score/wins.json`).
- **DK missing:** *not captured* — DK's per-team win totals live on a different
  subcategory page that wasn't recorded.
- **Score "missing":** if this means the win-totals O/U card, the data exists in
  wins.json but FD↔Score team names differ (`"Buffalo Bills"` vs `"BUF Bills"`);
  matching relies on the last-name fallback in `findIndexedPlayer`
  (`views/odds.html:486-531`). This is the one spot where a **naming mismatch (#1)**
  could plausibly drop Score — worth a direct check.

**Awards** — split outcome:
- **mvp / opoy / dpoy:** DK *not captured* (no MVP/POY market name anywhere in DK
  bundle); Score **is present**.
- **oroy / droy:** Score *not captured* (no rookie-award LIST in Score bundle); DK
  **is present**.
- **coy / cpoy:** *not captured* by either DK or Score.

**To Make Playoffs** — DK **is present** (`"To Make Playoffs"` → `make_playoffs`);
only **Score** missing, and *not captured* (no playoffs LIST in the player_totals
bundle).

**To Miss Playoffs** — DK *not captured* (the DK page was
`nav_1=to-make-the-playoffs` — the "miss" sub-nav never loaded); Score *not
captured*. FD has it because FD's bundle carries `"To Miss the Playoffs AFC/NFC
2026-27"`, which `fd_canon` merges.

## Is anything actually a naming (#1) problem?

Checked both parser skip-lists:
- **Score** (`parse_score_outrights.py:27-33`): **zero** unmapped LIST markets —
  `SCORE_MARKETS` exactly covers what was captured. No naming gap.
- **DK** (`parse_dk_outrights.py:33-46`): every unmapped name is a **player prop**
  (`"NFL 2026/27 - Josh Allen Regular Season Passing Yards"`), handled by the other
  parser — not an outright gap.

So for DK/Score outrights, there is **no name-mapping miss**. The single naming
candidate is the FD-vs-Score team-name format on the win-totals O/U card.

## Recommended fix

Re-record DK and Score with **full page coverage**, then re-run the outright
parsers (they merge non-destructively; FD/Score columns are never clobbered):
- **DK:** visit each futures subcategory — `to-miss-the-playoffs`, MVP, OPoY, DPoY,
  CoY, CPoY, Most Wins — so those markets land in the bundle. (Make-playoffs,
  rookie awards, division winners already work.)
- **Score:** open the awards/futures shelves for ORoY, DRoY, CoY, CPoY, and
  Make/Miss Playoffs — the player_totals recording missed them.

No parser code changes are required for DK/Score; the mapping tables already match
DK/Score's naming for every market they actually serve. The only code-side item to
verify is the Score team-name match on the Regular Season Wins O/U card
(`views/odds.html:486-531`).
