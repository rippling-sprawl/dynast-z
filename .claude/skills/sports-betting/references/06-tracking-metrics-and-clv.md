# Tracking Metrics & CLV

The performance metrics a tracker should compute, with exact formulas, plus **closing line value** — the single best leading indicator of betting skill.

---

## 1. Profit / Loss (P/L)
```
Net P/L = total_returns - total_staked = Σ(per-bet P/L)
per-bet: win -> stake × (decimal - 1) ;  loss -> -stake ;  push/void -> 0
```
Worked: 3 × $100 at `+150`, results W/L/W → `+150 - 100 + 150 = +$200`.

## 2. Total wagered / handle / turnover
Sum of all stakes, win or lose. **Turnover** (bettor's view) = **handle** (book's view). *Not* the same as deposits or revenue (books hold just under ~5% of handle).
```
total_wagered = Σ stakes
```
10 × $50 + 5 × $200 = **$1,500**.

## 3. ROI / Yield
```
ROI = Yield = net_profit / total_staked × 100
```
Worked: +$500 on $10,000 wagered → **5%**. +$200 on $5,000 → **4% yield**.

> **Denominator caveat:** some sources define ROI on **starting bankroll** and yield on **turnover**, which diverge (e.g. $2,760 profit, $36,500 wagered, $10,000 deposit → yield 7.56% but bankroll-ROI 27.6%). **Pick one convention and label it.** When ROI is computed on turnover, ROI = yield. Benchmarks: long-term **3–7% is good**, >10% sustained is exceptional; **yield >5% over 1,000+ bets is excellent**.

## 4. Win rate / hit rate
```
Win % = wins / (wins + losses) × 100      # pushes EXCLUDED by default
```
Worked: `8-4` → 8/12 = **66.7%**. (Some ATS trackers instead count a push as half a win — be explicit.) Win% alone isn't profitability — a sub-50% rate still profits at plus odds, so track **average odds** alongside it.

## 5. Break-even win %
The minimum win rate to profit at a given price (the price's implied probability).
```
favorite (-A):  |A| / (|A| + 100)
underdog (+A):  100 / (A + 100)
```
| Odds | Break-even |
|---|---|
| -110 | **52.38%** |
| -150 | 60.0% |
| +100 | 50.0% |
| +150 | 40.0% |

`-110` derivation: risk $110 to return $210 → `110/210 = 52.38%`. Going 5-5 at `-110` on $100 bets **loses $50** — proof that 50% isn't break-even.

## 6. Units won/lost
Bankroll-independent P/L.
```
units_won = net_profit / unit_size
stake_in_units = stake / unit_size
```
A `-110` win returns **0.91 units** per unit risked (the vig "tax"); if 1u = $20 that's ~$18.18. Store `unit_size` so both dollar and unit views are derivable.

## 7. Other standard fields
- **Average odds** = `Σ odds / n` (or stake-weighted) — context for win% vs break-even.
- **Average stake** = `total_wagered / n` — stake discipline / chasing signal.
- **Longest win/loss streak** — variance/risk indicator.

---

## 8. Closing Line Value (CLV) — the key edge indicator
**CLV = the difference between the odds/line you bet and the closing line** (the final price just before kickoff). The closing line is the sharpest, most efficient price the market produces, so consistently beating it is the **leading indicator of long-term edge — independent of whether the bet won.** It reveals edge far faster than P/L: ~5% consistent CLV can show significance in ~50 bets vs thousands needed to prove profit from results alone.

### Compute it

**Line points (spreads/totals):**
```
clv_points = your_line - closing_line     # took +5, closed +3 -> +2 (you beat it)
```
**Moneyline (cents):** difference in American price (got +150, closed +130 → 20 cents better).

**As a percentage / probability:**
```
implied_prob = 1 / decimal_odds
clv_pct      = (your_decimal / closing_decimal - 1) × 100      # positive = you beat the close
clv_prob_pts = (closing_implied_prob - your_implied_prob) × 100
```

**Worked:**
```
You bet +110 -> decimal 2.10 -> implied 47.62%
Closes  -110 -> decimal 1.909 -> implied 52.38%
clv_pct = (2.10 / 1.909 - 1) × 100 ≈ +10.0%
clv_prob_pts = 52.38% - 47.62% ≈ +4.76 points
```

### Two cautions (bake into the app)
1. **Sign convention:** Pinnacle writes `closing/bet − 1` (negative when you beat the close); the form above (`bet/closing − 1`) is positive when you beat the close. **Choose one app-wide** so "positive = good."
2. **De-vig the closing line first.** The closing price contains the book's margin and **overstates** true probability. De-vig against the other side before computing CLV%:
   ```
   fair_prob_A = implied_prob_A / (implied_prob_A + implied_prob_B)
   ```
   Real example: ignoring vig showed ~4% CLV that shrank to **<1%** after de-vigging. Store the **opponent's closing odds** to enable this.

**Positive CLV** = you locked a better price than the close (bought low). **Negative CLV** = the market moved against your price.

---

## Implementation checklist
- Net P/L = Σ per-bet P/L (win: `stake×(D−1)`, loss: `−stake`, push/void: `0`).
- ROI/yield = net_profit ÷ total_staked (label the denominator).
- Win% excludes pushes: wins ÷ (wins+losses).
- Break-even% = `|A|/(|A|+100)` (fav) or `100/(A+100)` (dog).
- Units = profit ÷ unit_size; persist `unit_size`.
- CLV: store both your odds and closing odds (+ opponent close to de-vig); fix one sign convention.

---

## Sources
- Action Network — [Units](https://www.actionnetwork.com/education/units), [Glossary](https://www.actionnetwork.com/education/sports-betting-terms-glossary), [Push](https://www.actionnetwork.com/education/push)
- The Betting Institute — [Calculate ROI/Yield/Win%](https://www.bettinginstitute.co.uk/how-to-bet/calculate-roi-yield-winning-percentage/) · Underdog Chance — [ROI vs Yield](https://www.underdogchance.com/difference-roi-yield-betting/) · BettingPros — [Break-Even Win %](https://www.bettingpros.com/articles/break-even-win-for-sports-betting/) · Boyd's Bets — [Break-Even](https://www.boydsbets.com/percentage-bets-break-even/)
- CLV: Boyd's Bets — [Closing Line Value](https://www.boydsbets.com/closing-line-value/), Sharp Football — [CLV Betting](https://www.sharpfootballanalysis.com/sportsbook/clv-betting/), Pinnacle Odds Dropper — [CLV](https://www.pinnacleoddsdropper.com/blog/closing-line-value), Unabated — [Getting Precise About CLV](https://unabated.com/articles/getting-precise-about-closing-line-value)
