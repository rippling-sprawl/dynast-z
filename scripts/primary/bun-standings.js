/*
  Baker's Buns — Projected 2026 Standings.

  The Board argues the model against a price one team at a time. This does the
  other thing the model has never been asked to do: play it. Every team's
  seventeen games are simulated, the wins are counted, and the conference is
  ordered the way January orders it — four division winners, three wild cards,
  and everybody else.

  The point of the exercise is the compression. The model's #1 team is #1 by a
  distance that looks decisive in a ranked list and is not decisive at all in a
  football game, and a ranking has no way of saying so. A schedule does. Denver
  opens roughly four and a half points better than an average opponent; four and
  a half points wins about 62% of the time against a 14-point margin, so the
  best team in the model projects to eleven or twelve wins and not to seventeen.
  The same arithmetic run at the other end is why the worst team in the model
  still projects to four or five: a team eight points worse than the field still
  wins a quarter of its games, and it plays some of the field's worst teams.

  --- five decisions, each of which could have gone the other way ---

  1. STRENGTH OF SCHEDULE COMES OUT OF THE RATING. The composite scored in the
     table has an SoS input in it, weighted 15%. Here the schedule is being
     played rather than summarized, so leaving SoS in the rating would count it
     twice — once as a number attached to the team, once as the opponents it
     actually draws. So the rating is built from the composite's team-quality
     inputs only, with SoS dropped and the rest renormalized to sum to 1. Every
     other input stays, including Rest, which the simulation has no other way to
     see: this plays a schedule of opponents, not of body clocks.

     A consequence worth naming: the SoS column and this table can disagree
     about who has it easy, because the sheet's SoS is built off the market's
     win totals and this one is built off the model's own ratings. That is the
     model being made to answer for itself, which is the point.

  2. THE SCALE IS CALIBRATED TO HISTORY, NOT TO THE SPREAD OF THE SCORES. A
     composite z-score has no units, so something has to say how many points of
     football one unit of it is worth. Reading that off the scores themselves
     would make the answer depend on the blend — a reader who pushes one slider
     to 100% would get a league that spreads differently, which is not something
     re-weighting an opinion should do. So the ratings are standardized to the
     field first and then scaled by a constant chosen so that a simulated season
     scatters the way real ones do. The model says who is better; twenty-seven
     seasons of results say how far apart thirty-two NFL teams actually finish.

  3. THE ERROR TERM IS THE INJURY TERM, AND HALF OF IT ARRIVES AFTER KICKOFF.
     Each team's rating carries an error the model cannot see, in two pieces: a
     fixed one drawn before the season, for being wrong in August, and a random
     walk that accumulates week by week, for going wrong during it. This is the
     one thing a preseason number is structurally unable to have an opinion
     about — which quarterback tears something in October — and it is also what
     stops the table being overconfident: without it a 4-point favourite is a
     4-point favourite in all seventeen games of all six thousand seasons, and
     the division odds come out far harder than any August forecast has earned.

     The walk is not decoration. Sorted by the prior season's margin, teams do
     not fan out as the year goes on — the bad ones average -3.47 a game in the
     first third and -2.82 in the last, which is if anything a drift back toward
     the field. What does fan out is the league as observed: the spread of
     margin per game across the thirty-two runs 7.52, 8.02, 8.35 across the
     three thirds of a season. Teams separate late along an axis nobody could
     see in August, which is a walk that accumulates and not an offset fixed in
     advance. With it the simulation reproduces the same widening (8.5, 9.0,
     9.2) instead of holding flat, and a team the model got wrong in September
     stays wrong through December rather than being re-rolled each week.

  4. THE SEEDING IS RUN OFF PROJECTED WINS, THE PERCENTAGES OFF THE SIMULATION.
     The two are different questions and the table prints both. Where a team is
     placed is the model's single best guess, which is its mean; how sure the
     model is comes from how often the simulation actually put it there. That is
     why a 1-seed can carry a 48% division number, and why the two columns are
     side by side rather than one of them being left off. Nothing in the top
     block is above 70% to make the playoffs, and that is the honest reading.

  5. THE PERCENTAGES ARE PRINTED AGAINST A PRICE. Both of them carry the gap
     between this simulation and the books' de-vigged number for the same
     event, which is the one figure in the section that is about neither the
     model nor the market on its own. It is what turns a 41% division line from
     a fact into a position: the model is only interesting where it disagrees,
     and a column of percentages with nothing to be measured against gives a
     reader no way to see where that is.

     It is a difference in points and not a ratio, and it is colored against
     the widest disagreement in its own column rather than across both. Why,
     for each, is at edgeTag() and at the edgeMax block below.

  --- the constants, and where each one came from ---

  All four are measured off nflverse's regular-season game results, 1999-2025 —
  raw scores, not anybody's projections:

    HFA        2.0 pts   mean home margin, 2021-2025 (2.06; it was 2.40 through
                         2019, and the drop is real and league-wide)
    MARGIN_SD  14.2 pts  SD of home margin, 2015-2025 (14.18)
    RATING_SD  4.6 pts   the spread of preseason team quality, chosen below
    DRIFT_SD   4.0 pts   the scale of the error above, chosen below

  The last two are not measured directly — no box score contains them — so they
  are fitted to two things that are. Across the five 17-game seasons, team wins
  within a season have an SD of 3.12, and a preseason forecast correlates with
  final wins somewhere around 0.6. Those two facts pin the pair: RATING_SD sets
  how far apart the projections are, DRIFT_SD how much of the rest of a season's
  spread arrives after kickoff. At 4.6 and 4.0 a simulated league lands on a
  realized win SD of 3.12 and a projection-to-outcome correlation of 0.62.

  There is a third check the page prints, and it is the one worth quoting at
  anybody who finds the column too tight: the thirty-two projections here spread
  1.94 wins, and the thirty-two win totals the books have actually hung — which
  the projections table prints two sections up — spread 1.94. The range is
  4.6-11.6 against a posted 4.5-11.5. This is not a cautious forecast; it is the
  same width the market is charging money at.

  DRIFT_SD is split evenly in variance between the two pieces: the fixed part
  gets DRIFT_SD/sqrt(2) and the walk ends the season at DRIFT_SD, so the average
  uncertainty over a season is DRIFT_SD either way and only its timing changes.
  A team is 0.7 x DRIFT_SD from its August rating in week 1 and 1.2 x by week 18.

  Ties are not modelled. A margin drawn from a continuous distribution is never
  exactly zero, and the league has averaged well under one tie a season.
*/
(function (global) {
  'use strict';

  var SEASON = 2026;
  var GAMES = 17;

  var HFA = 2.0;
  var MARGIN_SD = 14.2;
  var RATING_SD = 4.6;
  var DRIFT_SD = 4.0;

  /* The two halves of DRIFT_SD. PRE_SD is fixed for the season — the model was
   * wrong in August. WALK_SD is the weekly step of the random walk on top of
   * it, scaled so the walk's own SD reaches DRIFT_SD by the final week. Both
   * derived rather than typed, so moving DRIFT_SD moves them together. */
  var PRE_SD = DRIFT_SD / Math.SQRT2;
  var WALK_SD = DRIFT_SD / Math.sqrt(GAMES + 1);

  // Total drift variance a game in week `wk` is decided under: the fixed part,
  // plus the walk's variance after wk steps. Both teams carry one, independent,
  // hence the 2x wherever this feeds a margin.
  function driftVar(wk) {
    return PRE_SD * PRE_SD + wk * WALK_SD * WALK_SD;
  }

  /* Six thousand seasons. The standard error on a 50% division number is 0.6
   * of a percentage point, which is under the rounding the table prints it at,
   * and the whole run is ~1.6M coin flips — tens of milliseconds, once, on the
   * same pass that draws The Board. */
  var SIMS = 6000;

  /* What a real 17-game season's wins spread by, across the field, mean of
   * 2021-2025 (2.84, 3.01, 2.70, 3.65, 3.41). It is not an input to anything —
   * RATING_SD and DRIFT_SD were fitted to it — so it is carried here only so
   * the note can print the check rather than the page asserting the fit. */
  var REAL_WIN_SD = 3.12;

  /* Half a point of probability. Two numbers that round to the same percent
   * are not a disagreement, so anything inside this prints grey rather than
   * claiming a direction the rounding cannot support. */
  var EDGE_FLAT = 0.005;

  var DIV_ORDER = ['East', 'North', 'South', 'West'];
  var CONFS = ['AFC', 'NFC'];
  var LOGO_DIR = '/assets/icons/nfl/';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  /* ---------- the arithmetic ----------
   * Φ, by Abramowitz & Stegun 26.2.17. Accurate to 7.5e-8, which is six digits
   * more than a win probability is ever printed to, and it avoids pulling in an
   * erf implementation for the one place this file needs one.
   */
  function ncdf(x) {
    var t = 1 / (1 + 0.2316419 * Math.abs(x));
    var d = 0.3989422804014327 * Math.exp(-x * x / 2);
    var p = d * t * (0.31938153 + t * (-0.356563782 + t * (1.781477937 +
      t * (-1.821255978 + t * 1.330274429))));
    return x >= 0 ? 1 - p : p;
  }

  /* xorshift128, seeded by a constant. Determinism is not a nicety here: two
   * loads of the same page showing Baltimore at 33% and then 34% would read as
   * the number being soft when what is soft is the estimator, and a reader
   * comparing a screenshot to the page would be comparing two samples. */
  function rng() {
    var x = 123456789, y = 362436069, z = 521288629, w = 88675123;
    return function () {
      var t = x ^ (x << 11);
      x = y; y = z; z = w;
      w = (w ^ (w >>> 19)) ^ (t ^ (t >>> 8));
      return (w >>> 0) / 4294967296;
    };
  }

  /* Box-Muller, keeping the second of each pair. Halves the transcendental
   * calls, which is the whole cost of the run. */
  function gauss(rand) {
    var spare = null;
    return function () {
      if (spare !== null) { var s = spare; spare = null; return s; }
      var u, v, r;
      do {
        u = rand() * 2 - 1;
        v = rand() * 2 - 1;
        r = u * u + v * v;
      } while (r === 0 || r >= 1);
      var f = Math.sqrt(-2 * Math.log(r) / r);
      spare = v * f;
      return u * f;
    };
  }

  /* ---------- the price ----------
   * The two of The Board's five markets that price exactly what these tables
   * print. A win total is a line rather than a probability, and nothing here
   * forecasts a conference or a Super Bowl, so those three have no column to
   * sit beside and are not read.
   *
   * `ok` is honoured rather than merely `value`: a market the feed could not
   * fill comes back with a handful of teams in it, and an edge printed for six
   * clubs and blank for twenty-six would read as the model agreeing with the
   * price everywhere it says nothing.
   */
  function priced(markets, key) {
    var m = (markets || []).filter(function (x) { return x.key === key; })[0];
    return m && m.ok ? m.value : null;
  }

  /* ---------- the rating ----------
   * Composite minus SoS, renormalized, standardized over the thirty-two, then
   * scaled into points. Standardizing before scaling is decision 2 in the file
   * comment: it is what makes the league's spread a property of the league and
   * not of the reader's slider positions.
   */
  function ratings(teams, weights) {
    var keys = [], total = 0;
    Object.keys(weights || {}).forEach(function (k) {
      if (k === 'sos' || !weights[k]) return;
      keys.push(k);
      total += weights[k];
    });
    if (!keys.length || !total) return null;

    var raw = {}, sum = 0;
    teams.forEach(function (t) {
      var v = 0;
      keys.forEach(function (k) { v += weights[k] * ((t.z || {})[k] || 0); });
      raw[t.abbr] = v / total;
      sum += raw[t.abbr];
    });

    var mean = sum / teams.length, ss = 0;
    teams.forEach(function (t) { ss += (raw[t.abbr] - mean) * (raw[t.abbr] - mean); });
    var sd = Math.sqrt(ss / teams.length) || 1;

    var out = {};
    teams.forEach(function (t) { out[t.abbr] = RATING_SD * (raw[t.abbr] - mean) / sd; });
    return out;
  }

  /* Every regular-season game as [away, home, hfa, week]. A neutral-site game —
   * this schedule has three, Melbourne and two in London — carries no home
   * edge, and the flag is honoured rather than ignored because it is worth two
   * thirds of a win to whoever was nominally at home.
   *
   * The week is carried because the drift now depends on it: a week 2 game is
   * decided much closer to the August rating than a week 17 game is. */
  function fixtures(doc) {
    var out = [];
    (doc.weeks || []).forEach(function (w) {
      (w.games || []).forEach(function (g) {
        if (!g.away || !g.home) return;
        out.push([g.away, g.home, g.neutral ? 0 : HFA, w.week || 1]);
      });
    });
    return out;
  }

  /* Projected wins, in closed form rather than off the simulation.
   *
   * The drift is Gaussian and enters the margin linearly, so averaging over it
   * is the same as widening the margin: the two teams' independent errors add
   * 2·driftVar(week) to the variance that game is decided by. Widening, and not
   * a correction to the mean — which is why the projections barely moved when
   * the walk replaced a flat season-long offset, while the seasons around them
   * changed shape. That makes the expectation exact, which the simulation's
   * mean is not: its standard error would be about four hundredths of a win,
   * and a division race decided at one decimal place should not turn on the
   * seed. */
  function projected(rating, games) {
    var wins = {};
    Object.keys(rating).forEach(function (a) { wins[a] = 0; });
    games.forEach(function (g) {
      if (rating[g[0]] == null || rating[g[1]] == null) return;
      var eff = Math.sqrt(MARGIN_SD * MARGIN_SD + 2 * driftVar(g[3]));
      var p = ncdf((rating[g[1]] - rating[g[0]] + g[2]) / eff);
      wins[g[1]] += p;
      wins[g[0]] += 1 - p;
    });
    return wins;
  }

  /* Six thousand seasons, counting three things per team: how often it won its
   * division, how often it reached the field of seven, and the shape of its win
   * distribution.
   *
   * Ties in the standings are broken the way the league breaks them, as far as
   * a simulation this coarse can: division record, then conference record, then
   * a coin. Rating is deliberately not a tiebreaker — it would hand every tie
   * to the better team and quietly turn a 50/50 division into a 60/40 one. */
  function simulate(teams, rating, games, seed) {
    var rand = seed || rng();
    var norm = gauss(rand);
    var abbrs = teams.map(function (t) { return t.abbr; });
    var n = abbrs.length;
    var idx = {}, conf = [], div = [];
    abbrs.forEach(function (a, i) { idx[a] = i; });
    teams.forEach(function (t, i) { conf[i] = t.conf; div[i] = t.conf + ' ' + t.div; });

    // Fixtures resolved to indices once, so the inner loop is array reads.
    var fx = [];
    games.forEach(function (g) {
      if (idx[g[0]] == null || idx[g[1]] == null) return;
      fx.push([idx[g[0]], idx[g[1]], g[3], rating[g[1]] - rating[g[0]] + g[2]]);
    });
    // The schedule file is already in week order, but the walk depends on that
    // being true rather than merely likely.
    fx.sort(function (a, b) { return a[2] - b[2]; });
    var sameDiv = fx.map(function (g) { return div[g[0]] === div[g[1]]; });
    var sameConf = fx.map(function (g) { return conf[g[0]] === conf[g[1]]; });

    var divisions = {}, conferences = {};
    teams.forEach(function (t, i) {
      (divisions[div[i]] = divisions[div[i]] || []).push(i);
      (conferences[t.conf] = conferences[t.conf] || []).push(i);
    });

    var wonDiv = new Float64Array(n);
    var madePlayoffs = new Float64Array(n);
    var hist = [];
    for (var h = 0; h < n; h++) hist.push(new Float64Array(GAMES + 1));

    var w = new Int32Array(n), dw = new Int32Array(n), cw = new Int32Array(n);
    var drift = new Float64Array(n), tiebreak = new Float64Array(n);

    /* Better of the two, by wins then division record then conference record
     * then the coin this season drew for them. Hoisted out of the season loop
     * because it closes over the counters rather than over the season: the
     * arrays are reused, so one function serves all six thousand. */
    function better(x, y) {
      if (w[x] !== w[y]) return w[x] > w[y] ? x : y;
      if (dw[x] !== dw[y]) return dw[x] > dw[y] ? x : y;
      if (cw[x] !== cw[y]) return cw[x] > cw[y] ? x : y;
      return tiebreak[x] > tiebreak[y] ? x : y;
    }

    for (var s = 0; s < SIMS; s++) {
      for (var i = 0; i < n; i++) {
        w[i] = 0; dw[i] = 0; cw[i] = 0;
        // Where August already had it wrong. Fixed for this whole season.
        drift[i] = norm() * PRE_SD;
        tiebreak[i] = rand();
      }
      var week = 0;
      for (var g = 0; g < fx.length; g++) {
        var f = fx[g], a = f[0], b = f[1];
        // One step of the walk per team at the top of each new week, so a team
        // that goes wrong in October is still wrong in December rather than
        // being re-rolled game by game.
        if (f[2] !== week) {
          week = f[2];
          for (var q = 0; q < n; q++) drift[q] += norm() * WALK_SD;
        }
        var winner = (f[3] + drift[b] - drift[a] + norm() * MARGIN_SD) > 0 ? b : a;
        w[winner]++;
        if (sameConf[g]) {
          cw[winner]++;
          if (sameDiv[g]) dw[winner]++;
        }
      }
      for (var t2 = 0; t2 < n; t2++) hist[t2][w[t2]]++;

      for (var c = 0; c < CONFS.length; c++) {
        var members = conferences[CONFS[c]] || [];
        var champs = [];
        for (var d = 0; d < DIV_ORDER.length; d++) {
          var grp = divisions[CONFS[c] + ' ' + DIV_ORDER[d]] || [];
          if (!grp.length) continue;
          var top = grp[0];
          for (var k = 1; k < grp.length; k++) top = better(top, grp[k]);
          champs.push(top);
          wonDiv[top]++;
          madePlayoffs[top]++;
        }
        // The three wild cards: the best of the conference minus its champions.
        // A partial sort, because only the top three of nine are wanted.
        var pool = [];
        for (var m = 0; m < members.length; m++) {
          if (champs.indexOf(members[m]) === -1) pool.push(members[m]);
        }
        for (var slot = 0; slot < 3 && slot < pool.length; slot++) {
          var best = slot;
          for (var p = slot + 1; p < pool.length; p++) {
            if (better(pool[p], pool[best]) === pool[p]) best = p;
          }
          var swap = pool[slot]; pool[slot] = pool[best]; pool[best] = swap;
          madePlayoffs[pool[slot]]++;
        }
      }
    }

    /* The spread the simulated seasons actually came out at, which is the
     * calibration's one falsifiable claim and so is measured here rather than
     * quoted from the constant it was fitted to.
     *
     * Pooling every team-season together is exact rather than approximate: each
     * simulated season hands out 272 wins to 32 teams, so its mean is 8.5 every
     * time, and a pooled variance around a mean that never moves is the average
     * of the within-season variances. */
    var mean = fx.length / n;   // 272 games shared by 32 teams: 8.5, every season
    var ss = 0;
    for (var t3 = 0; t3 < n; t3++) {
      for (var wq = 0; wq <= GAMES; wq++) {
        ss += hist[t3][wq] * (wq - mean) * (wq - mean);
      }
    }
    var realized = Math.sqrt(ss / (n * SIMS));

    var out = { _realized: realized };
    abbrs.forEach(function (a, i) {
      out[a] = {
        div: wonDiv[i] / SIMS,
        playoff: madePlayoffs[i] / SIMS,
        lo: quantile(hist[i], 0.1),
        hi: quantile(hist[i], 0.9)
      };
    });
    return out;
  }

  /* Writes a 1-based rank onto every team's slice, ordered by `by` ascending.
   * Three fields need one and none of them is stored anywhere, so ranking is a
   * pass over the same object rather than three parallel sorted arrays. */
  function rankInto(byTeam, field, by) {
    Object.keys(byTeam).sort(function (a, b) { return by(byTeam[a]) - by(byTeam[b]); })
      .forEach(function (a, i) { byTeam[a][field] = i + 1; });
  }

  // The win count at which the cumulative share of seasons first passes p.
  function quantile(counts, p) {
    var need = SIMS * p, run = 0;
    for (var i = 0; i < counts.length; i++) {
      run += counts[i];
      if (run >= need) return i;
    }
    return counts.length - 1;
  }

  /* ---------- the forecast ----------
   * One object per team, keyed by abbr, and the league-level checks the note
   * prints. Returns null when there is nothing to forecast off, which is what a
   * schedule file that did not load looks like from here.
   */
  function forecast(teams, doc, weights, markets) {
    if (!teams || !teams.length || !doc) return null;
    var rating = ratings(teams, weights);
    if (!rating) return null;
    var games = fixtures(doc);
    if (!games.length) return null;

    // The two prices the percentage columns get to be argued with. Absent
    // markets are absent edges and nothing else — the tables are the model's
    // forecast first, and they print in full whether or not a book agrees.
    var mktDiv = priced(markets, 'division');
    var mktPo = priced(markets, 'playoffs');

    var wins = projected(rating, games);
    var sim = simulate(teams, rating, games);

    /* The model's own strength of schedule: the mean rating of the seventeen
     * opponents a team actually draws. This is the number that replaced the
     * sheet's SoS input, so it is the one that has to be printed when the two
     * disagree — see the read-out below the tables. */
    var opp = {}, oppN = {};
    teams.forEach(function (t) { opp[t.abbr] = 0; oppN[t.abbr] = 0; });
    games.forEach(function (g) {
      if (rating[g[0]] == null || rating[g[1]] == null) return;
      opp[g[1]] += rating[g[0]]; oppN[g[1]]++;
      opp[g[0]] += rating[g[1]]; oppN[g[0]]++;
    });

    // The composite as the table prints it, SoS included — the Rank column, in
    // other words, recomputed here rather than read off `score`, because a
    // reader's own weights have to move it exactly as they move the table's.
    var composite = {};
    teams.forEach(function (t) {
      var v = 0;
      Object.keys(weights).forEach(function (k) { v += weights[k] * ((t.z || {})[k] || 0); });
      composite[t.abbr] = v;
    });

    var byTeam = {}, sum = 0, ss = 0;
    teams.forEach(function (t) {
      var w = wins[t.abbr];
      byTeam[t.abbr] = {
        rating: rating[t.abbr],
        wins: w,
        losses: GAMES - w,
        div: sim[t.abbr].div,
        playoff: sim[t.abbr].playoff,
        // The market's own number for the same two events, and the gap. Both
        // the price and the difference are carried: the tables print the gap
        // and the cell's title prints the price it came from, because a
        // difference with neither of its two inputs beside it is not checkable.
        mktDiv: mktDiv ? mktDiv[t.abbr] : null,
        mktPlayoff: mktPo ? mktPo[t.abbr] : null,
        edgeDiv: mktDiv && mktDiv[t.abbr] != null ? sim[t.abbr].div - mktDiv[t.abbr] : null,
        edgePlayoff: mktPo && mktPo[t.abbr] != null
          ? sim[t.abbr].playoff - mktPo[t.abbr] : null,
        lo: sim[t.abbr].lo,
        hi: sim[t.abbr].hi,
        composite: composite[t.abbr],
        oppRating: oppN[t.abbr] ? opp[t.abbr] / oppN[t.abbr] : 0,
        sheetSos: (t.raw || {}).sosRank
      };
      sum += w;
    });

    // Rank 1 is the best team, the easiest schedule, the most wins.
    rankInto(byTeam, 'compRank', function (f) { return -f.composite; });
    rankInto(byTeam, 'winsRank', function (f) { return -f.wins; });
    rankInto(byTeam, 'oppRank', function (f) { return f.oppRating; });
    var mean = sum / teams.length;
    teams.forEach(function (t) { ss += Math.pow(byTeam[t.abbr].wins - mean, 2); });

    /* The one comparison that answers "is this column too tight" without an
     * appeal to anybody's judgement: the books have hung a win total on all
     * thirty-two of these teams, the projections table prints them two sections
     * up, and the question is only whether these numbers spread as wide as
     * those do. Skipped if the feed is short — a partial field has a different
     * spread for reasons that have nothing to do with this model. */
    var posted = teams.map(function (t) { return (t.odds || {}).winTotal; })
      .filter(function (v) { return typeof v === 'number'; });
    var market = null;
    if (posted.length === teams.length) {
      var pm = posted.reduce(function (a, b) { return a + b; }, 0) / posted.length;
      var pss = posted.reduce(function (a, b) { return a + (b - pm) * (b - pm); }, 0);
      market = {
        spread: Math.sqrt(pss / posted.length),
        lo: Math.min.apply(null, posted),
        hi: Math.max.apply(null, posted)
      };
    }

    var allWins = teams.map(function (t) { return byTeam[t.abbr].wins; });

    /* One heat scale per percentage column, not one shared between them. The
     * two disagreements are nothing like the same size — a division is a
     * four-way market the model can be thirty points off in, a playoff berth is
     * a fourteen-of-thirty-two market where the ends of the field are already
     * settled and the argument is over the middle — so a shared scale would
     * print the whole Playoffs column pale and say the model has no opinion
     * about it. Each column is colored against its own widest disagreement,
     * which is what makes the color a read within the column it is in. */
    var edgeMax = { div: 0, playoff: 0 };
    teams.forEach(function (t) {
      var f = byTeam[t.abbr];
      if (f.edgeDiv != null) edgeMax.div = Math.max(edgeMax.div, Math.abs(f.edgeDiv));
      if (f.edgePlayoff != null) {
        edgeMax.playoff = Math.max(edgeMax.playoff, Math.abs(f.edgePlayoff));
      }
    });

    return {
      market: market,
      edgeMax: edgeMax,
      lo: Math.min.apply(null, allWins),
      hi: Math.max.apply(null, allWins),
      teams: byTeam,
      games: games.length,
      sims: SIMS,
      // 272 games is 272 wins; the column has to add up to it or the schedule
      // was read wrong, and the note prints it rather than trusting it.
      totalWins: sum,
      spread: Math.sqrt(ss / teams.length),
      realized: sim._realized,
      hfa: HFA,
      marginSd: MARGIN_SD,
      ratingSd: RATING_SD,
      driftSd: DRIFT_SD
    };
  }

  /* ---------- the seeding ----------
   * Division winners first, four of them, ordered by wins; then the best three
   * left in the conference; then everybody else. Ordering is on the unrounded
   * projection throughout, so two teams printed at 8.8 still have an order and
   * it is the one the numbers behind the print actually have.
   */
  function seedConference(teams, fc, conf) {
    var field = teams.filter(function (t) { return t.conf === conf; });
    var wins = function (t) { return fc.teams[t.abbr].wins; };
    var byWins = function (a, b) { return wins(b) - wins(a); };

    var champs = [];
    DIV_ORDER.forEach(function (d) {
      var grp = field.filter(function (t) { return t.div === d; }).sort(byWins);
      if (grp.length) champs.push(grp[0]);
    });
    champs.sort(byWins);

    var rest = field.filter(function (t) { return champs.indexOf(t) === -1; }).sort(byWins);
    return { champs: champs, wilds: rest.slice(0, 3), out: rest.slice(3) };
  }

  /* ---------- rendering ---------- */

  function logo(t) {
    return '<img class="ps-logo" src="' + LOGO_DIR + esc(t.abbr) + '.svg" alt="" aria-hidden="true" loading="lazy">';
  }

  function pct(v) {
    // Never 0% or 100%: every team in the simulation both made and missed at
    // least once, and rounding a 0.4% away would say something the run does not.
    var p = v * 100;
    if (p > 0 && p < 1) return '<1%';
    if (p < 100 && p > 99) return '>99%';
    return Math.round(p) + '%';
  }

  /* 0 where the model and the price agree, 1 at the widest disagreement in
   * that column, on the same curve the projections table's own heat map uses
   * (see heat() in bakers-buns.html). The exponent is what makes it a column
   * and not two colors: on a straight ratio one Detroit-sized disagreement
   * washes the other thirty-one out to grey, and the middle of the field is
   * where most of the argument actually is. */
  function heat(v, max) {
    return (0.12 + 0.88 * Math.pow(Math.min(1, Math.abs(v) / (max || 1)), 0.7)).toFixed(3);
  }

  /* The model minus the price, in points of probability, printed beside the
   * percentage it belongs to. Always signed and with a real minus rather than
   * a hyphen, because the sign is the entire read and it is being set at nine
   * and a half pixels.
   *
   * Points and not a ratio. "The model is 12 points higher" is a statement a
   * reader can carry back to the two percentages either side of it; "31%
   * higher" is a number about the price rather than about the team, and it
   * explodes at exactly the end of the field where the price is smallest and
   * least worth arguing with.
   *
   * A team the market did not price gets the span anyway, empty. The tag is a
   * fixed width in a right-aligned cell precisely so the percentages beside it
   * line up down the table, and omitting it for one row would let that row's
   * percentage slide right into the gap — the one place the alignment is most
   * visible is exactly where it would break. */
  function edgeTag(v, max) {
    if (v == null) return max ? '<span class="ps-edge"></span>' : '';
    var cls = v > EDGE_FLAT ? 'pos' : (v < -EDGE_FLAT ? 'neg' : 'flat');
    var pp = Math.round(v * 100);
    var txt = pp > 0 ? '+' + pp : (pp < 0 ? '\u2212' + Math.abs(pp) : '0');
    return '<span class="ps-edge ' + cls + '" style="--heat:' + heat(v, max) + '">' +
      txt + '</span>';
  }

  /* A percentage cell: the simulation's number, then the market's disagreement
   * with it. The price itself goes in the title rather than in a third column —
   * the tables are already five columns in a half-width grid, and the number a
   * reader wants at a glance is the gap, not the two sides of it. */
  function pctCell(model, mkt, max, what, cls) {
    var e = mkt == null ? null : model - mkt;
    return '<td class="num ps-pct' + (cls ? ' ' + cls : '') + '"' +
      (mkt == null ? '' : ' title="Market: ' + pct(mkt) + ' ' + what + '"') + '>' +
      pct(model) + edgeTag(e, max) + '</td>';
  }

  function row(t, fc, seedNo, cls) {
    var f = fc.teams[t.abbr];
    var range = f.lo + '–' + f.hi;
    return '<tr class="ps-row' + (cls ? ' ' + cls : '') + '">' +
      '<td class="ps-seed">' + (seedNo ? seedNo : '') + '</td>' +
      // The flex row is a span inside the cell rather than the cell itself.
      // A <td> set to display:flex stops being a table cell, which takes it out
      // of the table's border collapsing — its rules then paint on its own box
      // edge instead of astride the shared gridline, and the section's two
      // dividers arrive a pixel or two out of line with the rest of the row.
      '<td class="ps-team"><span class="ps-team-in">' + logo(t) +
        '<span class="ps-label">' +
          '<span class="ps-name">' + esc(t.short || t.team) + '</span>' +
          (seedNo && seedNo <= 4 ? '<span class="ps-div">' + esc(t.div) + '</span>' : '') +
        '</span>' +
      '</span></td>' +
      '<td class="num ps-rec" title="8 in 10 simulated seasons land between ' +
        range + ' wins">' + f.wins.toFixed(1) + '</td>' +
      pctCell(f.div, f.mktDiv, fc.edgeMax.div, 'to win the division', '') +
      pctCell(f.playoff, f.mktPlayoff, fc.edgeMax.playoff, 'to make the playoffs', 'is-po') +
    '</tr>';
  }

  /* The sub-label only appears where there is a price to be against. An
   * outrights feed that did not arrive costs the Div % column its edge, and a
   * header still promising one over an empty column would read as the model
   * agreeing with a book that never spoke. */
  function edgeHead(max) {
    return max ? '<span class="th-sub">vs market</span>' : '';
  }

  function table(teams, fc, conf) {
    var s = seedConference(teams, fc, conf);
    var rows = '';
    s.champs.forEach(function (t, i) { rows += row(t, fc, i + 1, ''); });
    s.wilds.forEach(function (t, i) { rows += row(t, fc, i + 5, i === 0 ? 'is-wildcard' : ''); });
    s.out.forEach(function (t, i) { rows += row(t, fc, 0, i === 0 ? 'is-cut' : ''); });

    return '<div class="ps-conf">' +
      '<table class="bun-table ps-table">' +
        '<caption>' + esc(conf) + '</caption>' +
        '<thead><tr>' +
          '<th scope="col" class="ps-seed"><span class="sr-only">Seed</span></th>' +
          '<th scope="col">Team</th>' +
          '<th scope="col" class="num">Wins</th>' +
          '<th scope="col" class="num">Div %' + edgeHead(fc.edgeMax.div) + '</th>' +
          '<th scope="col" class="num">Playoffs %' + edgeHead(fc.edgeMax.playoff) +
            '</th>' +
        '</tr></thead>' +
        '<tbody>' + rows + '</tbody>' +
      '</table>' +
    '</div>';
  }

  function ord(n) {
    var s2 = ['th', 'st', 'nd', 'rd'], v = n % 100;
    return n + (s2[(v - 20) % 10] || s2[v] || s2[0]);
  }

  /* ---------- rank vs finish ----------
   * The read-out this section turned out to need. A team's place in the Rank
   * column and its place in these tables are not the same number, and when they
   * differ by half a conference the reader is owed the reason rather than left
   * to notice it.
   *
   * The reason is always the schedule, and it is always the same disagreement:
   * the Rank column's SoS input is built off the market's win totals, and this
   * section replaced it with the mean rating of the seventeen opponents the
   * model itself thinks a team drew. Where the model likes a team's division
   * more than the market does, the sheet's easy schedule stops being easy.
   *
   * Detroit is the case that makes it worth printing. Three quarters of their
   * composite is the SoS input alone — the sheet has them 1st, the softest
   * schedule in football, and everything else about them grades out mid-table.
   * Play the model's own opponents and that schedule is ordinary, because the
   * model is far higher on Chicago and Minnesota than the market is and Detroit
   * draws both twice.
   *
   * Moves of one place are dropped: a place is worth about a tenth of a win in
   * the middle of the field and the ordering there is not that sure of itself.
   */
  var MOVE_MIN = 2;
  var MOVE_MAX = 5;

  function movers(teams, fc, dir) {
    return teams.slice()
      .map(function (t) {
        var f = fc.teams[t.abbr];
        return { t: t, f: f, move: f.compRank - f.winsRank };
      })
      .filter(function (m) { return dir * m.move >= MOVE_MIN; })
      .sort(function (a, b) { return dir * (b.move - a.move); })
      .slice(0, MOVE_MAX);
  }

  function moverList(list, cls) {
    return '<ul class="board-list ' + cls + '">' + list.map(function (m) {
      return '<li>' +
        '<img src="' + LOGO_DIR + esc(m.t.abbr) + '.svg" alt="" aria-hidden="true">' +
        '<span class="board-abbr">' + esc(m.t.abbr) + '</span>' +
        '<span class="board-mkt ps-move-from">' + ord(m.f.compRank) + ' &rarr; ' +
          ord(m.f.winsRank) + '</span>' +
        '<span class="board-resid">' + (m.move > 0 ? '+' : '\u2212') +
          Math.abs(m.move) + '</span>' +
      '</li>';
    }).join('') + '</ul>';
  }

  /* The lede for each list, written off the team at the top of it, so the
   * sentence names whoever the schedule actually moved this time rather than
   * whoever it moved when this was written. */
  function moverLede(m, harder) {
    if (!m) return 'Nothing moved more than a place.';
    var name = esc(m.t.short || m.t.team);
    var sheet = m.f.sheetSos == null ? null : ord(m.f.sheetSos);
    var mine = ord(m.f.oppRank);
    return name + ' rank ' + ord(m.f.compRank) + ' on the score and finish ' +
      ord(m.f.winsRank) + ' here' +
      (sheet ? ', because the sheet has their schedule ' + sheet + ' and the model&rsquo;s own ' +
        'ratings of the same seventeen opponents have it ' + mine : '') +
      '. ' + (harder
        ? 'A team the market thinks has it easy, in a division this model rates highly.'
        : 'A team the market thinks has it hard, against opponents this model rates lower.');
  }

  function reads(teams, fc) {
    var down = movers(teams, fc, -1);
    var up = movers(teams, fc, 1);
    if (!down.length && !up.length) return '';
    return '<div class="board-reads ps-reads">' +
      '<div class="board-read is-under">' +
        '<h4>The schedule takes away</h4>' +
        '<p>' + moverLede(down[0], true) + '</p>' +
        moverList(down, 'is-under') +
      '</div>' +
      '<div class="board-read is-over">' +
        '<h4>and gives back</h4>' +
        '<p>' + moverLede(up[0], false) + '</p>' +
        moverList(up, 'is-over') +
      '</div>' +
    '</div>';
  }

  /* The note, computed for the same reason every other note on this page is:
   * it quotes the model's own best team back at itself, and that team changes
   * the moment a reader moves a slider. */
  function note(teams, fc) {
    var best = teams.slice().sort(function (a, b) {
      return fc.teams[b.abbr].wins - fc.teams[a.abbr].wins;
    })[0];
    var worst = teams.slice().sort(function (a, b) {
      return fc.teams[a.abbr].wins - fc.teams[b.abbr].wins;
    })[0];
    var b = fc.teams[best.abbr], w = fc.teams[worst.abbr];
    // Against an average opponent on a neutral field, at mid-season noise.
    var edge = ncdf(b.rating / Math.sqrt(fc.marginSd * fc.marginSd + 2 * driftVar(GAMES / 2)));

    return 'Each team&rsquo;s seventeen games played ' + fc.sims.toLocaleString() +
      ' times. Home field is worth ' + fc.hfa.toFixed(1) + ' points and a margin scatters ' +
      fc.marginSd.toFixed(1) + ' around it, both measured off 1999&ndash;2025 results rather ' +
      'than projected by anyone. Every rating carries a ' + fc.driftSd.toFixed(1) +
      '-point error the model cannot see &mdash; part of it fixed before kickoff, the rest ' +
      'arriving week by week, which is what makes the field spread out through December the ' +
      'way real ones do. Strength of schedule is dropped from the rating because the schedule ' +
      'is being played rather than summarized. That is why the team this projects highest, ' +
      esc(best.team) + ', lands on ' + b.wins.toFixed(1) + ' wins and not 17: ' +
      b.rating.toFixed(1) + ' points of edge makes them a ' + Math.round(edge * 100) +
      '% favourite in a game, which over seventeen of them is a very good season ' +
      'and not an unbeaten one. ' + esc(worst.team) + ' sit at ' +
      w.wins.toFixed(1) + ' for the same reason read from the other end.' +
      (fc.edgeMax.div || fc.edgeMax.playoff
        ? ' The small figure beside each percentage is that percentage against ' +
          'the books&rsquo; own de-vigged price for the same event, in points: ' +
          'a team at +12 is one this model backs twelve points harder than the ' +
          'market does. Hover the cell for the price it is measured against.'
        : '');
  }

  /* The two arithmetic checks worth printing rather than asserting.
   *
   * The second one is a variance decomposition and not a subtraction: a
   * projection's spread and the luck a season adds are independent, so they
   * combine in quadrature. 1.87 of projection and 2.47 of September through
   * January make the 3.12 that the five 17-game seasons actually came in at,
   * which is the sense in which this table is calibrated rather than guessed. */
  function check(fc) {
    var luck = Math.sqrt(Math.max(fc.realized * fc.realized - fc.spread * fc.spread, 0));
    var out = 'Projected wins sum to ' + fc.totalWins.toFixed(1) + ' across ' + fc.games +
      ' games, which is the check &mdash; every game awards exactly one. The column spreads ' +
      fc.spread.toFixed(2) + ' wins wide';
    // The width check, against the only other thirty-two-team forecast in the
    // building that has money behind it.
    if (fc.market) {
      out += ', against the ' + fc.market.spread.toFixed(2) + ' the books&rsquo; own posted ' +
        'win totals spread &mdash; ' + fc.lo.toFixed(1) + '&ndash;' + fc.hi.toFixed(1) +
        ' here against a posted ' + fc.market.lo.toFixed(1) + '&ndash;' +
        fc.market.hi.toFixed(1);
    }
    return out + '. The seasons behind it finished ' +
      fc.realized.toFixed(2) + ' apart, against the ' + REAL_WIN_SD.toFixed(2) +
      ' the five 17-game seasons since 2021 actually came in at; the ' + luck.toFixed(2) +
      ' wins between those two, in quadrature, is the part of a season no August number ' +
      'gets to have an opinion about.';
  }

  /* Draws into `host`, or clears it and hides the section when there is no
   * forecast to draw — a schedule file that did not load costs this section and
   * nothing else on the page. */
  function render(teams, fc) {
    // The note sits outside the host and is written separately, because
    // .bun-section-note is styled as a direct child of .bun-section — the same
    // place The Board keeps #board-note, and for the same reason.
    var note_ = document.getElementById('standings-note');
    var host = document.getElementById('standings-host');
    if (!host) return;

    if (!fc) {
      if (note_) note_.innerHTML = '';
      host.innerHTML = '<p class="proj-empty">Could not load the ' + SEASON +
        ' schedule, so there is nothing to play out.</p>';
      return;
    }

    if (note_) note_.innerHTML = note(teams, fc);
    host.innerHTML =
      '<div class="ps-grid">' +
        CONFS.map(function (c) { return table(teams, fc, c); }).join('') +
      '</div>' +
      reads(teams, fc) +
      '<p class="ps-check">' + check(fc) + '</p>';
  }

  function load() {
    // The same cached loader the team card's schedule tab uses, so the file is
    // fetched once whichever of the two asks first.
    if (typeof global.schedLoad !== 'function') return Promise.resolve(null);
    return global.schedLoad(SEASON).catch(function () { return null; });
  }

  global.bunStandings = {
    load: load,
    forecast: forecast,
    render: render,
    SEASON: SEASON
  };
})(window);
