# Let the baseline lead, the matchup nudge

The /player-projections page should be built around one decomposable model and four linked charts. The model: **projection = recent-weighted volume × shrunk efficiency × an opponent-adjusted defense factor shrunk hard toward 1.0**, with career head-to-head (H2H) games shown as context and given almost no weight. The charts: (1) a per-game bar log with the prop line drawn across it, (2) a forest-plot-style "evidence rows" chart that shows each of the three inputs as individual game dots, labeled with its sample size n and its weight, and ends in a projection diamond, (3) a 20–50-dot quantile dotplot of the projected outcome with the over-dots counted, and (4) a compact defense-allowed-vs-expected strip or heat grid. The weighting comes straight from the evidence. Season-to-date production overtakes prior-season data within a few weeks. Defense-vs-position (DvP) numbers persist weakly (year-to-year r of only 0.16–0.26) and add only about 0.03 R² to next-week rushing forecasts. No published study shows that a player's history against one team predicts anything. The visual choices also have evidence behind them: quantile dotplots got decision-makers to 97% of optimal payoff in controlled tests, while bar-of-averages and error-bar charts mislead at small n. Everything except routes, snaps and air yards can be built from balldontlie box scores. nflverse fills those gaps and can add play-by-play (PBP) views later. The most distinctive part is the evidence-rows chart, because commercial tools show form, H2H and DvP side by side but almost never show how much each one moves the number.

## Volume carries the signal, defense nudges it, head-to-head is flavor

The three inputs are not equally informative, and the page should say so visually and mathematically. On the player side, current-season production became more predictive than prior-season production after a few weeks of play, and a player's average through Week 5 explained **82% of the variance** in his final-season average ([Harvard Sports Analysis Collective](https://harvardsportsanalysis.org/2015/10/is-it-time-to-give-up-on-insert-underperforming-fantasy-player-here/); [Minitab](https://blog.minitab.com/en/the-statistics-game/how-well-did-minitab-predict-fantasy-football-player-performance-part-1)). Within a player's line, volume is far stickier than efficiency. Target share has a year-over-year r of about **0.70**, while RB EPA per rush is "virtually negligible" ([SumerSports](https://sumersports.com/the-zone/sticky-football-stats-predictive-nfl-metrics/)), and yards per carry is unstable both within a season and across seasons ([Football Perspective](https://www.footballperspective.com/thoughts-on-running-back-yards-per-carry/)). Stabilization estimates make the gap concrete. Yards per carry needs about **1,978 carries** before half of the observed variation is skill rather than luck, compared with 169 routes for receptions per route run ([Footballguys](https://www.footballguys.com/article/tuccittotfp0rb)). In practice, a running back's projected YPC should sit very close to the league average.

The defense input is real but small. Across 2014–2024, year-to-year correlation in fantasy points allowed was **0.26 for QBs, 0.23 for RBs and 0.16 for TEs**, and only 20–30% of top-five defenses repeated ([4for4](https://www.4for4.com/2025/preseason/do-defenses-repeat-fantasy-football-performances)). PFF found that adding a defense adjustment raised next-week rushing-yards R² from **0.05 to 0.08**. That is a meaningful relative gain, but it is tiny next to single-game noise ([PFF](https://www.pff.com/run-offenses-vs-run-defenses/)). Raw DvP is also biased by schedule: a defense that met two elite tight ends in September looks worse against TEs than it is ([Establish The Run](https://establishtherun.com/establish-the-run-nfl-dvp/)). 4for4 says its schedule-adjusted version becomes meaningful only after about **four games** ([4for4](https://www.4for4.com/2014/preseason/schedule-adjusted-fantasy-points-and-streaming-tight-ends)).

Career H2H is the weakest input. Stathead's Versus Finder encourages checking a QB's history against his next opponent but offers no evidence that the history predicts anything ([Sports Reference](https://www.sports-reference.com/blog/2023/06/versus-finder-launches-on-stathead-football/)). The research found no NFL study that tests it directly. The structural problem is obvious, though: a player sees a division rival about twice a year and other teams at most once, so a career H2H sample is typically 2–8 games spread across different rosters, coordinators and roles. Reviewers already flag shrinking samples as a core failure of filter-heavy prop tools ([BettorEdge](https://www.bettoredge.com/post/propsmadness-review)). A "2/2 = 100%" H2H hit rate is the most misleading number such a page can show. The defensible position is to plot H2H games and hold their weight at **0–5%**. That figure is an inference from sample size, not a tested optimum.

## Build the projection as a chain of shrunk multipliers

The combination method should be chosen so that every step can be drawn. The recommended pipeline works on box-score logs.

**Step 1, volume.** Project targets, carries or attempts with exponential decay over this season's games (λ ≈ 0.85–0.92 per game, a half-life of about 4–8 games). Use last season as a prior worth about three or four games that fades out by midseason. Open Source Football's rolling-average study backs the shape: windows that use all available games beat a fixed 10-game window, and exponential weighting worked best for passing and total EPA ([Open Source Football](https://www.opensourcefootball.com/posts/2020-12-29-exploring-rolling-averages-of-epa/)). The "last 5" view is therefore most useful for spotting role changes, not hot hands.

**Step 2, efficiency.** Shrink yards per target, yards per carry and catch rate toward the positional mean with the standard formula, *(player total + k × league rate) / (player opportunities + k)*, where k is the stabilization point ([Footballguys](https://www.footballguys.com/article/tuccittotfp0rb)). Baseline = volume × shrunk efficiency.

**Step 3, defense factor.** For each game the opponent played, compare what the opposing players produced with what those same players averaged in their other games. Sum across games: DefFactor = Σ allowed / Σ expected. This is the ratio form of RotoGrinders' matchup-adjusted DvP, where a defense holding 25-point RBs to 20 points rates 80% ([RotoGrinders](https://rotogrinders.com/pages/matchup-adjusted-dvp-legend-894142)). It is also the box-score analogue of Open Source Football's opponent adjustment, which uses lagged 10-game averages so that only prior games count ([Open Source Football](https://www.opensourcefootball.com/posts/2020-08-20-adjusting-epa-for-strenght-of-opponent/)). Then shrink it: (n × DefFactor + k × 1.0) / (n + k), with k of roughly 6–10 games for WR and TE and fewer for QB, which matches the persistence ranking above. A ratio beats PFF's additive version ([PFF](https://www.pff.com/news/strength-of-opposition-and-fantasy-points-allowed)) because a +15% matchup should be worth more yards to a 90-yard WR1 than to a 30-yard WR3. Where possible, split the factor into volume allowed (targets to the position versus expected) and efficiency allowed (yards per target versus expected), and multiply each into the matching part of the baseline.

**Step 4, H2H.** Re-express each H2H game as a ratio to the player's own average that season. This removes the confound that he was a WR3 in 2022 and a WR1 now. Decay each game by about half per season back. Either apply the result as a few games' worth of Bayesian update, or leave it out of the math entirely.

**Step 5, distribution.** Turn the mean into an outcome distribution. Books set lines near the median while projections report the mean ([Stokastic](https://www.stokastic.com/articles/dfs-strategy/player-props-for-dfs-players)), and a receiver can have a 65-yard mean but a median under 50 ([PFF](https://www.pff.com/news/bet-best-bets-receiving-yards-player-props-2021)). Use the following families:

| Stat | Distribution | P(over) / display |
|---|---|---|
| Rushing and receiving yards | Gamma (shape = 1/CV², CV from the player's logs shrunk to a positional value), plus a hurdle for zero games | 1 − GammaCDF(line) |
| Passing yards | Normal | 1 − Φ((line − μ)/σ) |
| Receptions | Binomial on targets × catch rate, or Poisson | Exact PMF sum at half-lines |
| TDs | Poisson ([PFF](https://www.pff.com/news/bet-best-bets-receiving-touchdown-player-props-2021)) | Anytime = 1 − e^(−λ) |
| Any stat (empirical option) | Rescale the player's last N games by projection ÷ his average, then count the share above the line | Count of games over |

The empirical option has the advantage that the chart and the math are the same object. Convert P(over) to fair odds and compare it with the no-vig price using the project's sports-betting skill.

None of these weights or k values come from a validated public model. 4for4's and FantasyPoints' adjustments are proprietary, and no source documents the weights any commercial tool uses. They are informed starting points and should be backtested against the app's own logs and closing lines.

## Four charts, each answering one question

Because the model is a chain of steps, the page can show each step instead of only a final number. That fills the gap left by commercial tools, which mostly present "parallel evidence plus one bottom-line number" ([Props.cash](https://propsdotcash.beehiiv.com/p/propscash-newsletter-new-nba-feature); [4for4](https://www.4for4.com/2021/preseason/nfl-player-prop-stat-explorer-introduction)).

### The game log with a prop line is table stakes

The industry baseline is 4for4's Prop Stat Explorer: one bar per game labeled by opponent and home/away, a dotted horizontal prop line, a hit rate, and the projection appended as a distinct final bar ([4for4](https://www.4for4.com/2021/preseason/nfl-player-prop-stat-explorer-introduction)). Keep that design but fix its weaknesses.

**Color.** Over and under should not depend on red versus green alone. Use blue versus orange or filled versus hollow, plus an O/U glyph, as Datawrapper's color-blindness guidance recommends ([Datawrapper](https://www.datawrapper.de/blog/colorblindness-part1)). This also satisfies WCAG 1.4.1, which says color must not be the only cue, and 1.4.11, which requires 3:1 contrast for chart marks ([Deque](https://dequeuniversity.com/resources/wcag2.1/1.4.11-non-text-contrast)).

**Labels.** Put the line value directly on the rule ("O/U 64.5") and the hit rate with its n in the title ("Over in 6 of 9").

**H2H games and pushes.** Mark H2H games with a ring rather than a third hue. Give pushes a neutral state.

**Usage strip.** Add a thin target-share or carry-share strip under the bars, computed as player targets ÷ team targets from the same logs. A low bar can then be read as low usage rather than a bad matchup. This is the usage layer PropFinder and PFF sell as a differentiator ([PropFinder](https://www.propfinder.app/)).

**Interaction.** Offer a draggable line or a threshold ladder that recomputes the hit rate. BettingPros' slider and Outlier's Custom Line Builder show users want this ([FantasyPros](https://blog.fantasypros.com/8-24-2022-bettingpros-prop-bet-analyzer/); [Unders Club](https://undersclub.substack.com/p/issue-37-custom-fitting)).

**Breakeven.** Show the breakeven implied by the price next to the hit rate, because a 60% hit rate loses at −262, where breakeven is about 72% ([StatsBench](https://blog.statsbench.com/mlb-hits-runs-rbis-props-guide/)).

### Forest-plot rows show the three inputs and what each one is worth

This is the centerpiece and the direct answer to "how were the inputs combined." Meta-analysis forest plots solve the same problem: several estimates of unequal reliability pooled into one number. Each row shows a point estimate whose marker size encodes weight, a printed weight percentage, and a pooled row at the bottom. Practitioners print the weight because a dramatic-looking estimate can barely move the pooled result ([MetricGate](https://metricgate.com/blogs/reading-a-forest-plot/)).

The rows are:

1. **Season baseline**
2. **Recent form**, last 5 games
3. **Career vs [opponent]**, with n in the label
4. **[Opponent] allowed vs expected**, each dot one opponent game, rescaled to this player's baseline
5. **Projection**, a diamond with its interval

Every row plots individual games as dots with a median tick, carries its weight ("H2H · n=3 · 4%"), and shares one x-axis with a dashed prop rule running through all rows.

Plotting individual games rather than averages follows Weissgerber's finding that "many different data distributions can lead to the same bar or line graph," and her rule to add error bars only when n is large enough to avoid false certainty ([Mayo Clinic summary](https://newsnetwork.mayoclinic.org/discussion/discoverys-edge-the-fault-in-our-bars/); [Weissgerber guide](https://openresearch-repository.anu.edu.au/bitstream/1885/155722/1/Data_Viz_Weissgerber%20v1.pdf)). Put n in the label text, not a tooltip, because tooltips are unreliable on touch screens. Draw no interval on rows with n ≤ 2.

Because the model is multiplicative, a three- or four-bar waterfall works as a secondary view: baseline 58 → defense +6% → H2H +1% → 62. Keep it under five bars. No study compares waterfalls with forest layouts for lay readers.

### A quantile dotplot turns the projection into countable outcomes

For the projected distribution, the evidence clearly favors a quantile dotplot. In Kay et al.'s transit-app study, quantile dotplots reduced the variance of people's probability estimates compared with density plots, and they were designed specifically for small mobile screens ([UW IDL](https://idl.uw.edu/papers/when-ish-is-my-bus)). In an incentivized follow-up, **50-dot plots produced decisions at 97% of optimal payoff**, five points above a no-uncertainty control. CDF plots did nearly as well, and both beat text ([UW IDL](https://idl.uw.edu/papers/uncertainty-bus)).

Design details:

- **Dot count.** Draw 20 dots on phones (5% each) or 50 on desktop. Wilke warns that too many dots read as a continuum ([Wilke](https://clauswilke.com/dataviz/visualizing-uncertainty.html)).
- **Line and over-dots.** Fill the dots above the prop line and leave the ones below hollow.
- **Caption.** Use frequency framing, which readers grasp more intuitively than percentages ([Padilla et al.](https://www.frontiersin.org/journals/computer-science/articles/10.3389/fcomp.2021.758406/pdf)): "31 of 50 simulated games go over 64.5 (62%)."
- **Mean and median.** Mark them with thin ticks, not a bold headline. Kale et al. found that emphasizing the mean biases users toward discounting uncertainty ([arXiv](https://arxiv.org/pdf/2007.14516)). Showing the median matters because the line sits near it.
- **Touchdowns.** Replace the dotplot with a three-bar P(0)/P(1)/P(2+) chart or a 100-cell frequency grid.
- **Animation.** Do not auto-play simulated outcomes. The NYT election needle's jitter drew heavy public criticism, and the Times later added a toggle to turn it off ([Nieman Lab](https://www.niemanlab.org/2020/11/bad-polls-fake-news-and-that-damned-needle-heres-how-the-media-covered-a-twisty-election-night/)). If hypothetical-outcome animations are added, make them opt-in.

### The defense panel should show residuals, not raw ranks

The opponent context should plot what this defense allowed relative to what each offense normally does, not a raw 1–32 rank. Commercial tools split between raw rank tables (FantasyPros, Props.cash) and opponent-adjusted deltas (4for4 aFPA, RotoGrinders %, ESPN Adjusted FPA). 4for4's own example shows why the adjustment matters: Dallas allowed fewer QB points than Kansas City, but the QBs Dallas faced averaged 14.4 points while Kansas City's averaged 19.1, which flipped the ranking ([4for4 FAQ](https://www.4for4.com/faq/what-schedule-adjusted-fantasy-points-allowed)).

A box-score-buildable design is a per-game strip of allowed ÷ expected for the relevant position, using a diverging color scale around 100%, with the shrunk factor drawn as a line. Pair it with a Sharp-style text edge label ("Offense edge," "Even") so meaning does not rely on hue alone ([Sharp Football](https://www.sharpfootballanalysis.com/?p=129218)). Once nflverse PBP is wired in, the natural upgrade is a 3×3 depth-by-direction grid of EPA allowed with attempt counts per cell ([Kabir Devgun](https://kabirdevgun.substack.com/p/nfl-advanced-coverage-heat-maps)). Coverage-scheme views (man/zone, WR vs. CB) need paid charting data and are out of scope.

### Layout on the page

Stack one card per stat: Rec Yds, Receptions, TDs. Each card holds its game log, the evidence rows and the dotplot, all on a shared x-scale within the stat so the prop line stays in one place. Give each stat its own y-axis and say so. Use one column on phones and two or three on desktop. Datawrapper and CDC small-multiple guidance both favor direct labels, no legends, and fewer repeated axis labels ([Datawrapper](https://www.datawrapper.de/blog/small-multiple-column-charts); [CDC COVE](https://www.cdc.gov/cove/data-visualization-types/small-multiples.html)).

## Conclusion

The main finding is that the honest projection is mostly the player. The chart that best shows a "player vs this defense" projection is one that visibly shows the defense and the H2H history *not* moving the number much. The forest-plot rows do that: users see every game behind every input, see that the H2H row has three dots and a 4% weight, and see the diamond land close to the season baseline. That is both more truthful and more distinctive than the hit-rate grids and DvP ranks competitors show side by side without explaining how they combine. It also guards against the most common failure the research found, false confidence from tiny filtered samples.

Two points remain open and are worth testing on the app's own data. First, every weight, decay rate, shrinkage constant and per-game coefficient of variation (CV) recommended here is a principled prior, not a published optimum. The app can derive per-game stabilization points with split-half tests on its balldontlie logs and check calibration against closing lines. Second, game script (spread and implied team total from balldontlie's `/odds`) is a likely stronger driver of RB volume than DvP, though no source quantified it. It is the next input to add as a volume multiplier and a fifth evidence row.
