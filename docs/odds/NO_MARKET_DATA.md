# "No market data" — analysis

Investigation of why many odds coupons/cards render with no prices. The
front-end now **hides** these empties (see "Current handling" below), but the
underlying data gap remains and should be fixed upstream in the FanDuel capture.

## Where the message came from

`buildCoupon()` in [views/odds.html](../views/odds.html) rendered the literal
`'No market data'` whenever a coupon's runner list was empty:

```js
const runners = couponRunners(couponRef);
if (!runners.length) {
  body.textContent = 'No market data';   // now: return null (hidden)
}
```

`couponRunners()` returns `[]` whenever the coupon has no `marketId`, or that
id isn't present in `MARKETS`:

```js
const market = coupon && coupon.marketId ? MARKETS[coupon.marketId] : null;
return (market && market.runners) || [];
```

So the renderer was behaving correctly — the gap is in the **data**, not the
display logic.

## Root cause — it's in the FanDuel snapshot, not the code

`MARKETS` comes straight from `data.attachments.markets` in
[data/fd.json](../data/fd.json), which is a **captured FanDuel API snapshot**
(no script in the repo produces it — `build.py` / `scripts/` don't generate it).

Counts from the actual file:

- **792 coupons** in the layout, but only **186** have a `marketId` that
  resolves to runners.
- **606 coupons have no `marketId` at all.** Their raw shape:

```json
{ "id": 9700, "type": "OUTRIGHTS",
  "externalMarketId": "42.317325359",
  "hasAttachments": false,            // ← prices were never loaded
  "attachmentsFullyLoaded": true,
  "display": [] }
```

These are real FanDuel markets that exist in the navigation, but whose
odds/runners were **never attached** when the snapshot was captured
(`hasAttachments: false`). FanDuel lazy-loads market attachments; fd.json only
contains markets that happened to be expanded. The `externalMarketId` (e.g.
`"42.317325359"`) is the handle to fetch the missing attachment.

## Scope — what was blank

Of the tab-reachable cards, **261 coupons across 18 cards** rendered "No market
data". Many cards were *entirely* empty:

| Tab          | Card                             | Blank / Total |
|--------------|----------------------------------|---------------|
| NFL Draft    | Position of Team Picks           | 55/55         |
| Playoffs     | To Make the Playoffs             | 33/33         |
| Playoffs     | To Make Playoffs                 | 32/34         |
| Divisions    | Division Finishing Position      | 32/32         |
| NFL Draft    | To Be a Top X Pick               | 27/27         |
| NFL Draft    | NFL Draft Position O/U           | 23/23         |
| NFL Draft    | NFL Draft 2027                   | 17/17         |
| NFL Draft    | First of Position Drafted        | 16/16         |
| Divisions    | Division Exact Finishing Orders  | 8/8           |
| Awards       | NFL Awards Odds                  | 4/11 (partial)|
| NFL Draft    | Head to Head                     | 3/3           |
| Player Props | Regular Season Receiving Yards   | 3/38 (partial)|
| Playoffs     | To Make/Miss the Playoffs        | 2/2           |
| NFL Draft    | Team to Draft Player             | 2/2           |
| ...          | (4 more single-coupon cards)     | 1/1 each      |

Whole categories (NFL Draft, Playoffs, Divisions) are blank because those market
groups were never expanded at all — not because individual prices are missing.

## Current handling (front-end hide)

As an interim measure, empties are hidden rather than shown:

- `buildCoupon()` returns `null` for a coupon with no runners (the render loop
  already skips `null`), so empty coupons no longer appear.
- `cardHasData()` / `tabHasData()` helpers skip fully-empty cards and tabs in the
  navigation lists (`renderTab`, `renderTabList`).
- A directly-linked empty card shows "No markets available." instead of a blank
  page.

## The real fix (future task)

Repair the data capture: when fetching FanDuel data, the markets with
`hasAttachments: false` need a follow-up request (keyed by `externalMarketId`)
to load their runners/prices before writing `fd.json`. Once the snapshot is
complete, the hide logic becomes a no-op and all 18 cards populate.
