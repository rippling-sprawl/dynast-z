# Visualizing an Uncertain, Small-Sample Player Projection (prop line, sources, contributions, distribution)

Scope: chart choices for (a) a per-game log against a prop line, (b) one metric compared across three sources (recent form, head-to-head history, opponent-allowed), (c) how each source contributes to the final projection, (d) the projected distribution and P(over)/P(under). Built by one developer with Chart.js / D3 / Observable Plot / plain SVG, mobile-first.

## What does uncertainty-visualization research say about quantile dotplots, HOPs, gradient/interval plots and density plots, and how did FiveThirtyEight, The Economist and the NYT needle apply it?

### Takeaway
Discrete, countable displays work best for lay decisions. Quantile dotplots (about 20 to 50 dots) and CDF plots beat text and point estimates in incentivized decision tests, and they suit small screens. HOPs help with "which is bigger" comparisons, but they need animation and can upset users (see the NYT needle). Showing a bold mean on top of the uncertainty slightly biases people toward ignoring the uncertainty. For a prop page, the strongest evidence-backed choice for (d) is a 20- or 50-dot quantile dotplot with the line drawn on it and the over-dots counted ("31 of 50 simulated games go over").

### Cited Findings
- Kay, Kola, Hullman and Munson (CHI 2016), "When(ish) is My Bus?": in a controlled experiment, quantile dotplots reduced the variance of people's probability estimates by about 1.15x compared with density plots and supported more confident estimates. They were designed as a discrete display for small mobile screens, based on a survey of users of a real-time transit app. — [UW IDL](https://idl.uw.edu/papers/when-ish-is-my-bus); [paper PDF](https://vis.mit.edu/classes/6.859/readings/pdfs/Kay-WhenishIsMyBus.pdf)
- Fernandes, Walls, Munson, Hullman and Kay (CHI 2018, Best Paper Honorable Mention): in an incentivized bus-catching decision task, 50-dot quantile dotplots gave decisions with expected payoffs at 97% of optimal, 5 percentage points above the no-uncertainty control. Decisions were also more consistent, with a within-subject SD of about 3 points. CDF plots performed nearly as well. Both beat textual uncertainty, which depended on which probability interval the text reported. — [UW IDL](https://idl.uw.edu/papers/uncertainty-bus); [paper PDF](https://mucollective.northwestern.edu/files/2018-UncertainBusDecisions-CHI.pdf)
- Hullman, Resnick and Adar (PLOS ONE 2015): hypothetical outcome plots (animated random draws) let viewers judge comparisons of two or three quantities much more accurately than error bars or violin plots. For single-quantity questions, accuracy was similar across all three. In the motivating task, more than half of viewers underestimated Pr(B > A) (true value about 0.75) from static plots. — [PMC](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4646698/)
- Kale, Kay and Hullman (IEEE VIS 2020, best paper): they tested 95% intervals, HOPs, densities and quantile dotplots, each with and without a mean. Adding the mean had "small biasing effects on both magnitude estimation and decision-making, consistent with discounting uncertainty." The design that gave the least biased estimates was not the one that best supported decisions. Many users switched strategies, and they often fell back on comparing positions (about 75% of interval users, 59% of dotplot users). — [arXiv](https://arxiv.org/pdf/2007.14516); [UW IDL](https://idl.uw.edu/papers/effect-size-judgments)
- Correll and Gleicher (IEEE TVCG 2014), "Error Bars Considered Harmful": bar charts with error bars communicate uncertainty poorly. Gradient plots (opacity follows the CDF) and violin plots (width follows the density) worked better for inference tasks. They ran 3 Mechanical Turk experiments with 240 participants, framed as polling, weather and finance. — [PMC author manuscript](https://pmc.ncbi.nlm.nih.gov/articles/PMC6214189); [PDF](https://graphics.cs.wisc.edu/Papers/2014/CG14/Error%20Bars%20Considered%20Harmful%20Exploring%20Alternate%20Encodings%20for%20Mean%20and%20Error.pdf)
- Padilla, Kay and Hullman's handbook chapter "Uncertainty Visualization": a frequency framing ("1 out of 10") is understood more intuitively than a probability framing ("10%"), building on Gigerenzer. Padilla et al. (2018) also review evidence for a dual-process account, in which fast, low-effort reading competes with slow, deliberate reasoning. — [NIU lecture citing the chapter](https://faculty.cs.niu.edu/~dakoop/cs628-2021fa/lectures/lecture15.pdf); [Frontiers PDF](https://www.frontiersin.org/journals/computer-science/articles/10.3389/fcomp.2021.758406/pdf)
- Claus Wilke, *Fundamentals of Data Visualization*, chapter 16:
  - Recommends frequency framing.
  - "Quantile dotplots should use a small to moderate number of dots." Too many dots read as a continuum and the advantage of discreteness is lost.
  - Every error bar must say what it represents.
  - Graded error bars show "a range of different possibilities" but add clutter.
  - Confidence strips "are difficult to read."
  - HOPs should use fast or fade transitions, because smooth tweening makes probabilities harder to judge.
  - Static displays risk the "deterministic construal error," where readers take an interval for a hard min/max.
  — [Wilke ch. 16](https://clauswilke.com/dataviz/visualizing-uncertainty.html)
- ggdist (Matthew Kay's R package): its documentation shows analytical distributions with 100 quantiles by default and cites Kay 2016 and Fernandes 2018. For dotplots with a threshold, it recommends "weave" or "swarm" layouts because they place dots closer to their true x positions than binned layouts do. It can also color dots by the interval they fall in. — [ggdist dotsinterval vignette](https://mjskay.github.io/ggdist/articles/dotsinterval.html)
- FiveThirtyEight 2020: the model ran 40,000 simulations, and the page showed a sample of 100 outcomes "to give readers a sense of the range." FlowingData noted the forecast showed many hypothetical outcomes, used few percentages in favor of "fuzzier sounding odds," and used the Fivey Fox mascot for interpretation hints. — [538 forecast page](https://projects.fivethirtyeight.com/2020-election-forecast); [FlowingData](https://flowingdata.com/2020/08/12/fivethirtyeight-launches-2020-election-forecast)
- NYT needle (2016): Gregor Aisch explained that the jitter was bounded by the 25th to 75th percentiles of simulated outcomes. It was meant to signal a live feed and to convey uncertainty better than printed percentiles would. The public reaction was heavily negative ("irresponsible design at best, unethical at worst"), and a jittering gauge reads like a broken instrument. In 2018 the NYT added a toggle to turn the jitter off. In 2020 the needle moved only when data changed. — [vis4.net (Aisch)](https://vis4.net/blog/jittery-gauges-election-forecast); [FlowingData](https://flowingdata.com/2016/11/15/showing-uncertainty-during-the-live-election-forecast/); [Nieman Lab](https://www.niemanlab.org/2020/11/bad-polls-fake-news-and-that-damned-needle-heres-how-the-media-covered-a-twisty-election-night/)
- The Economist 2020 (Gelman and Heidemanns): a Bayesian model in Stan that partially pools a fundamentals-based prior with polls, which is structurally like blending several noisy sources. Gelman's retrospective raised concerns about how well its uncertainty was quantified. Its headline probability was much higher than 538's (for example 97% vs 89%), with the gap coming from uncertainty levels rather than central estimates. — [HDSR paper](https://hdsr.mitpress.mit.edu/pub/yoa73r1m); [Gelman blog](https://statmodeling.stat.columbia.edu/2020/10/22/election-forecasting-how-we-succeeded-brilliantly-failed-miserably-or-landed-somewhere-in-between/)

### Inferences
- For (d), the projected distribution: use a quantile dotplot with 20 dots on mobile (each dot is 5%) or 50 dots on a wider screen. Draw a vertical prop-line rule. Fill the dots above the line in one hue and the dots below it hollow or in a second hue. Label it with a frequency phrase such as "~31 of 50 sims over (62%)". Every part of this is backed by Kay 2016, Fernandes 2018, Wilke and Padilla. It is easy in plain SVG or D3: take n evenly spaced quantiles of the predictive distribution, bin them by width, and stack them.
- Pair the dotplot with a small CDF readout ("P(over 64.5) = 62%"). CDFs were nearly as good as dotplots for decisions, and a single number is screen-reader friendly.
- Keep the median or mean marker visually quiet, for example a thin tick rather than a big bold number above the chart. Kale 2020 shows that emphasizing the mean nudges users to discount uncertainty.
- Avoid auto-playing HOPs or jitter. The NYT needle shows the backlash risk, and animation is poor for accessibility. If HOPs are used at all, make them opt-in ("simulate games" button) with discrete frame transitions, as Wilke advises. They are most useful for comparing two things.
- A sports projection that blends several sources is like the Economist's pooling. The lesson is that the width of the uncertainty is a modeling choice and should not be visually understated.

### Gaps
- I could not fetch FiveThirtyEight's own "how we designed the look of our 2020 forecast" article (the URL now redirects to ABC News), so the specific design rationale is secondhand via FlowingData.
- I did not retrieve The Economist's "how this works" page, so chart-level design details for the Economist are missing.
- No study found tested these designs specifically for sports betting or prop decisions.

## Which charts show small samples honestly, and how should n be shown?

### Takeaway
With 3 to 17 games per source, show every game as its own mark (dot, strip or per-game bar) and print n explicitly. Bars of averages and error bars hide the distribution and can imply false precision at small n.

### Cited Findings
- Weissgerber et al. (PLOS Biology 2015) reviewed 703 physiology papers and found that most showed continuous small-sample data as bar or line graphs. This is a problem because "many different data distributions can lead to the same bar or line graph." They recommend dot plots of individual observations. — [Mayo Clinic summary](https://newsnetwork.mayoclinic.org/discussion/discoverys-edge-the-fault-in-our-bars/); [JCI reference](https://m.jci.org/references/scholar/35903/B40)
- Weissgerber's data-visualization guide says to make every data point visible, use symmetric jittering, list the sample size under each group label, and "only add error bars if the sample size is large enough to avoid creating a false sense of certainty." Bar graphs are for counts or proportions, not continuous data. — [ANU repository PDF](https://openresearch-repository.anu.edu.au/bitstream/1885/155722/1/Data_Viz_Weissgerber%20v1.pdf)
- Wilke shows raw observations as jittered strip-chart dots under summary intervals, and warns that error bars must state what they represent. — [Wilke ch. 16](https://clauswilke.com/dataviz/visualizing-uncertainty.html)
- In forest plots, marker size usually encodes weight, which is driven by sample size and precision. Many plots also print the numeric weight, because "a study can have a dramatic-looking point estimate and still barely move the pooled result if its weight is small." — [MetricGate](https://metricgate.com/blogs/reading-a-forest-plot/); [CASRAI](https://casrai.org/guides/how-to-read-a-forest-plot)
- ggdist can scale a slab's thickness by sample size so that each slab's area reflects n. — [ggdist vignette](https://mjskay.github.io/ggdist/articles/dotsinterval.html)

### Inferences
- For (b), comparing sources: draw a strip or dot plot with three rows (Recent L5, vs. Opponent H2H, Opp. allowed to position). Each game is a dot, with a short median tick, and the row label carries n ("H2H · n=2"). Draw the prop line as one vertical rule through all three rows. This works in Observable Plot (dot + ruleX + tickX) or a few dozen lines of SVG.
- Put n in the label text, not only in a tooltip, because tooltips are unreliable on touch screens. Optionally fade rows with n < 3, or add a "small sample" tag.
- For the opponent-allowed row, each dot can be a game the defense played against that position, which keeps the same unit (games) as the other rows.
- Do not draw intervals for rows with n of 1 or 2. Weissgerber says to add error bars only when n is large enough.

### Gaps
- I found no research quantifying how lay readers discount evidence when n is shown as text versus encoded visually (opacity or size).

## Which charts best show how each input contributes to the result (waterfall, contribution bars, slope, dumbbell, forest-plot rows, bullet charts)?

### Takeaway
A forest-plot-style layout fits this model best: one row per source, each with its estimate, an interval (or the raw dots) and its weight, plus a final "Projection" row and a reference line at the prop. It shows both what each source says and how much it counts. Dumbbells and slope charts are for two-point comparisons. A waterfall works if the model is additive ("baseline + adjustments"), but I found no research evidence for waterfalls specifically.

### Cited Findings
- Forest plots show each study's point estimate with a horizontal CI line, marker size proportional to weight, a printed percentage weight, a pooled-estimate row and a reference line. Point estimates that are scattered with little interval overlap are the visual sign of heterogeneity, meaning pooling may be questionable. Readability tips are legible labels, stripe shading on alternate rows, and a legend when shape or color encodes meaning. — [MetricGate](https://metricgate.com/blogs/reading-a-forest-plot/); [CASRAI](https://casrai.org/guides/how-to-read-a-forest-plot)
- Under random-effects pooling, small studies gain relative weight and the pooled interval widens. This is a useful analogy for shrinking small-n sources. — [MetricGate](https://metricgate.com/blogs/reading-a-forest-plot/)
- Dumbbell charts suit exactly two values per category (about 5 to 20 categories) when the gap is the story. They should be avoided for more than two groups or when absolute values matter. Slope charts emphasize direction and fall apart beyond about 15 categories. Grouped bars are best when absolute magnitudes must be compared. — [Domo dumbbell](https://domo-webflow.domo.com/learn/charts/dumbbell-plot-chart); [Domo slope](https://domo-webflow.domo.com/learn/charts/slope-chart); [r-statistics.co](https://r-statistics.co/Dumbbell-and-Slope-Charts-in-R.html); [Desbarats via gorelik.net](https://gorelik.net/2020/11/12/the-problem-with-slope-charts-by-nick-desbarats)
- The Economist model's structure (a fundamentals prior partially pooled with polls) is the same "blend several noisy sources" idea that a contribution display needs to explain. — [HDSR](https://hdsr.mitpress.mit.edu/pub/yoa73r1m)

### Inferences
- For (c), source contributions: use one forest-style SVG with these rows:
  - Season baseline
  - Recent L5
  - H2H
  - Opponent allowed
  - **Projection** (a diamond with its interval)

  Each row shows its median as a square sized by weight, with the printed weight ("40%") and n. A vertical dashed prop line runs through all rows. This merges (b) and (c) into one chart, which matters on mobile.
- If the model is a weighted average, an alternative is a stacked "contribution" bar that splits the projection into weight × source value. Readers find this harder to read than the forest rows, so use it as a secondary detail view.
- Use a waterfall only if the model really is additive (baseline 58 yds, +6 recent form, −3 tough defense, = 61). Keep its bars few (≤5), because waterfalls read poorly as plain weights.
- A dumbbell fits a single two-way comparison, such as "player's average vs what the opponent allows". It is not right for three sources at once.
- A bullet chart (bar = projection, marker = prop line, bands = interval) is a compact summary tile for each stat in the small-multiples grid. Its bands must be explained, because readers may take them as hard limits (Wilke's deterministic-construal warning).

### Gaps
- I found no controlled studies comparing waterfall, stacked-contribution and forest layouts for lay understanding of weighted blends.
- I found no research on bullet charts with probabilistic bands.

## How should a prop line or threshold be shown clearly, including hit/miss coloring and color-blind pitfalls?

### Takeaway
The industry convention is per-game bars with a dashed line at the prop and a hit-rate summary. That is fine, but hit or miss should be encoded with more than red and green: use a blue/orange pair (or a filled/hollow distinction) plus a text label or icon. Meet WCAG 1.4.1 (color is not the only cue) and 1.4.11 (graphical objects at 3:1 contrast).

### Cited Findings
- 4for4's NFL Player Prop Stat Explorer shows bars of the player's actual stat for each game, a dashed line at the prop, a hit rate (the share of selected games over the line) and a projection bar for the upcoming week. Other apps (BetTrendz, Toad Sports) offer L5, L10 and season hit-rate toggles and opponent or home/away splits. props.cash uses a color-coded table of line, projection, difference and hit rates. — [4for4](https://www.4for4.com/2021/preseason/nfl-player-prop-stat-explorer-introduction); [props.cash newsletter](https://propsdotcash.beehiiv.com/p/propscash-newsletter-new-nba-feature); [BetTrendz listing](https://mwm.ai/apps/bettrendz/6746268287)
- Datawrapper (Lisa Charlotte Muth):
  - Blue looks nearly the same to people with normal vision and with red-green color blindness, so pair blue with orange or red.
  - Do not combine green with orange or red, or with blue of the same lightness. Red-green color-blind readers may see red and green as two shades of olive or orange.
  - Vary lightness, and test the chart in black and white.
  - Use labels, symbols, shapes, patterns or dashes so that meaning does not rely on color alone.
  — [Datawrapper colorblindness part 1](https://www.datawrapper.de/blog/colorblindness-part1); [part 2](https://www.datawrapper.de/blog/colorblindness-part2); [colorblind check](https://www.datawrapper.de/blog/colorblind-check)
- WCAG 1.4.1 (Level A): color must not be the only visual means of conveying information. WCAG 1.4.11 (Level AA): graphical objects needed to understand the content must reach 3:1 contrast against adjacent colors, which covers chart bars, lines and slices. — [Deque 1.4.11](https://dequeuniversity.com/resources/wcag2.1/1.4.11-non-text-contrast); [TabNav](https://tabnav.com/academy/wcag/success-criterion-1.4.11); [Texas State](https://doit.txst.edu/accessibility/user-guides/color-contrast.html)
- In ggdist, coloring dots by which interval they fall in (`level`) is a built-in pattern for marking dots relative to a cut point. — [ggdist vignette](https://mjskay.github.io/ggdist/articles/dotsinterval.html)

### Inferences
- For (a), the game log: draw vertical bars in date order, one per game, with the value labeled on or above the bar. Draw the prop line as a high-contrast dashed horizontal rule with its value labeled directly at the right end ("O/U 64.5"), not in a legend.
  - Over: solid fill in a saturated blue.
  - Under: a lighter orange (or a hollow outline with the same hue but different lightness).
  - Add a ✓/✗ or "O"/"U" glyph under each bar.
  - Put the headline hit rate in the title ("Over in 6 of 9 · 67%").
  - Pushes (value exactly on the line) need a third, neutral state.
- Use bars rather than a line for the game log, because games are discrete events and bars make each game's distance from the threshold easy to judge. Chart.js can do this with a bar chart, per-bar `backgroundColor` and the annotation plugin for the line. D3 or SVG gives finer control over glyphs.
- Mark the opponent games (H2H) in the log with a ring or a label rather than another color. This avoids a third hue competing with the over/under encoding.
- Check the over/under color pair against the dark-mode background as well (3:1 against the background and against each other).
- Provide a text alternative: an `aria-label` or a visually hidden table listing each game's value and its result against the line.

### Gaps
- I found no published usability research on how bettors read prop-line game logs. The conventions above come from products, not studies.

## How should small multiples for several stats (yards, receptions, TDs) work, and how do dense layouts behave on mobile?

### Takeaway
Small multiples, one panel per stat, each with its own prop line, are the standard way to show several stats. On mobile, stack the panels in one column, cut repeated axis labels, label values directly, and give each panel its own y-scale with that stated clearly. Each stat has different units, so shared scales do not apply.

### Cited Findings
- Datawrapper small multiples:
  - Layouts can be set separately for desktop and mobile, including which panels show on small screens and panel height and width.
  - Grid labels appear only in the first column by default, because repeated axis labels make panels busy.
  - Value labels are worth considering when panels have few bars.
  - A baseline line repeated in every panel aids comparison.
  — [Datawrapper small multiple column charts](https://www.datawrapper.de/blog/small-multiple-column-charts); [What to consider when creating small multiple line charts](https://www.datawrapper.de/blog/what-to-consider-when-creating-small-multiple-line-charts); [Datawrapper multiple lines](https://datawrapper.de/charts/multiple-lines)
- The CDC's COVE guidance suggests small multiples once there are more than five series, hiding the standard legend and using at most three tiles per row on desktop. — [CDC COVE](https://www.cdc.gov/cove/data-visualization-types/small-multiples.html)
- Wilke, as cited by Datawrapper: tell readers when y-axis scales differ across panels. — [Datawrapper](https://www.datawrapper.de/blog/what-to-consider-when-creating-small-multiple-line-charts)
- Kay 2016 designed quantile dotplots specifically for small mobile screens. — [UW IDL](https://idl.uw.edu/papers/when-ish-is-my-bus)

### Inferences
- Layout: build one card per stat (Rec Yds, Receptions, Rush+Rec TD). Each card holds a game-log mini bar chart with the prop rule, a one-line source summary and a 20-dot quantile dotplot with P(over). Use one column on phones and two or three on desktop. Use CSS grid plus SVG with a `viewBox` so charts scale without redrawing.
- Touchdowns are low counts (0, 1, 2) and fit a dotplot or histogram poorly. Show them as a discrete bar of probabilities (P(0), P(1), P(2+)) or as a frequency grid ("anytime TD: 38 of 100"). This is an application of frequency framing.
- Give each card an independent y-axis (the units differ), and label the axis or the values in every panel. Within one stat, keep the same x-scale across the game log, the source rows and the dotplot, so the prop line sits at a consistent position.
- Use direct labels rather than legends, and avoid hover-only information. Targets need roughly 44px or more for any tap interaction, such as an L5/L10/Season toggle. That figure is a common platform guideline and was not verified in this research.
- Avoid animation by default, and respect `prefers-reduced-motion` if HOPs are added.

### Gaps
- I found no empirical studies on small-multiple density limits on phone screens. The guidance here comes from practitioners (Datawrapper, CDC).
- I did not verify the 44px touch-target number against Apple or WCAG 2.5.5 sources during this research.
