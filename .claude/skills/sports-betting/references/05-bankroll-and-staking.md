# Bankroll & Staking

How much to bet: units, flat vs percentage staking, the Kelly criterion, and expected value (EV).

---

## 1. Units
A **unit** is a standardized bet size expressed as a **percentage of bankroll**, not a fixed dollar amount — your "personal betting currency." Tracking in units lets bettors compare performance across different bankroll sizes and removes dollar emotion.

```
unit_size ($) = bankroll × unit_percentage
```
- Common range **1–5%**; **1–2% recommended for conservative bettors**; pros often stay near **1%**.
- Examples: $1,000 × 1% = $10 unit; $10,000 × 1% = $100 unit.

**Why track in units:** standardization/comparability, removes ego, ties directly to bankroll health. *"Winning $150 on $10 bets (15 units) is far better than winning $150 on $100 bets (1.5 units)"* — units expose this; dollars hide it.

---

## 2. Flat betting
Bet the **same amount (e.g. 1 unit) on every play**, regardless of confidence. Smooths variance, prevents overconfidence, recommended for beginners. Downside: doesn't auto-respond to bankroll changes (you re-set the unit manually as the bankroll moves). A common flat range is 1–5% per play; 3% is a frequently cited medium.

## 3. Percentage / proportional betting
Stake a **fixed % of the CURRENT bankroll each time**, so the dollar stake grows after wins and shrinks after losses (recompute before each bet).
```
stake ($) = current_bankroll × fixed_percentage
```
Auto-scales down through losing streaks (downside protection) and up through winning runs; swings feel larger than flat. OddsJam caps practical proportional staking at ~10% of available funds.

## 4. Confidence-based unit staking
Vary units by conviction, e.g. **1u = small lean, 2–3u = regular play, 4–5u = big play**. Props/SGPs often 0.5u. **Cap single-bet exposure** (e.g. 3–5 units max) — *"betting 10 units because you're extra confident, when you usually bet 1, is a good way to go broke."*

---

## 5. Kelly criterion
The bet fraction that maximizes long-term **logarithmic (geometric) growth** of bankroll.

```
f* = (b·p - q) / b          # equivalently  f* = p - q/b
```
- `f*` = fraction of current bankroll to wager
- `b`  = net decimal odds = **decimal odds − 1** (profit per unit on a win)
- `p`  = your true win probability
- `q`  = 1 − p

**Worked A — even money (decimal 2.00, b=1), p=0.55:**
```
f* = (1×0.55 - 0.45) / 1 = 0.10  -> bet 10% of bankroll
```
**Worked B — `+150` (decimal 2.50, b=1.5), p=0.45:**
```
f* = (1.5×0.45 - 0.55) / 1.5 = 0.125/1.5 = 0.0833  -> bet ~8.33%
```

**No-bet rule:** if `f* ≤ 0` (your edge `b < q/p`), **don't bet** — the wager is not +EV.

### Fractional Kelly
Most practitioners bet **half or quarter Kelly** (multiply `f*` by 0.5 or 0.25) to cut volatility and the risk of ruin, and to hedge against **error in your probability estimate** (overestimating edge → overbetting). Full Kelly is famously swingy. Half-Kelly of the examples: 5% and ~4.17%.

> Kelly tells you **how much** to bet **once a bet is +EV**; EV (below) tells you **whether** it's +EV.

---

## 6. Expected value (EV)
The average profit/loss per bet over the long run.

```
EV = P_win × profit_if_win  -  P_loss × stake
   = P_win × (payout - stake)  -  (1 - P_win) × stake
```

**Worked — $100 at `+120`, true win prob 50%:**
```
EV = (0.50 × $120) - (0.50 × $100) = $60 - $50 = +$10   (+10% of stake)
```
**Worked — $20 at `+150`, your prob 45% (implied 40%):**
```
EV = (0.45 × $30) - (0.55 × $20) = $13.50 - $11.00 = +$2.50   (+12.5%)
```
Break-even: 40% win prob, $150 profit, $100 stake → `0.40×150 - 0.60×100 = $0`.

**+EV when your true win probability exceeds the price's implied probability.** Over many bets, realized results converge toward EV even though individual bets vary. −EV (true prob below implied) bleeds money long-term.

---

## Quick reference
- 1 unit ≈ 1% of bankroll; conservative 1–2%, pros ~1%.
- Flat = same size every play (variance control). Percentage = % of current bankroll (auto-scaling).
- Bet only +EV (true prob > implied prob). Size with **fractional Kelly** (`f* = (bp−q)/b`, then × 0.25–0.5).
- Cap single-bet exposure; never chase.

---

## Sources
- Wikipedia — [Kelly criterion](https://en.wikipedia.org/wiki/Kelly_criterion) · Corporate Finance Institute — [Kelly Criterion](https://corporatefinanceinstitute.com/resources/data-science/kelly-criterion/)
- Boyd's Bets — [Unit](https://www.boydsbets.com/unit-in-sports-betting/), [Expected Value](https://www.boydsbets.com/expected-value-in-sports-betting/)
- Action Network — [Units](https://www.actionnetwork.com/education/units), [Bankroll Management](https://www.actionnetwork.com/how-to-bet-on-sports/general/sports-betting-tips-bankroll-management), [+EV Betting](https://www.actionnetwork.com/education/ev-betting)
- OddsJam — [Bankroll Management](https://oddsjam.com/betting-education/bankroll-management) · The Spread — [Units & Staking](https://www.thespread.com/betting-guides/betting-units-staking-plans/) · The Sports Geek — [What Is a Unit](https://www.thesportsgeek.com/sports-betting/what-is-a-unit/)
