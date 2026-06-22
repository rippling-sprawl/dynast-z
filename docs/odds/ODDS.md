# Odds Page

A betting-odds comparison page for dynast-z that parses two sportsbook feeds
(FanDuel + DraftKings) and renders them in a tabbed, deep-linkable UI.

- **Route:** `/odds` → `views/odds.html`
- **Home tile:** 🎲 "Odds" on the home page (`views/index.html`)
- **Data sources:** `data/fd.json` (FanDuel), `data/dk.json` (DraftKings)
- **UI reference:** `data/fd_layout.png`

---

## Wiring

| File | Change |
| --- | --- |
| `views/index.html` | Added 🎲 "Odds" home tile linking to `/odds` (after Football, before News). |
| `server.py` | Added exact route `elif self.path == "/odds": self.path = "/views/odds.html"` (after `/football`). |
| `views/odds.html` | The entire feature — markup, `<style>`, and an inline `<script>`. |

---

## Navigation model (hash routing)

Flask matches `/odds` exactly, so all in-page navigation uses the URL **hash**
(`location.hash` + `hashchange`). This keeps routing client-side and survives
refresh/share without server changes.

Three levels, each a deep link:

| Level | Hash | View |
| --- | --- | --- |
| 0 | `#/` | Tab list (`renderTabList`) |
| 1 | `#/<tabId>` | Card list for a tab (`renderTab`) |
| 2 | `#/<tabId>/<cardId>` | Coupons for a card (`renderCard`) |

Tabs and cards both render as **vertical lists**. Pinned breadcrumbs
(`renderCrumbs`) let you jump back up the path.

### In-Active partitioning

`renderTabList()` splits tabs into **active** and **In-Active** groups (matched
by title: `Games`, `Week 1`, `NFL Draft`), preserving
`layout.tabsDisplayOrder` within each group. The "In-Active" `.odds-section`
heading only renders when there are inactive tabs.

---

## Data parsing

### FanDuel (`fd.json`)
Nesting: `layout.tabs[tabId]` → cards → `coupons[]` → `marketId` →
`markets[marketId].runners[]` → `runnerName` +
`winRunnerOdds.americanDisplayOdds.americanOdds` (signed integer).

### DraftKings (`dk.json`)
Schema: `{ sports, leagues, events, markets, selections, subscriptionPartials }`.
Selections carry Over/Under with American odds as strings using a **unicode
minus** (U+2212).

### Cross-book matching
The two books don't share IDs and runner names differ ("Cam Ward" vs
"Cameron Ward"). Matching is fuzzy by player name (`normName`, `findDkPlayer`):
normalize (lowercase, strip punctuation), then fall back to **last name equal +
one first name is a prefix of the other**.

---

## Market layouts

Two structural types, detected by `parseRunner()` (regex
`/^(.*?)\s+(Over|Under)\s+([\d.]+)\s*$/`):

- **Field-based** (Super Bowl, Divisions, Conferences, etc.) — runner-name row
  + odds badges per book. `buildFieldBody`.
- **OU-based** (Player Props) — **FD / DK as column headings**, odds grouped
  vertically per column, no horizontal scroll. `buildOuBody` / `ouColumn` /
  `ouCell`.

The FD/DK heading is **pinned once at the top** of a card (`buildOuHead`), not
repeated per coupon. `showDk` is computed at card level
(`ouRefs.some(couponHasDk)`) and threaded to every coupon so columns stay
aligned even when a card (e.g. Passing TDs) has no DK data.

---

## Title cleanup

Three layered strippers remove redundant text:

| Helper | Removes |
| --- | --- |
| `stripYear` | Trailing ` 2026-27` season suffix |
| `stripMarketTitle` | Entity prefix repeated in runner names |
| `stripSectionTitle` | Card/section title repeated in coupon titles |

Plus `fmtAmerican` (FD signed int, `+` prefix) and `fmtDk` (replaces U+2212).

---

## Sticky / pinned layout

The site `header` is itself `position: sticky; top: 0`. The Odds page stacks
two more sticky layers below it, with offsets measured in JS
(`applyStickyTops`, recomputed on `hashchange` and `resize`):

1. `header` (height measured)
2. Breadcrumbs (`.odds-crumbs`) — pinned below header
3. FD/DK heading (`.odds-ou-head`) — pinned below breadcrumbs

`main.home` has 0 horizontal padding on this page; content is centered in
`.odds-wrap` (max-width 900px).

---

## Key functions (inline `<script>`)

- Routing: `route`, `renderTabList`, `renderTab`, `renderCard`, `renderCrumbs`,
  `applyStickyTops`, `init`
- Coupons: `buildCoupon`, `buildFieldBody`, `buildOuBody`, `buildOuHead`,
  `ouColumn`, `ouCell`, `couponRunners`, `isOuCoupon`, `couponHasDk`
- Parsing/format: `parseRunner`, `normName`, `findDkPlayer`, `buildDkIndex`,
  `fmtAmerican`, `fmtDk`, `stripYear`, `stripMarketTitle`, `stripSectionTitle`,
  `escapeRe`

Validated changes with `node --check` on the extracted script block.
