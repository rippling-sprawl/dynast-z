# Odds Page — New Belgium Restyle & Column Alignment

Summary of the styling work done on the `/odds` page (`views/odds.html`).

## Goals

1. Adopt the color scheme, spacing, and fonts from `new_belgium.css` (New Belgium
   brewery's stylesheet) for the `/odds` page.
2. Use a monospace font for `.odds-book-label`.
3. Make the OU (player-prop) columns equal width, with `.odds-book-label` badges
   matching width and height across all columns, and FMV/FD/DK headings centered
   horizontally over their columns — regardless of each cell's text content.

## Design tokens (from new_belgium.css)

New Belgium uses a **light cream theme** (opposite of the odds page's original dark
theme), a signature orange-red accent, heavy uppercase display lettering, and sharp
(square, `border-radius: 0`) corners.

Extracted values:

- `body { color: #1b2533; background: #fffafb }`
- Signature accent: `#d74229`
- Cream surfaces: `#f2f1e3`, `#ebe9e2`
- Charcoal: `#373737`; orange: `#f68b21`; gold: `#f1c218`
- Fonts: `ccsamaritanlower-bold` (headings), `Adso` (display, uppercase, weight 800),
  `futura-pt` (body)
- `border-radius: 0` dominant; `letter-spacing: 1px` for labels

> Caveat: the custom web fonts (`Adso`, `futura-pt`, `ccsamaritanlower-*`) are loaded
> by New Belgium via Typekit/CDN and are **not** bundled into this project, so they
> fall back to Helvetica/Arial and system monospace. Wiring up a Typekit link would
> load the real faces.

## Implementation

### Round 1 — theme flip

Rewrote the `<style>` block in `views/odds.html`, flipping the dark theme to New
Belgium's light theme via CSS variables scoped to `.odds-wrap`:

```css
.odds-wrap {
  --nb-bg: #f2f1e3; --nb-surface: #fffafb; --nb-ink: #1b2533;
  --nb-ink-soft: #373737; --nb-muted: #857550; --nb-accent: #d74229;
  --nb-accent-2: #f68b21; --nb-line: #ddd8c2; --nb-line-soft: #e7e2d0;
  --nb-up: #6f8f1f; --nb-down: #d74229;
  --nb-display: "Adso", "ccsamaritanlower-bold", "Helvetica Neue", Arial, sans-serif;
  --nb-body: "futura-pt", "ccsamaritanlower-regular", "Helvetica Neue", Arial, sans-serif;
  --nb-mono: ui-monospace, "SFMono-Regular", Menlo, "Roboto Mono", "Courier New", monospace;
}
```

- `--nb-mono` applied to `.odds-book-label`, `.odds-odds`, and `is-ou` variants.
- Tabs/crumbs/headers use `--nb-display` (uppercase, letter-spaced).
- Square corners (`border-radius: 0`) throughout.
- Related intentional edits: `.index-body { background: #f2f1e3; }`; `.odds-coupon`
  reduced to just `border-top: 1px solid var(--nb-line);`.

### Round 2 — equal-width columns & uniform badges

Three edits to align the OU layout:

1. `.odds-coupon.is-ou .odds-coupon-body` — added `align-items: stretch` so the three
   columns share a common (tallest) height.

2. `.odds-col` — equal-width columns:
   ```css
   /* flex-basis 0 + grow 1 so FMV/FD/DK each take exactly a third of the body
      regardless of contents. min-width:0 lets them shrink evenly instead of being
      padded out to their text width. */
   .odds-col { display: flex; flex-direction: column; gap: 6px; flex: 1 1 0; min-width: 0; }
   ```

3. `.odds-coupon.is-ou .odds-book-label` — uniform box sizing/centering:
   ```css
   .odds-coupon.is-ou .odds-book-label {
     margin-bottom: 0;
     box-sizing: border-box;
     width: 100%;
     min-height: 52px;
     display: flex;
     flex-direction: column;
     align-items: center;
     justify-content: center;
     text-align: center;
     color: var(--nb-ink);
     background: var(--nb-surface);
     border: 1px solid var(--nb-accent);
     border-radius: 0;
     padding: 8px 10px;
     font-family: var(--nb-mono);
     font-size: 14px;
     font-weight: 600;
     text-transform: none;
     letter-spacing: 0;
   }
   ```

The pinned heading row (`buildOuHead`) builds its columns from the same `.odds-col`
class and shares the body's `flex: 0.7` header spacer, so FMV/FD/DK headings sit
directly over their columns. `.odds-col-head` is `text-align: center` stretched
full-width, centering each heading over its column.

## Known caveat

Heights are matched by reserving a fixed `min-height: 52px`, which covers the normal
case where the odds subtext (`O −110 / U −110`) fits on one line. On a very narrow
viewport the subtext can wrap to two lines and exceed 52px for that one badge, causing
minor row drift. A bulletproof fix would restructure the OU body as a CSS grid (rows
instead of three independent columns).

## Relevant JS (unchanged)

- `buildOuHead(showDk)` — builds the sticky FMV/FD/DK header row.
- `buildOuBody()` — builds `fmvCol`/`fdCol`/`dkCol`.
- `ouCell(labelText, oddsText)` — creates `.odds-book-label` with optional inner
  `.odds-odds` (FMV cells pass empty `oddsText` → single line; FD/DK pass odds
  subtext → taller).
