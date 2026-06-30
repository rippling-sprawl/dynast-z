# Tracker Data Schema

A clean, normalized per-bet data model for the wager & winnings tracker, plus the fields you **derive** rather than store. Based on what real trackers (Action Network, Sportsbook Scout, Boyd's Bets, aussportsbetting) record.

---

## Stored fields (one row per bet; parlays = header + leg rows)

| Column | Type | Description | Example |
|---|---|---|---|
| `bet_id` | string (PK) | Unique id | `b_8f3a1c` |
| `placed_at` | timestamp | When the wager was placed (for line-movement context) | `2026-06-30T18:42:00Z` |
| `event_date` | timestamp | Scheduled event start | `2026-07-01T23:10:00Z` |
| `sport` | enum/string | Sport | `Baseball` |
| `league` | enum/string | League/competition | `MLB` |
| `event` | string | Match / teams | `Yankees @ Red Sox` |
| `home_team` | string | Home team (normalized) | `Red Sox` |
| `away_team` | string | Away team (normalized) | `Yankees` |
| `bet_type` | enum | `moneyline / spread / total / prop / future / parlay / teaser / round_robin` | `spread` |
| `selection` | string | The pick | `Yankees -1.5` |
| `line` | decimal (nullable) | Handicap/total points (null for ML/most props) | `-1.5` |
| `odds_decimal` | decimal | **Canonical** price at placement | `2.10` |
| `odds_american` | integer | American rendering (display) | `+110` |
| `odds_format_entered` | enum | Format the user entered (`american/decimal/fractional`) | `american` |
| `stake` | decimal | Amount risked | `50.00` |
| `to_win` | decimal | Profit if win (`stake × (odds_decimal-1)`) | `55.00` |
| `potential_payout` | decimal | `stake + to_win` | `105.00` |
| `unit_size` | decimal | Dollar value of 1 unit at placement | `50.00` |
| `sportsbook` | enum/string | Book where placed | `DraftKings` |
| `status` | enum | `pending / win / loss / push / void / half_win / half_loss / cashout` | `pending` |
| `settled_at` | timestamp (nullable) | When graded | `null` |
| `profit_loss` | decimal (nullable) | Net P/L once settled (see grading rules) | `null` |
| `cashout_amount` | decimal (nullable) | Amount received if cashed out | `null` |
| `closing_line` | decimal (nullable) | Closing handicap/total (spread/total CLV) | `-2.0` |
| `closing_odds_decimal` | decimal (nullable) | Closing price (odds/ML CLV) | `1.909` |
| `closing_odds_opponent` | decimal (nullable) | Other side's closing odds — needed to **de-vig** CLV | `2.00` |
| `parlay_id` | string (nullable, FK→self) | Groups legs of one parlay | `p_22b9` |
| `leg_index` | integer (nullable) | Order of this leg within a parlay | `2` |
| `tags` | string[] | Strategy labels | `["model","fade-public"]` |
| `notes` | text | Free-form | `bet early line` |

**Parlay modeling:** the parlay is a **header row** (`bet_type=parlay`, holds combined stake/odds/payout) and each leg is its own row linked by `parlay_id` + `leg_index` (leg rows carry their own odds/line/closing odds so per-leg grading and CLV still work). When a leg pushes/voids, drop it and re-price the header from the surviving legs (see [03-parlays-and-combos.md](03-parlays-and-combos.md)).

---

## Derived / computed fields (don't store; compute from the above)

| Field | Formula |
|---|---|
| `implied_prob` | `1 / odds_decimal` |
| `units_staked` | `stake / unit_size` |
| `units_won` | `profit_loss / unit_size` |
| `clv_points` | `line - closing_line` (sign per your convention) |
| `clv_pct` | `(odds_decimal / closing_odds_decimal - 1) × 100`, de-vigged via `closing_odds_opponent` |
| `break_even_pct` | `1 / odds_decimal` (= implied prob) |

## Grading rules → `profit_loss`

| `status` | `profit_loss` |
|---|---|
| `win` | `+ to_win` |
| `loss` | `- stake` |
| `push` | `0` |
| `void` | `0` |
| `half_win` | `+ to_win / 2` |
| `half_loss` | `- stake / 2` |
| `cashout` | `cashout_amount - stake` |

## Portfolio-level rollups
`total_staked = Σ stake` · `net_profit = Σ profit_loss` · `roi = net_profit / total_staked` · `win_pct = wins / (wins + losses)` (exclude pushes/voids) · `units_net = net_profit / unit_size` · `avg_clv_pct = mean(clv_pct)`. Also useful: P/L grouped by `sport`, `bet_type`, `sportsbook`, and `tag`; equity curve over `settled_at`; longest win/loss streak.

> See [06-tracking-metrics-and-clv.md](06-tracking-metrics-and-clv.md) for the metric definitions and [04-settlement-and-grading.md](04-settlement-and-grading.md) for the grading logic.

---

## Sources
- Action Network — [Track Your Bets](https://actionnetworkhq.zendesk.com/hc/en-us/articles/360022118011-How-to-track-your-bets), [BetSync](https://www.actionnetwork.com/betsync)
- Sportsbook Scout — [Bet Tracking](https://www.sportsbookscout.com/tools/sports-bet-tracking) · Boyd's Bets — [Tracking Sports Bets](https://www.boydsbets.com/tracking-sports-bets/) · Aus Sports Betting — [Betting Tracker](https://www.aussportsbetting.com/tools/betting-tracker-excel-worksheet/)
