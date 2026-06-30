---
name: sports-betting
description: >-
  In-depth reference for sports betting domain knowledge — odds formats and
  conversions, implied probability, vig/hold, bet types (moneyline, spread,
  totals, props, futures), parlays/teasers/round robins, wager settlement
  (win/loss/push/void/half-win/cash out), bankroll & staking (units, Kelly),
  performance metrics (ROI, yield, win%, CLV, EV), and a per-bet data schema.
  Use this whenever building, designing, or reasoning about a sports betting
  tracker, wager log, odds calculator, or any feature that records, grades, or
  analyzes bets and winnings.
---

# Sports Betting

A complete, multi-source-verified knowledge base for sports betting concepts. Built to support a **wager & winnings tracker**: every concept needed to record a bet, grade its result, and measure performance is defined here with plain-text formulas and worked numeric examples.

## How to use this skill

Load the reference file that matches the task. Each file is self-contained with formulas, worked examples, and sources.

| # | Reference | Covers |
|---|-----------|--------|
| 1 | [references/01-odds-and-probability.md](references/01-odds-and-probability.md) | American / decimal / fractional odds, all conversions, implied probability, vig / juice / hold, de-vigging, line movement |
| 2 | [references/02-bet-types.md](references/02-bet-types.md) | Moneyline, point spread, totals (O/U), props, futures, live betting — with settlement rules |
| 3 | [references/03-parlays-and-combos.md](references/03-parlays-and-combos.md) | Parlays + payout math, leg push/void handling, same-game parlays, teasers, round robins, pleasers, payout tables |
| 4 | [references/04-settlement-and-grading.md](references/04-settlement-and-grading.md) | Win / loss / push / void / half-win / half-loss / cash out; stake, to-win, payout definitions |
| 5 | [references/05-bankroll-and-staking.md](references/05-bankroll-and-staking.md) | Units, flat vs percentage betting, Kelly criterion, fractional Kelly, expected value (EV) |
| 6 | [references/06-tracking-metrics-and-clv.md](references/06-tracking-metrics-and-clv.md) | Profit/loss, handle/turnover, ROI, yield, win%, break-even%, units won/lost, closing line value (CLV) |
| 7 | [references/07-tracker-data-schema.md](references/07-tracker-data-schema.md) | Proposed per-bet data model for the tracker, plus all derived/computed fields |
| 8 | [references/08-glossary.md](references/08-glossary.md) | Quick A–Z glossary of terms |

Visual quick-references live in [assets/](assets/):
`odds-conversion-cheatsheet.png` · `implied-probability-curve.png` · `parlay-payout-growth.png` · `settlement-outcomes.png`

## The 60-second mental model

- **Odds encode two things**: the payout *and* the market's implied probability of the outcome. Three notations exist for the same price — **American** (`-110`, `+150`), **decimal** (`1.91`, `2.50`), **fractional** (`10/11`, `3/2`). Decimal is the math-friendly one because payout = `stake × decimal`.
- **The book always builds in a margin** (the *vig* / *juice* / *hold*). That's why a coin-flip market is priced `-110/-110`, not `+100/+100`, and why the two sides' implied probabilities sum to **more than 100%**.
- **You profit long-term only if you win more often than your price's break-even rate.** At `-110` that's **52.38%**, not 50%.
- **A bet settles** as win, loss, **push** (tie → stake refunded), void (cancelled → refunded), or — on Asian quarter-lines — half-win/half-loss. Cash out lets you settle early for a book-discounted amount.
- **Parlays multiply**: combined decimal odds = product of each leg's decimal odds; all legs must win. Bigger payout, lower hit rate, compounding house edge.
- **Track in units, not just dollars.** 1 unit ≈ 1% of bankroll. Judge skill by **ROI / yield** and especially **closing line value (CLV)** — the sharpest leading indicator of edge.

## Core formulas (cheat sheet)

```
# Odds  ↔  implied probability
P(- odds) = |A| / (|A| + 100)          # e.g. -150 -> 60.0%
P(+ odds) = 100 / (A + 100)            # e.g. +150 -> 40.0%
P(decimal) = 1 / D                     # e.g. 2.50 -> 40.0%

# American  ->  decimal
D = (A/100) + 1     if A > 0           # +150 -> 2.50
D = (100/|A|) + 1   if A < 0           # -110 -> 1.909

# Payout
profit  = stake × (D - 1)             # decimal form (cleanest)
payout  = stake × D = stake + profit
profit(+A) = stake × (A/100)          # +150 on $100 -> $150
profit(-A) = stake × (100/|A|)        # -110 on $100 -> $90.91

# Vig / fair probability (two-way market)
overround   = P_a + P_b - 1
fair P_a    = P_a / (P_a + P_b)        # normalize out the juice

# Parlay
parlay_decimal = D1 × D2 × ... × Dn
parlay_profit  = stake × (parlay_decimal - 1)

# Performance
break-even %   = |A|/(|A|+100)  (fav)  |  100/(A+100)  (dog)   # -110 -> 52.38%
ROI / yield    = net_profit / total_staked
units_won      = net_profit / unit_size
EV             = P_win × profit_if_win  -  P_loss × stake
Kelly  f*      = (b·p - q) / b          # b = decimal-1, q = 1-p; bet a fraction of f*
```

## Conventions to fix app-wide (so data stays consistent)

1. **Store odds in one canonical format** (decimal recommended for math; keep the American display value too). All conversions are lossless.
2. **Pick one CLV sign convention** so "positive = you beat the close," and **de-vig the closing line** before computing CLV% (raw vigged closing odds overstate CLV).
3. **Win% excludes pushes** by default: `wins / (wins + losses)`.
4. **ROI and yield both divide net profit by total staked** (turnover) — they coincide under that convention. If you also show "bankroll ROI" (÷ starting bankroll), label it distinctly.
5. **Model parlays as a header row + one row per leg** (`parlay_id`, `leg_index`) so per-leg grading and CLV still work.
6. **Two settlement facts vary by sportsbook** — flag them in the UI: (a) prop void/no-action rules when a player is scratched or exits injured, and (b) whether a market uses a whole-number (push-eligible) or half-point line.

> All figures here were cross-checked across multiple authoritative sources (Action Network, DraftKings, FanDuel, Wikipedia, Boyd's Bets, Pinnacle, Unabated, BettingPros, Covers, FOX Sports, and others). Per-topic source lists are at the bottom of each reference file. Sportsbook house rules differ on edge cases; treat the standard rules here as defaults and defer to a given book's posted rules for grading disputes.
