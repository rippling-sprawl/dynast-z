# Bet-screenshot parser — feasibility summary

## Idea
Auto-populate the place-bet form from a sportsbook confirmation screenshot (e.g. a FanDuel-style "Straight bet placed!" card) instead of typing every field.

## Feasibility verdict
- **Highly feasible via a vision model.** The fixed `Label: value` layout is extraction-friendly.
- **Moderately feasible via OCR + regex** (Tesseract.js / pytesseract) — brittle on the odds `-` sign and team split.
- **Pure Python/JS string parsing alone is NOT possible** — input is an image, so a pixel→text step (vision LLM or OCR) is mandatory.

## Field mapping (image → existing schema)
Schema: `views/bets/place.html`, `scripts/primary/bets.js`, `api/bets.py`.

Directly extractable:
- `stake` ← Wager `$26.00`
- `odds_american` ← Odds `-130`
- `to_win` ← To win `$20.00`
- `side` ← selection header `Over`
- `selection` ← market line `AWAY TEAM FIRST HALF OVER/UNDER 2.5 GOALS`
- `opponent` / event ← `Norway v France` (split on `v`/`vs`)

Inferred / defaulted (not literally in image):
- `league` = `Other`, `sport` = `Soccer` (not NFL/NBA)
- `event_date` = today (card shows `LIVE`)
- `status` = `pending`, `wager_status` = `unpaid`

Auto-computed by existing code (no extraction needed): `id`, `placed_at`, `odds_decimal`, `match`, `sport`.

Not representable: external `BET ID: us-nc:01kw...` — no schema field. Optional `external_bet_id` if traceability wanted.

## Recommended approach: vision LLM extraction
1. Add image upload/paste to `views/bets/place.html`.
2. Send image + JSON-schema prompt to Claude vision; strict JSON out, `null` for absent fields.
3. Prefill form fields; **user reviews before submit** (no auto-place) — absorbs extraction error and covers inferred fields.
4. Reuse existing compute (`americanToDecimal`, stake↔to_win link); extracted `to_win` is a cross-check only.

### Alternative (no LLM)
Tesseract.js (browser) or pytesseract (via `api/`) + per-row regex. Viable but brittle; all inference manual. Choose only to avoid an LLM dependency.

## Verification plan
- 5–8 varied screenshots (different books, +/- odds, ML/spread/total, parlay).
- Diff extracted JSON vs hand-labeled expected; confirm form prefill and round-trip through `api/bets.py` → Supabase.
- Ambiguous cases (team split, league, missing date) surface for review, not silent guesses.

## Open item
User may request a deep-research pass (best OCR/vision library, multi-sportsbook layout variance) before committing.
