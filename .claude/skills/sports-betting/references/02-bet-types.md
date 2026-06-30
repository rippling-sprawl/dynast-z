# Bet Types

The five core bet types plus live betting. Each section: how it works, notation, a worked example, and explicit win/loss/push settlement. All examples use American odds (see [01-odds-and-probability.md](01-odds-and-probability.md) for the payout formulas).

Quick payout reminder: favorite (`-A`) profit = `stake × (100/|A|)`; underdog (`+A`) profit = `stake × (A/100)`; total return = stake + profit.

---

## 1. Moneyline
Pick **who wins straight up**, no margin of victory. Favorite gets negative odds, underdog positive.

```
Indiana  -325   (favorite)
Miami    +260   (underdog)
```
- $100 on Miami `+260`: win → +$260 (return $360); loss → −$100.
- $100 on Indiana `-325`: win → +$30.77 (return $130.77); loss → −$100.

**Settlement:** Win = your team wins. Loss = your team loses. **Push** is rare — only if the game ends tied and no draw option was offered (stakes refunded). In a **3-way** market (soccer Home/Draw/Away), a tie is a **loss** for a team bet, not a push.

---

## 2. Point spread
A handicap that levels the teams; you bet the **margin of victory**.
- Favorite **gives** points → shown `-6.5`; must win by **more than** that.
- Underdog **gets** points → shown `+6.5`; covers by winning outright **or** losing by fewer.

```
Chiefs    -6.5   -110
Broncos   +6.5   -110
```
"Covering" = beating the handicap (add the spread to the team's score, compare).

- Chiefs win 27–17 (by 10) → Chiefs `-6.5` cover ✓.
- Chiefs win 24–20 (by 4) → Broncos `+6.5` cover ✓.
- Broncos win outright → Broncos `+6.5` cover ✓.

**Push (whole numbers only):** Chiefs `-7`, win by exactly 7 → **push**, stakes refunded. The **"hook"** (the `.5`, e.g. `-6.5`) exists to eliminate pushes. Bettors pay extra juice to move a line, especially around football's **key numbers 3 and 7** (most common margins).

**ATS** ("against the spread") = a team's cover record, e.g. `4-2-1` = 4 covers, 2 non-covers, 1 push. Standard pricing is `-110/-110` (that's the vig).

**Settlement:** Win = your side covers. Loss = fails to cover. Push = margin lands exactly on a whole-number spread (impossible on a half-point).

---

## 3. Totals (Over / Under)
Bet whether the **combined final score** is over or under the book's number (the "total," "O/U").

```
Total 47.5   Over -110 / Under -110
```
- Combine 48+ → Over wins. 47 or fewer → Under wins.
- **Push (whole numbers):** total `216`, final `116–100 = 216` → push, refunded. Half-point totals can't push.

Totals also apply to halves/quarters and to individual stats. Real example: Super Bowl XXXIX total was 46.0; actual combined 45 → Under.

**Settlement:** Win/Loss on the correct side; Push when combined score equals a whole-number total exactly.

---

## 4. Props (proposition bets)
Any wager **not tied to the final outcome/score** — the book "proposes" a scenario, you bet over/under or yes/no.

- **Player props:** an individual's stat line, usually O/U — e.g. *Mahomes Over/Under 285.5 passing yards*; or yes/no like *anytime TD scorer*.
- **Team props:** one team's output independent of who wins — e.g. team total points in Q1.
- **Game props:** broader events — overtime yes/no, first-score method, coin toss.
- **Alternate lines:** same market at a different number with adjusted odds. Standard *Over 275.5 (-110)* might have alternates *Over 300.5 (+180)* (harder, bigger payout) or *Over 250.5 (-200)* (easier, smaller).

Common by sport: NFL passing/rushing/receiving yards, anytime TD; NBA points/rebounds/assists (and PRA combos); MLB pitcher strikeouts, batter HR; NHL goal scorer, shots on goal, saves.

Worked: $50 on *Mahomes Over 285.5 (-110)* → 291 yards = Over wins, +$45.45.

**Settlement:** graded once the game ends against the final stat line. **Push** on whole-number lines landing exactly. **Void/no-action** if the player **doesn't play at all** (stake refunded); if he plays but exits injured, props are typically graded on the final stat **as-is**. *(Void rules vary by book — flag this.)*

---

## 5. Futures
Bets on outcomes decided later — championship, MVP, season win totals, division winners.

- Listed favorite-to-longshot: *Ravens +650* ($100 → $650 profit), *Saints +40000* ($100 → $40,000).
- **Large payouts** because there are many possible outcomes.
- **Locked-in odds:** you keep the price at bet time even as the market moves all season.
- **Settles only when the event/season concludes** — your capital is **tied up** for weeks/months.

Worked: $100 on *Ravens +650* pre-season → if they win the title, +$650 (paid after the Super Bowl) even if their in-season price had dropped to +300.

**Settlement:** Win if the backed outcome occurs; Loss otherwise (settled when eliminated/at season end). Win-total futures can **push** on an exact whole-number line.

---

## 6. Live / in-play betting (brief)
Betting a game already underway. Spreads, totals, and moneylines are recalculated continuously as scores, momentum, injuries, and pace change — often during stoppages, sometimes 2,000+ line changes a game. Example: in the 2018–19 AFC Championship, KC opened a 3-point favorite but swung to `+6.5` live after falling behind by two scores. Useful for entering late or buying improved prices on a comeback.

---

## Settlement cheat-sheet

| Bet type | Wins when… | Push possible? |
|---|---|---|
| Moneyline | Your team wins outright | Only on an un-offered tie (rare); never in 3-way |
| Point spread | Your side covers the handicap | **Yes** — exact whole-number margin |
| Totals (O/U) | Combined score on the right side | **Yes** — exact whole-number total |
| Props | Stat clears the line / yes-no hits | Yes on whole numbers; **void/refund** if player doesn't play |
| Futures | Backed long-term outcome occurs | Rare (exact win-total); stake tied up until resolution |

A **push refunds your stake** — neither win nor loss — recorded as the third result (e.g. `4-2-1`).

---

## Sources
- FanDuel — [What Is a Moneyline Bet?](https://www.fanduel.com/sports-betting-guide/what-is-a-moneyline-bet)
- FOX Sports — [What Is the Point Spread?](https://www.foxsports.com/stories/betting/what-is-point-spread)
- Action Network — [Push](https://www.actionnetwork.com/education/push), [Live Betting](https://www.actionnetwork.com/education/live-betting-sports-tips)
- Wikipedia — [Over–under](https://en.wikipedia.org/wiki/Over%E2%80%93under)
- Covers — [How to Bet Futures](https://www.covers.com/guides/how-to-bet-futures)
- Hard Rock Bet — [What Is a Prop Bet?](https://www.hardrock.bet/sportsbook/prop-bet/)

*Caveats that genuinely vary by book: (a) prop void/no-action rules on a scratch or mid-game injury; (b) whether a market uses a whole-number (push-eligible) or half-point line.*
