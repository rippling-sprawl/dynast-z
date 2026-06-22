# Odds display — mobile layout & empty-market work (session log)

Summary of the work done on the odds display (`views/odds.html`) covering the
"no market data" investigation and the mobile/iPhone layout pass. Preserved from
a compacted working session for future reference.

## Requests addressed

1. **Understand the "no market data" issues** — see
   [NO_MARKET_DATA.md](NO_MARKET_DATA.md) for the full root-cause analysis.
2. **Hide empty coupons and markets** (interim fix) — empty coupons/cards/tabs
   are now hidden in the front-end.
3. **Fit the standard columns on an iPhone viewport** — reduce `odds-book-label`
   size/spacing on narrow views; slightly reduce player/team name fonts.
4. **Refine the O/U book columns** — reduce book-label width ~25%, replace
   bordered/white-background boxes with single vertical-line separators, and put
   the red/green arrows inline with their value while keeping the value centered.

## Architecture notes

- Static HTML/CSS/vanilla-JS app, deployed on Vercel (dynastz.com).
- `server.py` — local Python `http.server` on port 8000 (`python3 server.py`),
  used only for local preview/verification.
- Books: FanDuel ("FD"), DraftKings ("DK"), ESPN ("SCORE"). FMV = average of
  available book lines.
- `data/fd.json` — captured FanDuel API snapshot
  (`{ layout: { tabs, cards, coupons }, attachments: { markets } }`). **No repo
  script produces it.**
- Hash routing: `#/<tab>`, `#/<tab>/<card>`.
- O/U (player-prop over/under) coupons render differently from field-market
  coupons (`.odds-coupon.is-ou`).

## Key implementation details (`views/odds.html`)

### Empty-market hiding
- `couponRunners(ref)` returns `(market && market.runners) || []`.
- `cardHasData(card)` / `tabHasData(tab)` helpers skip fully-empty cards/tabs in
  `renderTab` / `renderTabList`.
- `buildCoupon()` returns `null` when `runners.length === 0` (render loop already
  skips `null`); the old `'No market data'` text branch was removed.
- A directly-linked empty card shows "No markets available." instead of a blank
  page.

### Mobile layout
- **CSS variables live on `.odds-wrap`, not `:root`.** This matters: a media
  query that overrides them on `:root` is outranked by the closer `.odds-wrap`
  declaration in the inheritance chain, so the override silently does nothing.
  The narrow breakpoint must target `.odds-wrap`:
  ```css
  @media (max-width: 600px) {
    .odds-wrap { --nb-name-w: 92px; --nb-col-w: 42px; }
    /* ... */
  }
  ```
- Default `--nb-col-w` reduced 76px → 57px (~25%); narrow breakpoint 42px.
- Player/team name fonts trimmed (14px → 13px desktop, 12px narrow).
- There IS a viewport meta tag, so real iPhones apply the media query.

### Book-label separators & inline arrows
- Removed `border` + white `background` from `.odds-coupon.is-ou .odds-book-label`.
- One hairline divider per column:
  `.odds-coupon.is-ou .odds-col + .odds-col { border-left: 1px solid var(--nb-line); }`.
- `lineWithArrow()` wraps the value in `<span class="odds-line">`; the value is
  centered and `.odds-arrow` is `position: absolute; left: 100%`, so the arrow
  rides the same line to the right without pulling the value off-center.

## Verification harness (transient)

Visual checks used headless Chrome driven via the Chrome DevTools Protocol from a
Node script (Node 24 global `WebSocket`/`fetch`, no external deps):

- `--headless=new` hung on this machine; use `--headless=old` with
  `--remote-debugging-port=9222`.
- Headless ignores `--window-size` for `width=device-width` (renders desktop);
  use CDP `Emulation.setDeviceMetricsOverride` with `mobile:true` for true
  iPhone-width emulation.
- macOS has no `timeout` command — use a background-process + poll loop instead.

All temp files, the test server, and Chrome were cleaned up after verification.

## Deferred / future task

The real fix for the empty markets is upstream in the data capture: markets with
`hasAttachments: false` need a follow-up request keyed by `externalMarketId` to
load their runners/prices before writing `fd.json`. Once the snapshot is
complete, the hide logic becomes a no-op and all affected cards populate. See
[NO_MARKET_DATA.md](NO_MARKET_DATA.md) for the affected-card breakdown.
