# Projecting an NFL Player's Stat Line vs a Specific Opponent (recent form + career H2H + defense-allowed)

Scope note: the public evidence base is thin and mostly practitioner writing (fantasy sites), not peer-reviewed work. Several numbers below come from older studies (2011-2015). Formulas marked as inferences are standard statistics and are not taken from a cited source. The project's own `.claude/skills/sports-betting/` notes cover odds, implied probability, vig and EV, not projection methods. Use them to convert an over/under probability into implied odds and EV once you have the probability.

## Q1. How predictive is each input (recent form, season or multi-season baseline, H2H, DvP)?

### Takeaway
Volume and usage (target share, routes, carries) is the most stable signal. Season-to-date per-game production overtakes the prior season within a few weeks. Raw defense-vs-position (DvP) numbers persist only weakly (year-to-year r of about 0.16-0.26) and explain little week to week. Career head-to-head history has no published evidence of predictive value and should be treated as noise or flavor.

### Cited Findings
- **Season-to-date vs prior season:** using 2010-2014 PPR data, current-season production became more predictive than prior-season production after a few weeks and stayed that way for the rest of the season. Kickers and DSTs were the hardest to predict, being the most matchup-dependent. — [Harvard Sports Analysis Collective, 2015](https://harvardsportsanalysis.org/2015/10/is-it-time-to-give-up-on-insert-underperforming-fantasy-player-here/) (page returned HTTP 500 when fetched; finding taken from the search snippet)
- **Early-season averages:** a player's average through Week 5 explained 82% of the variation in his final-season average. A model built on the previous season reached a predicted R² of 58%. — [Minitab blog, 2011](https://blog.minitab.com/en/the-statistics-game/how-well-did-minitab-predict-fantasy-football-player-performance-part-1)
- **Minitab follow-up:** the predictions explained 86.7% of the variation in final averages. The author put the remainder down to injuries, trades and random variation. — [Minitab part 2](https://blog.minitab.com/en/blog/the-statistics-game/how-well-did-minitab-predict-fantasy-football-player-performance-part-2-v1) (caveat: predicting the season average from part of that same season is partly autocorrelated, so this overstates true out-of-sample next-game accuracy)
- **Per-game rates are the most stable:** per-game metrics carry the most year-over-year signal for WRs, with fantasy points per game the most stable WR stat in Sharp's 2024 study. Targets are the core volume driver and TDs are among the least stable. — [Sharp Football Analysis, WR stats that matter 2024](https://www.sharpfootballanalysis.com/fantasy/wide-receiver-stats-that-matter-fantasy-football-2024/)
- **Year-over-year stickiness since 2021** (players with 100+ key snaps in consecutive seasons):
  - Target share is about 0.70, the stickiest metric in the study.
  - YPRR is above 0.60 (100+ routes).
  - QB EPA/dropback is about 0.60.
  - RB EPA/rush is "virtually negligible," and rushing stats overall are among the least sticky.
  - Source: [SumerSports, Sticky football stats](https://sumersports.com/the-zone/sticky-football-stats-predictive-nfl-metrics/)
- **Targets per route run vs YPRR:** targets per route run (TPRR) is more consistent year to year than YPRR or yards per target (WRs with 40+ targets in consecutive seasons, 2007-2012). — [Football Perspective](https://www.footballperspective.com/yards-per-route-run-yards-per-target-and-targets-per-route-run/)
- **Yards per carry:** YPC is inconsistent both across years and within a season (1,512 RBs, 1990-2013, split by odd and even games). — [Football Perspective, thoughts on YPC](https://www.footballperspective.com/thoughts-on-running-back-yards-per-carry/); see also [Footballguys, Regression Alert: Be Very Wary of Yards per Carry](https://www.footballguys.com/article/HarstadRegression02)
- **DvP year-to-year correlation** (half-PPR fantasy points allowed, 2014-2024):

  | Position | Year-to-year r | Top-5 defenses repeating | Bottom-5 defenses repeating | Notes |
  |---|---|---|---|---|
  | QB | 0.26 | 30% | 20% | Highest correlation |
  | RB | 0.23 | 20% | ~32% | Bottom-5 wording in the article is ambiguous |
  | WR | not given | 24% | 24% | Described as "very little" correlation |
  | TE | 0.16 | 22% | 16% | Lowest correlation |

  The author also notes that real defensive quality does not reliably carry over to fantasy points allowed. — [4for4, Do Defenses Repeat Fantasy Football Performances? (2025)](https://www.4for4.com/2025/preseason/do-defenses-repeat-fantasy-football-performances)
- **Defense adjustment for next-week rushing** (R² for next week's production):

  | Metric | Offense rolling 1-year average only | With defense adjustment |
  |---|---|---|
  | Rushing yards | 0.05 | 0.08 |
  | Rushing TDs | 0.02 | 0.03 |
  | Rushing fantasy points | 0.04 | 0.07 |

  The defense adjustment helps, but both the offense and defense signals are weak against single-game noise. — [Scott Spratt, PFF, "Run Offenses vs. Run Defenses" (2014)](https://www.pff.com/run-offenses-vs-run-defenses/)
- **DvP sample windows:** one provider's DvP uses the defense's last 8 games. Another notes DvP trends become more reliable as the season goes on. Raw DvP is skewed by the opponents faced; for example, facing Andrews and Kelce in Weeks 1-3 makes a defense look worse against TEs than it is. — [Establish The Run DvP](https://establishtherun.com/establish-the-run-nfl-dvp/); [RotoGrinders Matchup-Adjusted DvP legend](https://rotogrinders.com/pages/matchup-adjusted-dvp-legend-894142)
- **Head-to-head history:** Stathead's Versus Finder gives player-vs-team game logs, and its launch post suggests checking a QB's history against his upcoming opponent. It offers no evidence that this history predicts anything. — [Sports Reference blog, Versus Finder launch (2023)](https://www.sports-reference.com/blog/2023/06/versus-finder-launches-on-stathead-football/)

### Inferences
- The baseline should come mostly from season-to-date volume (targets, carries, attempts) times shrunk efficiency. A recent-games window (last 3-5 games) is useful mainly for detecting role changes, not for "hot hand" efficiency.
- **Suggested starting weights (my inference, to be tuned by backtest):**
  - About 85-95% of the projection comes from the player baseline: season-to-date blended with prior season or career early in the year.
  - The defense matchup is a modest multiplicative adjustment, shrunk heavily toward 1.0.
  - H2H gets 0-5% weight, or is shown only for context.
  - These weights follow from the evidence that the R² gain from defense is small and that DvP persists only weakly.
- **H2H in practice:** a player usually has 1-2 games per year against a division rival and 0-1 against anyone else. Career H2H samples of 2-8 games, spread across different seasons, rosters, coordinators and the player's own role, are far below any stabilization threshold. That makes H2H the weakest of the three inputs. Its best use in a UI is as context dots beside the player's overall distribution, not as a driver of the projection.
- DvP is most usable for QBs and RBs and least usable for TEs and WRs, and it improves later in the season as samples grow.

### Gaps
- I found no published study that directly tests player-vs-specific-opponent history in the NFL (an NFL equivalent of baseball's batter-vs-pitcher work). The claim that it is noise rests on sample-size reasoning, not a cited test.
- I found no study that directly compares a last-3 or last-5 window against the season-to-date average for next-game prediction.
- The 4for4 WR correlation coefficient was not reported. The RB bottom-5 repeat rate wording was ambiguous.

## Q2. How do practitioners adjust opponent-allowed stats for strength of schedule?

### Takeaway
Compare what each offense scored against this defense with what that same offense normally scores against everyone else, then average those over- or under-performances. The result is expressed either as a difference (points above average) or a ratio (percent above or below average). Commercial versions (4for4 aFPA, FTN DVOA-adjusted FPA, RotoGrinders matchup-adjusted DvP) all follow this idea.

### Cited Findings
- **PFF difference method (Garth Bryden, 2015):**
  1. Compute each team's weekly fantasy points for and against in pass and rush.
  2. Average the matching figures of the opponents a team has faced.
  3. Take team FPA minus the average of those opponents' figures, which gives over- or under-performance.
  4. Apply that difference to the next opponent's average. Worked example: Arizona pass offense 31.68 vs opponent pass-defense average 32.11 gives -0.43. Applied to San Francisco's 32.95, that projects 32.51.

  No predictive test was reported. — [PFF, Strength of Opposition and Fantasy Points Allowed](https://www.pff.com/news/strength-of-opposition-and-fantasy-points-allowed)
- **4for4:** "schedule bias has been removed" from its adjusted FPA tables, giving an "apples-to-apples" comparison, with defenses ranked 1-5 marked very strong and 28-32 very weak. The exact math is not public. — [4for4 Hot Spots, schedule-adjusted fantasy points](https://www.4for4.com/recent-report/hot_spots_ff_points_adjusted)
- **FTN:** its DVOA-based fantasy points against is expressed as a percentage above or below average and uses DVOA and DYAR "to maximize the predictive value." — [FTN DvP](https://ftnfantasy.com/?p=111337)
- **Raw totals mislead:** raw fantasy points allowed "don't show you whether a particular team has had an easy or hard schedule." — [PFF, Strength of Opposition](https://www.pff.com/news/strength-of-opposition-and-fantasy-points-allowed)

### Inferences
**Ratio method that runs on box-score logs (inference; standard approach):**

1. For each game g that defense D played, and each position slot (WR1/WR2/TE/RB or simply "all WRs"), compute:
   ```
   ratio_g = allowed_g / expected_g
   ```
   - `allowed_g` is what the opposing players produced in that game.
   - `expected_g` is the sum of those same players' season averages, excluding the game against D.
2. Combine the games into a defense factor:
   ```
   DefFactor_D = Σ allowed_g / Σ expected_g
   ```
   A weighted ratio of sums is more stable than a mean of ratios.
3. Shrink the factor toward 1.0:
   ```
   DefFactor_shrunk = (n·DefFactor + k·1.0) / (n + k)
   ```
   - n is the number of games.
   - k is a prior strength. Given the low persistence, k is likely 6-10 games for WR and TE and fewer for QB.
4. Projection:
   ```
   Projection = PlayerBaseline × DefFactor_shrunk
   ```

This decomposes cleanly for visualization: a baseline bar, then a ±% defense adjustment.

**Other options:**
- **Additive version:** points above expected per game, as in the PFF example. A ratio scales better across players of different volume, since a +20% matchup means more for a 90-yard WR1 than a 30-yard WR3.
- **Volume and efficiency split:** compute factors separately for volume allowed (targets or carries allowed to the position relative to expected) and efficiency allowed (yards per target or per carry relative to expected), then multiply each into the matching part of the player baseline.
- **Data needs:**
  - This requires game logs for every opposing player who faced the defense, not just the subject player. With balldontlie, that means pulling per-game stats for all players on the defense's opponents' rosters (or team-game totals by position).
  - Position labels are needed. Positional "slot" (WR1 vs WR3) needs depth or role ordering, which can be approximated by season target rank on the team.

### Gaps
- No public, validated formula was found for 4for4 aFPA or FantasyPoints' adjusted metrics. Their exact shrinkage and weighting are proprietary.
- No source quantified how much schedule adjustment improves the year-to-year or week-to-week predictiveness of DvP over raw DvP.

## Q3. Blending methods: weighted averages, exponential decay, Bayesian shrinkage, stabilization, multiplicative matchup factors

### Takeaway
The practitioner approach is regression to the mean using stabilization points: true rate = (player total + k × league rate) / (player opportunities + k). Apply it to efficiency rates. Combine with a volume projection (recent-weighted) and a multiplicative opponent factor shrunk toward 1.0.

### Cited Findings
- **Tuccito's RB stabilization points:**

  | Stat | Unit | Stabilization point |
  |---|---|---|
  | Yards per carry | carries | 1,978 |
  | Rushing TD rate | carries | 667 |
  | Receptions per route run | routes | 169 |
  | Yards per route run | routes | 308 |
  | TDs per route run | routes | 1,063 |

  The implied formula is `true rate = (player total + k·same-team league average rate) / (player opportunities + k)`. Example: Lamar Miller's YPC = (2,051 + 1,978 × 4.50) / (443 + 1,978) ≈ 4.52. The data years were not stated; the article projects 2015. — [Footballguys, Tuccito True Fantasy Points (RB)](https://www.footballguys.com/article/tuccittotfp0rb)
- **What a stabilization point means:** it is the sample size where split-half reliability reaches about 0.707, where signal variance equals noise variance; equivalently, the point where half the observed variation is skill and half is chance. Carleton cautions that this is not the same as predicting the next sample of equal size. — [Baseball Prospectus, "Reliably stable? You keep using that word"](https://baseballprospectus.com/news/article/31626/baseball-therapy-reliably-stable-you-keep-using-that-word); [RotoWire, "The fallacy of stabilization"](https://www.rotowire.com/baseball/article/the-z-files-the-fallacy-of-stabilization-and-an-early-look-at-home-runs-56442)
- **Lagged features:** lagged (recent-game) features are among the best predictors in an open-source fantasy projection package. — [fantasyfootball PyPI package](https://pypi.org/project/fantasyfootball/0.4.25/)
- **Regression framing:** Footballguys' Regression Alert column (Adam Harstad) repeatedly shows that groups ranked high or low on efficiency or TD metrics revert toward the mean going forward, while volume holds up. — [Footballguys Regression Alert 2024 Wk5](https://footballguys.com/article/2024-regression-alert-week05)

### Inferences
Recommended pipeline for per-game box-score logs (inference):

1. **Volume** (targets, carries, pass attempts per game), with exponential decay over this season's games:
   ```
   w_i = λ^(age_i)
   ```
   - λ of about 0.85-0.92 per game, so the half-life is about 4-8 games.
   - Reset or downweight games before a known role change (injury to a teammate, trade, QB change).
   - Blend with the prior season or career per-game volume as a prior worth about 3-4 games early in the season, fading to near 0 by midseason. This is consistent with the Harvard and Minitab findings that the current season dominates after a few weeks.
2. **Efficiency** (yards per target, yards per carry, catch rate): shrink with stabilization points.
   - Use about 2,000 carries for YPC and the ~300-route YPRR point above.
   - If routes are unavailable, use targets, with a target-based k you derive yourself.
   - Use a league or positional mean as the prior, or the player's own multi-season mean when available.
   - The huge YPC k means a RB's YPC projection should sit close to the league or team average.
3. **Baseline:**
   ```
   Baseline = projected volume × shrunk efficiency
   ```
4. **Matchup:**
   ```
   × DefFactor_shrunk
   ```
   Split into a volume factor and an efficiency factor if possible.
5. **H2H (optional):** treat it as a tiny Bayesian update. Weight it as a few extra games at most, applied as a ratio relative to what the player averaged in that season (not raw yards), which removes the role confound. Or exclude it and only display it.

This decomposition gives natural visualizations:
- A waterfall or contribution bar: baseline → defense ±% → H2H ±% → final.
- Weight bars showing each input's share.
- Shrinkage "pull" arrows from the raw rate to the shrunk rate.

Data needs:
- Targets, carries, attempts and yards are available from box-score logs.
- Routes run, snap share and air yards are not in standard box scores. They require nflverse/nflfastR participation data or PFF.

### Gaps
- I found no published NFL stabilization points for WR or TE targets per game, receptions or receiving yards per game on a per-game basis. These would need to be computed (split-half by odd and even games) from the app's own logs.
- I found no published optimal decay λ for NFL weekly projections.

## Q4. Volume and efficiency inputs vs raw yardage

### Takeaway
Project volume and efficiency separately. Volume (target share, carries, routes) is sticky and drives most of the signal. Efficiency (YPC, EPA/rush, yards per target) is noisy and should be shrunk hard.

### Cited Findings
- Target share has a year-over-year r of about 0.70, YPRR above 0.60, QB EPA/play about 0.60, and RB EPA/rush is negligible. — [SumerSports](https://sumersports.com/the-zone/sticky-football-stats-predictive-nfl-metrics/)
- TPRR is more stable than YPRR or yards per target. — [Football Perspective](https://www.footballperspective.com/yards-per-route-run-yards-per-target-and-targets-per-route-run/)
- Targets are the most dependable WR volume input, and TDs are among the least stable. — [Sharp Football Analysis 2024](https://www.sharpfootballanalysis.com/fantasy/wide-receiver-stats-that-matter-fantasy-football-2024/)
- Team target share and yards per team pass attempt are stable for TEs. — [Sharp Football Analysis, TE stats that matter](https://www.sharpfootballanalysis.com/fantasy/te-stats-that-matter-fantasy-football/)
- YPC is inconsistent within and across seasons. — [Football Perspective](https://www.footballperspective.com/thoughts-on-running-back-yards-per-carry/)

### Inferences
- **Box-score-only proxies:**
  - Target share = player targets / team targets in games played (team targets is the sum of the team's player logs).
  - Carry share = carries / team carries.
  - Pass-attempt volume for QBs.
- **Defense-side analog:** targets or carries allowed to the position, and yards per target or per carry allowed, both opponent-adjusted as in Q2.
- **Extra data needed:**
  - EPA and success rate allowed, air yards, aDOT, routes and snaps come from nflverse play-by-play and participation data. The project memory notes nflverse pbp is already used for the Baker's Buns regression tiles, so that pipeline could supply them.
  - balldontlie `/plays` may also allow building some of these.

### Gaps
- No source gave week-to-week (as opposed to year-to-year) stability for target share or YPRR.
- No source quantified the stability of defensive EPA or success rate allowed. Search returned nothing usable.

## Q5. Turning a point projection into a distribution and over/under probability

### Takeaway
Books set prop lines near the median, and yardage is right-skewed, so the mean sits above the median. A normal approximation, P(over) = 1 − Φ((line − μ)/σ), is the common simple approach but misstates the tails. Skewed continuous fits (gamma or log-normal) suit yardage, discrete fits (Poisson or negative binomial) suit receptions and TDs, and an empirical or KNN-style distribution avoids parametric assumptions.

### Cited Findings
- Books set prop lines near the median while DFS projections report the mean, and the two diverge most for boom-or-bust players. — [Stokastic, Player props for DFS players](https://www.stokastic.com/articles/dfs-strategy/player-props-for-dfs-players)
- A receiver can have a 65-yard mean projection but a median under 50 because of explosive games. — [PFF, receiving yards props 2021](https://www.pff.com/news/bet-best-bets-receiving-yards-player-props-2021) (via search snippet)
- **Normal worked example:** μ = 74, σ = 15 gives P(under 72.5) ≈ 44%, so the over is about 56%, compared with the 52.4% break-even at −110. — [DeucesCracked, prop betting strategy](https://www.deucescracked.com/sports-betting/strategy/prop-betting-strategy)
- **Cumulative-probability approach:** P(over) = 1 − P(X ≤ line).
  - Example: Josh Allen's median rushing was 19 yards (50% cumulative), so 19.5 at −105 has EV ≈ −0.025, while the under at 26.5 hits about 61.5% for EV ≈ +0.2.
  - Example: Dalvin Cook averaged 3+ receptions but had ≤2 in 8 of 14 games, and the model distribution gave a 51% chance of ≤2.
  - The article prefers KNN with inverse-distance weighting over similar historical players, sampled to simulate outcomes, rather than a normal assumption.
  - Source: [Advanced Sports Analytics substack, "Getting Ready for NFL: Props & Sports Modeling Approaches"](https://advancedsportsanalytics.substack.com/p/getting-ready-for-nfl-props-and-sports)
- Game-level TDs are modeled as Poisson; PFF's simulation is "more pessimistic than raw data." — [PFF, receiving TD props 2021](https://www.pff.com/news/bet-best-bets-receiving-touchdown-player-props-2021)
- Gamma is a flexible family for positive, skewed outcomes, while log-normal has a fixed right-skewed shape with a heavier right tail. — [mlmodels vignette, Gamma vs Lognormal](https://brieger.esalq.usp.br/CRAN/web/packages/mlmodels/vignettes/mlmodels-gamma-lognormal.html)
- A football play-calling paper modeled positive pass yardage with a Gamma-Gamma conjugate (shape fixed at 1.3) after a normal mixture fit exaggerated high-yardage modes. — [arXiv 2103.06939](https://arxiv.org/pdf/2103.06939)
- A low-quality NBA spec used a normal for points and a negative binomial for rebounds and assists, a common pattern of treating counts as non-normal. — [edge-assist NBA spec](https://edge-assist.duckdns.org/data-status/docs/nba-player-props/strategy) (low reliability)

### Inferences
- **Receiving and rushing yards:** fit a gamma using the player's projected mean μ and a dispersion from his own game logs, shrunk toward a positional CV.
  ```
  shape = 1 / CV²
  scale = μ / shape
  P(over) = 1 − GammaCDF(line)
  ```
  - Report both the mean and the median. For a gamma with CV of about 0.6-0.8 the median is roughly 5-12% below the mean (property of the gamma, not from a source).
  - Handle zero games (an injury exit, or a 0-yard game) with a hurdle: P(0) plus the gamma for positive values.
- **Receptions:**
  - Simple: Poisson with mean λ.
  - Better: a binomial on projected targets × catch rate, or a negative binomial if there is overdispersion.
  - For half lines (4.5), the PMF sum gives P(over) exactly.
- **TDs:** Poisson. P(anytime TD) = 1 − e^(−λ).
- **Passing yards:** close to normal for starters (less skew because of high volume). Normal is acceptable, with σ estimated from game logs.
- **Fantasy points:** simulate. Draw volume, then efficiency, then TDs, and sum, or use the empirical distribution of the player's game logs scaled by projection / baseline.
- **Empirical-quantile option** (fits box-score logs well): take the player's last N games, rescale each by projection / his average over those games, and read the over-probability as the share of rescaled games above the line (smooth with a kernel). This makes a clean visualization: a dot strip or histogram of rescaled games with a line marker.
- Convert P(over) to fair odds and compare with the book's no-vig price, using the project's sports-betting skill (01-odds-and-probability.md) for implied-probability and vig math.

### Gaps
- I found no published calibration study comparing normal, gamma, log-normal or negative-binomial fits for NFL yardage props. Calibration would need to be tested on the app's own logs against closing lines.
- I found no published positional σ or CV values for NFL per-game yardage. Unabated's methodology is not public in what I found.

## Q6. Common pitfalls

### Takeaway
The biggest errors are trusting small samples (H2H, early-season DvP, efficiency), ignoring role or roster changes, and treating mean projections as medians. Injuries, game script and schedule skew also distort all three inputs.

### Cited Findings
- **DvP:** schedule skew distorts it (for example, facing elite TEs early). — [Establish The Run DvP](https://establishtherun.com/establish-the-run-nfl-dvp/)
- **DvP:** real defensive quality does not reliably carry over to fantasy points allowed, and RB points allowed are tied to team quality and game script. — [4for4](https://www.4for4.com/2025/preseason/do-defenses-repeat-fantasy-football-performances)
- **Past defensive effectiveness:** it does not guarantee continuation. — [PFF, Spratt 2014](https://www.pff.com/run-offenses-vs-run-defenses/)
- **Remaining prediction error:** attributed to injuries, trades and random variation. — [Minitab part 2](https://blog.minitab.com/en/blog/the-statistics-game/how-well-did-minitab-predict-fantasy-football-player-performance-part-2-v1)
- **Efficiency context:** high-YPRR, low-target-share players are less likely to sustain impact, and QB EPA is shared with line, receivers and scheme, so it moves when the supporting cast changes. — [SumerSports](https://sumersports.com/the-zone/sticky-football-stats-predictive-nfl-metrics/)
- **Mean vs median:** a mean projection above the line can still lose to the median because of outlier-propped averages. — [Stokastic](https://www.stokastic.com/articles/dfs-strategy/player-props-for-dfs-players)
- **Stabilization caveat:** reaching the stabilization point does not equal predicting the next equal-size sample. — [Baseball Prospectus](https://baseballprospectus.com/news/article/31626/baseball-therapy-reliably-stable-you-keep-using-that-word)

### Inferences (implementation guards)
- **H2H:**
  - Filter to games where the player had a similar role, for example his team target share that season within ±X of the current share.
  - Express each H2H game relative to his season average that year (a ratio), not as raw yards.
  - Down-weight by age (for example 0.5 per season back).
  - Show n prominently. Flag coordinator and QB changes on both sides if the data exists.
- **Game logs:** exclude or flag games the player left early through injury (low snaps), and games before a role change. Box scores lack snaps, so a heuristic is needed, for example targets plus carries far below his median.
- **Defense samples:** use only the current season (with a last-season prior early on), and flag known defensive changes such as injured CB1, scheme or coordinator change, and trades.
- **Game script:** a Vegas spread and total would explain more than DvP for RB volume. balldontlie `/odds` is reachable at the GOAT tier, so the spread and implied team total can be added as context or as a volume multiplier.
- **Display:**
  - Show uncertainty bands: a projection interval from the fitted distribution plus the line.
  - Show the effective sample size of each input, so users see why H2H barely moves the number.
  - Always display the median beside the mean when comparing with a prop line.

### Gaps
- No quantitative source was found on how much game script (spread or total) improves player prop projections versus DvP. The strong RB and game-script link is asserted by 4for4 but not quantified.
- No source was found on how often coaching or coordinator changes break H2H or DvP persistence.
