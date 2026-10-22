// One player's projected stat line against one defense, and the charts that
// show where it came from. For /football/player-projections.
//
// The model (reports/NFL player vs defense visualizations.md):
//
//   projection = volume x efficiency x defense x history
//
//   volume      targets, carries or attempts per game, this season's games
//               weighted toward the latest (LAMBDA per game back), with last
//               season's average as a prior worth PRIOR_GAMES games.
//   efficiency  yards per target, catch rate, ... over this season and last,
//               pulled toward the position's league rate by K[rate]
//               opportunities. Volume is the stable part of a stat line;
//               efficiency is mostly noise until the sample is large.
//   defense     what this defense allowed the position, over what those same
//               players average in their other games (the `exp` on each
//               /api/defense-vs-players row), pulled toward 1.0 by K_DEF games.
//               Defense numbers barely persist, so the pull is hard.
//   history     his career games against this defense, each as a ratio to his
//               average that season, halved per season back, and given at
//               most H2H_MAX of the say. Nothing shows it predicts anything;
//               it is on the page because people ask for it.
//
// Then a distribution around it: normal for passing yards, gamma (right-
// skewed) for rushing and receiving yards, negative binomial for carries,
// catches and completions, Poisson for touchdowns. How wide is built from
// the volume (spreadFor): a game's yards are a sum over its carries or
// targets, so the fewer of them, the more one long run or one drop decides
// the game -- and a backup's role swings with game script and the
// starter's health on top. His own logs then pull that toward what he has
// actually done. Passing yards are not skewed the way a receiver's are: a
// quarterback throws in every game, and a gamma's long right tail put his
// top-1% game near 580 yards, past the NFL record. The
// chance of clearing a line is read off that, not off the hit rate.
//
// Every constant below is a starting point, not a fitted value. Backtest
// before trusting a number to two digits.
//
// Charts, per stat: the projection and what goes into it on one axis (the
// outcome as a quantile dotplot over one row per input, each input's games
// as marks, with what it is worth), and the game log against the line. One
// panel for the defense, by game.
//
// Colors: --series-a (blue) is "over the line" or "toward the over",
// --series-b (orange) "under" or "toward the under", everywhere on the page.
// The two are close in lightness (1.04:1 in the light theme), so color is
// never the only cue: an over is a ▲ and an under a ▼, in every chart, the
// key and the bar labels. No mark carries a halo -- a surface-colored ring
// showed as a pale border on the striped rows and shrank a 9px mark to 7.
// An earlier season's game is the same hue as a dashed outline. Each card
// opens with a key to the symbols and each chart has a line saying how to
// read it. Styles: .pp-* in styles/primary/player-projections.css.

(function (global) {
  'use strict';

  var LAMBDA = 0.88;      // weight per game back, this season
  var PRIOR_GAMES = 3;    // last season's average, as this many games
  var H2H_MAX = 0.05;     // the most say career games vs the defense get
  var CV_PRIOR_GAMES = 8; // his own spread, against the position's

  // League rates by position, and how many opportunities of his it takes to
  // be worth as much as the league's (the stabilization point).
  var LEAGUE = {
    QB: { ypa: 6.9, cmp: 0.65, ptd: 0.045, ypc: 5.0, rtd: 0.035 },
    RB: { ypc: 4.3, rtd: 0.030, catch: 0.78, ypt: 5.9, ctd: 0.025 },
    WR: { ypc: 6.0, rtd: 0.030, catch: 0.64, ypt: 8.1, ctd: 0.045 },
    TE: { ypc: 4.0, rtd: 0.030, catch: 0.72, ypt: 7.3, ctd: 0.050 }
  };
  // Yards per carry was at 400, close to the ~2,000 carries the research
  // gives it to stabilize, which left every back at the league's 4.3 and
  // Jahmyr Gibbs 27 yards under his line. Books pay for an elite back's
  // efficiency; 150 lets two seasons of it show (Gibbs ~5.2) while a
  // backup's 60 carries still say almost nothing.
  var K = { ypa: 300, cmp: 250, ptd: 600, ypc: 150, rtd: 300, catch: 60, ypt: 80, ctd: 200 };
  // A quarterback's carries are scrambles and sneaks, his own kind of run.
  var K_POS = { QB: { ypc: 100 } };
  // The defense factor's pull toward neutral, in games; double for TDs.
  // Strong on purpose: what a defense allowed barely carries over (year to
  // year r of 0.16-0.26) and adds little to a weekly forecast, so five games
  // of it should move a projection a few percent, not a fifth. DET's first
  // five games had passers at +36% over their norm; at 12 that is +11%.
  var K_DEF = { QB: 12, RB: 12, WR: 14, TE: 14 };
  // And never more than this far from even, however lopsided the sample.
  var DEF_CAP = 0.15;
  // How much one carry, target or attempt's yards vary (standard deviation;
  // a target includes its incompletions at 0). Football's long runs and
  // catches make these large next to the means.
  var SD_PER = {
    ypa: { QB: 9.5 },
    ypc: { QB: 7.0, RB: 6.0, WR: 8.0, TE: 5.0 },
    ypt: { QB: 8.0, RB: 8.0, WR: 11.0, TE: 9.5 }
  };
  // How much the volume itself swings: VOL_PHI is the spread of a count
  // around its mean (1 = Poisson), and the role term -- game script, the
  // starter's health, a coach's mood -- is a share of the volume that grows
  // as the volume shrinks. A 20-carry starter's carries move about 20%
  // game to game; a 5-carry backup's about 35%.
  var VOL_PHI = 1.3;
  var ROLE_BASE = { pass_att: 0.12, rush_att: 0.20, targets: 0.20 };
  var ROLE_THIN = 0.25;  // added at zero volume, fading by ...
  var ROLE_FADE = 8;     // ... this many touches a game

  // Team context (contextOf): the offense around him this week, from
  // /api/player-projections?context= -- every game's carries and targets by
  // player, this week's injury report, the line, and the hand adjustments.
  // Starting points, like everything above.
  var CTX = {
    // A share is his carries or targets over the team's. Recent games count
    // more than for volume: a role changes faster than a team's pace.
    LAMBDA_SHARE: 0.75,
    // A teammate whose share of carries or targets is this or more (or the
    // quarterback) is someone whose absence moves everyone else.
    KEY_SHARE: 0.12,
    // A game played with a different lineup from this week's, translated to
    // this week's, counts this much of one that matches it. Backtested on
    // 2025 (every skill player-game from his team's earlier games, with the
    // lineup that played as the report): the translation is most of the
    // signal, so a translated game is worth nearly a matching one.
    MISMATCH_W: 0.8,
    // A missing teammate's carries: to the backs left, by their rank, then
    // the rest pro rata. His targets: this much to his own position, pro
    // rata, the rest to everyone.
    ALLOC_RUSH: [0.6, 0.25, 0.1],
    TGT_SAME_POS: 0.35,
    // And how much of it reaches the players with a share at all: the rest
    // goes to whoever takes his snaps, a depth player with no history. A
    // receiver's targets scatter (2025: handing on all of them made targets
    // worse than ignoring the lineup); a back's carries mostly stay.
    REDIST: { rush_att: 0.8, targets: 0.4, pass_att: 1 },
    // Tempo: how much of the opponent's pace (plays its defense faces, over
    // the league's) carries over, how much a point of total over the team's
    // usual adds, and the most the two can move the team's plays.
    OPP_PACE_W: 0.5,
    TOTAL_PER_PT: 0.004,
    PLAYS_CAP: 0.08,
    // Game script: each point he is favored by beyond the team's usual moves
    // this much of the play mix to the run, up to SCRIPT_CAP.
    SCRIPT_PER_PT: 0.007,
    SCRIPT_CAP: 0.06,
    // His own report: volume kept if questionable or doubtful.
    STATUS_MULT: { questionable: 0.93, doubtful: 0.75 },
    // Per lineman starter out.
    OL: { ypc: 0.97, ypa: 0.985 },
    // A new starting quarterback, before his games say otherwise, and how
    // many targets of evidence it takes to be worth as much.
    QB_YPT: 0.92, K_QB: 40,
    // His rate in games like this week's, shrunk by this many carries or
    // targets, and never more than EFF_CAP from his rate overall.
    K_EFF: { ypc: 120, ypt: 60 }, EFF_CAP: 0.1, EFF_MIN_GAMES: 2,
    // Before this many games with the team, his own log leads.
    PRIOR_GAMES: 3,
    // More spread when the context moves his volume by more than this.
    BUMP_AT: 0.15, BUMP: 0.08
  };
  var CTX_FIELDS = ['pass_att', 'rush_att', 'targets'];
  var GROUP = { RB: 'RB', FB: 'RB', WR: 'WR', TE: 'TE', QB: 'QB' };
  var TEAM_FACTORS = { tempo: true, script: true, line: true };

  // rate: numerator / volume field.
  var RATES = {
    ypa: ['pass_yds', 'pass_att'], cmp: ['pass_cmp', 'pass_att'], ptd: ['pass_td', 'pass_att'],
    ypc: ['rush_yds', 'rush_att'], rtd: ['rush_td', 'rush_att'],
    catch: ['rec', 'targets'], ypt: ['rec_yds', 'targets'], ctd: ['rec_td', 'targets']
  };

  // kind: yds (gamma), count (Poisson), td (Poisson, drawn as bars).
  // parts: [volume field, rate], summed -- only touchdowns have two.
  var STATS = {
    pass_yds: { label: 'Pass Yds', short: 'Pass', unit: 'yds', kind: 'yds', family: 'normal', parts: [['pass_att', 'ypa']], market: 'passing_yards' },
    pass_cmp: { label: 'Completions', short: 'Cmp', unit: 'cmp', kind: 'count', parts: [['pass_att', 'cmp']], market: 'passing_completions' },
    pass_td: { label: 'Pass TD', short: 'P TD', unit: 'TD', kind: 'td', parts: [['pass_att', 'ptd']], market: 'passing_tds' },
    rush_yds: { label: 'Rush Yds', short: 'Rush', unit: 'yds', kind: 'yds', parts: [['rush_att', 'ypc']], market: 'rushing_yards' },
    rush_att: { label: 'Carries', short: 'Car', unit: 'car', kind: 'count', parts: [['rush_att', null]], market: 'rushing_attempts' },
    rec: { label: 'Receptions', short: 'Rec', unit: 'rec', kind: 'count', parts: [['targets', 'catch']], market: 'receptions' },
    rec_yds: { label: 'Rec Yds', short: 'Rec Yd', unit: 'yds', kind: 'yds', parts: [['targets', 'ypt']], market: 'receiving_yards' },
    tot_td: { label: 'Anytime TD', short: 'TD', unit: 'TD', kind: 'td', parts: [['rush_att', 'rtd'], ['targets', 'ctd']], anytime: true }
  };

  var BY_POS = {
    QB: ['pass_yds', 'pass_cmp', 'pass_td', 'rush_yds'],
    RB: ['rush_yds', 'rush_att', 'rec', 'rec_yds', 'tot_td'],
    WR: ['rec_yds', 'rec', 'tot_td'],
    TE: ['rec_yds', 'rec', 'tot_td']
  };

  // The volume each stat's game log prints under its bar.
  var VOL_LABEL = { pass_att: 'att', rush_att: 'car', targets: 'tgt' };

  var BOOK = { draftkings: 'DK', fanduel: 'FD', betmgm: 'MGM', caesars: 'CZR', fanatics: 'FAN', betrivers: 'BR' };

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function sum(a, f) { var s = 0; a.forEach(function (x) { s += f(x); }); return s; }
  function clamp(x, lo, hi) { return Math.max(lo, Math.min(hi, x)); }
  function r1(x) { return Math.round(x * 10) / 10; }
  function fmt(x) { return Math.abs(x) >= 20 ? String(Math.round(x)) : String(r1(x)); }
  function pct(p) { return Math.round(p * 100) + '%'; }
  function signPct(x) { var v = Math.round((x - 1) * 100); return (v > 0 ? '+' : v < 0 ? '−' : '±') + Math.abs(v) + '%'; }

  /* ---------- distributions ---------- */

  function lgamma(x) {
    var c = [76.18009172947146, -86.50532032941677, 24.01409824083091,
             -1.231739572450155, 0.1208650973866179e-2, -0.5395239384953e-5];
    var y = x, t = x + 5.5, s = 1.000000000190015;
    t -= (x + 0.5) * Math.log(t);
    for (var j = 0; j < 6; j++) s += c[j] / ++y;
    return -t + Math.log(2.5066282746310005 * s / x);
  }

  // Regularized lower incomplete gamma P(a, x).
  function gammaP(a, x) {
    if (x <= 0) return 0;
    var gln = lgamma(a), i;
    if (x < a + 1) {
      var ap = a, del = 1 / a, s = del;
      for (i = 0; i < 200; i++) { ap++; del *= x / ap; s += del; if (Math.abs(del) < Math.abs(s) * 1e-10) break; }
      return s * Math.exp(-x + a * Math.log(x) - gln);
    }
    var b = x + 1 - a, c = 1e300, d = 1 / b, h = d;
    for (i = 1; i < 200; i++) {
      var an = -i * (i - a);
      b += 2;
      d = an * d + b; if (Math.abs(d) < 1e-300) d = 1e-300;
      c = b + an / c; if (Math.abs(c) < 1e-300) c = 1e-300;
      d = 1 / d;
      var del2 = d * c;
      h *= del2;
      if (Math.abs(del2 - 1) < 1e-10) break;
    }
    return 1 - Math.exp(-x + a * Math.log(x) - gln) * h;
  }

  function poissonPmf(k, lam) { return Math.exp(k * Math.log(lam) - lam - lgamma(k + 1)); }

  // -> { cdf(x), q(p), pmf(k) (counts only), discrete, mean }
  // Abramowitz-Stegun 7.1.26, good to 1.5e-7.
  function normCdf(z) {
    var t = 1 / (1 + 0.3275911 * Math.abs(z) / Math.SQRT2);
    var e = t * (0.254829592 + t * (-0.284496736 + t * (1.421413741 + t * (-1.453152027 + t * 1.061405429))));
    var erf = 1 - e * Math.exp(-z * z / 2);
    return z >= 0 ? (1 + erf) / 2 : (1 - erf) / 2;
  }

  function negBinPmf(k, mean, r) {
    var p = r / (r + mean);
    return Math.exp(lgamma(k + r) - lgamma(k + 1) - lgamma(r) + r * Math.log(p) + k * Math.log(1 - p));
  }

  // over: a count's spread beyond Poisson, as 1/r (0 is Poisson).
  function distribution(kind, mean, cv, family, over) {
    mean = Math.max(mean, 0.01);
    if (kind === 'yds' && family === 'normal') {
      // Cut off at zero and rescaled, though at a quarterback's spread the
      // part below zero is a rounding error.
      var sd = mean * cv, below = normCdf(-mean / sd);
      var ncdf = function (x) { return x <= 0 ? 0 : (normCdf((x - mean) / sd) - below) / (1 - below); };
      return {
        discrete: false, mean: mean, cdf: ncdf,
        q: function (p) {
          var lo = 0, hi = mean + 6 * sd;
          for (var i = 0; i < 60; i++) { var m = (lo + hi) / 2; if (ncdf(m) < p) lo = m; else hi = m; }
          return (lo + hi) / 2;
        }
      };
    }
    if (kind === 'yds') {
      var shape = 1 / (cv * cv), scale = mean / shape;
      var cdf = function (x) { return gammaP(shape, Math.max(x, 0) / scale); };
      return {
        discrete: false, mean: mean, cdf: cdf,
        q: function (p) {
          var lo = 0, hi = mean * 12;
          for (var i = 0; i < 60; i++) { var m = (lo + hi) / 2; if (cdf(m) < p) lo = m; else hi = m; }
          return (lo + hi) / 2;
        }
      };
    }
    var r = over > 1e-4 ? 1 / over : 0;
    var pmf = function (k) { return k < 0 ? 0 : r ? negBinPmf(k, mean, r) : poissonPmf(k, mean); };
    var cdfD = function (x) { var s = 0; for (var k = 0; k <= Math.floor(x); k++) s += pmf(k); return Math.min(s, 1); };
    return {
      discrete: true, mean: mean, cdf: cdfD, pmf: pmf,
      q: function (p) { var s = 0; for (var k = 0; k < 400; k++) { s += pmf(k); if (s >= p) return k; } return 400; }
    };
  }

  /* ---------- the model ---------- */

  function rateOf(games, rate, pos) {
    if (!rate) return { value: 1, own: null, opp: 0, league: null };
    var f = RATES[rate];
    var num = sum(games, function (g) { return g[f[0]] || 0; });
    var den = sum(games, function (g) { return g[f[1]] || 0; });
    var lg = LEAGUE[pos][rate];
    var k = (K_POS[pos] && K_POS[pos][rate]) || K[rate];
    return { value: (num + k * lg) / (den + k), own: den ? num / den : null, opp: den, league: lg, k: k };
  }

  // Volume per game: this season newest first, decayed, with last season as
  // a prior. -> { value }.
  function volumeOf(cur, prev, field) {
    var w = 1, sw = 0, sx = 0;
    cur.forEach(function (g) {
      sx += w * (g[field] || 0); sw += w;
      w *= LAMBDA;
    });
    if (prev.length) {
      sx += PRIOR_GAMES * sum(prev, function (g) { return g[field] || 0; }) / prev.length;
      sw += PRIOR_GAMES;
    }
    return { value: sw ? sx / sw : 0 };
  }

  // What the defense allowed this position, game by game, against what those
  // players usually get. -> { pending, games: [...], n, raw, factor }.
  function defenseOf(defDoc, pos, stat, kind) {
    if (!defDoc) return { none: true, games: [], n: 0, raw: 1, factor: 1 };
    var rows = defDoc.rows || [];
    if (rows.length && !rows.some(function (r) { return r.exp !== undefined; })) {
      return { pending: true, games: [], n: 0, raw: 1, factor: 1 };
    }
    var byGame = {};
    (defDoc.games || []).forEach(function (g) {
      if (!g.postseason) byGame[g.game_id] = { week: g.week, opp: g.opp, allowed: 0, exp: 0 };
    });
    rows.forEach(function (r) {
      var g = byGame[r.game_id];
      if (!g || r.pos !== pos || !r.exp) return;
      g.allowed += r[stat] || 0;
      g.exp += r.exp[stat] || 0;
    });
    var games = Object.keys(byGame).map(function (k) { return byGame[k]; })
      .filter(function (g) { return g.exp > 0; })
      .sort(function (a, b) { return a.week - b.week; });
    games.forEach(function (g) { g.ratio = g.allowed / g.exp; });
    var n = games.length;
    var raw = n ? sum(games, function (g) { return g.allowed; }) / sum(games, function (g) { return g.exp; }) : 1;
    var k = K_DEF[pos] * (kind === 'td' ? 2 : 1);
    var factor = clamp((n * raw + k) / (n + k), 1 - DEF_CAP, 1 + DEF_CAP);
    return { games: games, n: n, raw: raw, factor: factor, k: k };
  }

  // Career games against the defense, each against his average that season.
  function historyOf(all, def, stat, season) {
    var bySeason = {};
    all.forEach(function (g) {
      var s = bySeason[g.season] || (bySeason[g.season] = { n: 0, x: 0 });
      s.n++; s.x += g[stat] || 0;
    });
    var sw = 0, sx = 0;
    var games = all.filter(function (g) { return g.opp === def; }).map(function (g) {
      var s = bySeason[g.season], avg = s.x / s.n, w = Math.pow(0.5, season - g.season);
      if (avg <= 0) return { g: g, ratio: null };
      var ratio = clamp((g[stat] || 0) / avg, 0.25, 3);
      sw += w; sx += w * ratio;
      return { g: g, ratio: ratio };
    });
    var ratio = sw ? sx / sw : 1;
    var share = H2H_MAX * Math.min(1, sw / 2);
    return { games: games, ratio: ratio, weight: sw, share: share, mult: 1 + share * (ratio - 1) };
  }

  // The volume's own swing, as a share of it.
  function roleSpread(volField, vol) {
    return (ROLE_BASE[volField] || 0.2) + ROLE_THIN * Math.exp(-vol / ROLE_FADE);
  }

  // A game's yards as a sum over its N touches, each worth X:
  //   Var = E[N] Var(X) + Var(N) E[X]^2,   Var(N) = phi E[N] + (role E[N])^2
  // -> as a share of the mean (CV), the spread a player with this volume
  // and this efficiency should have.
  function structuralCv(vol, perMean, perSd, role) {
    vol = Math.max(vol, 0.5);
    perMean = Math.max(perMean, 0.5);
    return Math.sqrt(perSd * perSd / (vol * perMean * perMean) + VOL_PHI / vol + role * role);
  }

  function spreadOf(games, stat, volField, pos, prior) {
    var vals = games.filter(function (g) { return (g[volField] || 0) > 0; }).map(function (g) { return g[stat] || 0; });
    var n = vals.length;
    if (n < 3) return prior;
    var m = sum(vals, function (v) { return v; }) / n;
    if (m <= 0) return prior;
    var sd = Math.sqrt(sum(vals, function (v) { return (v - m) * (v - m); }) / (n - 1));
    return clamp((n * (sd / m) + CV_PRIOR_GAMES * prior) / (n + CV_PRIOR_GAMES), 0.2, 2);
  }

  /* ---------- team context ----------
   *
   * His volume above is his own: his carries a game, decayed. That cannot
   * see the team around him -- the starter ruled out this week, the starter
   * back after the three games he carried the load in, a quick offense
   * against a slow one. So with the team's games in hand (ctx.doc, from
   * scripts/build_team_context.py) his volume is rebuilt as
   *
   *   the team's carries or targets  x  his share of them
   *
   * and each step that moves it is a factor, multiplying a volume (vol) or a
   * rate (eff), named, explained and switchable:
   *
   *   role      his share over his games, recent ones counting most, times
   *             the team's volume -- in place of his own decayed count, once
   *             he has PRIOR_GAMES games with the team
   *   lineup    every one of his games translated to this week's lineup:
   *             a key teammate out now but in that game hands over his
   *             share (ALLOC_*), one back now but out then takes his back.
   *             Games that already match this week count most.
   *   tempo     the team's plays against this opponent's pace and total
   *   script    the run/pass mix against the spread
   *   status    his own injury report
   *   line      offensive linemen out
   *   qb        a new starting quarterback, for his receivers
   *   roleEff   how efficient he has been in games like this week's
   *   manual    what an editor set by hand (adjust.data)
   *
   * A hand-set status replaces the report's before any of it runs, so
   * marking a back out moves every teammate's projection. */

  function teamTotal(g, field) {
    var s = 0;
    for (var id in g.players) s += g.players[id][field] || 0;
    return s;
  }

  function played(g, id) {
    var p = g.players[id];
    return !!p && ((p.snap || 0) > 0 || (p.rush_att || 0) + (p.targets || 0) + (p.pass_att || 0) > 0);
  }

  function shareIn(g, id, field) {
    var t = teamTotal(g, field);
    return played(g, id) && t > 0 ? (g.players[id][field] || 0) / t : null;
  }

  // f over the games it is defined for, newest first, each one back
  // weighted `lambda` of the one after it. -> null when it is never defined.
  function decayed(games, f, lambda) {
    var w = 1, sw = 0, sx = 0;
    games.forEach(function (g) {
      var v = f(g);
      if (v == null) return;
      sx += w * v; sw += w; w *= lambda;
    });
    return sw ? sx / sw : null;
  }

  function avgOf(list, f) {
    var vals = list.map(f).filter(function (v) { return v != null; });
    return vals.length ? sum(vals, function (v) { return v; }) / vals.length : null;
  }

  // -> his status this week: { status: out|doubtful|questionable|null, row, manual }.
  function statusOf(ctx, id) {
    var adj = ((ctx.adjust || {}).data || {}).status || {};
    var row = (ctx.status || {})[id] || null;
    if (adj[id]) return { status: adj[id] === 'in' ? null : adj[id], row: row, manual: true };
    return { status: row ? row.status : null, row: row, manual: false };
  }

  function weekList(games) {
    var w = games.map(function (g) { return g.week; }).sort(function (a, b) { return a - b; });
    return w.length ? 'wk ' + w.join(', ') : '';
  }

  function lastName(name) { var p = String(name || '').split(' '); return p.length > 1 ? p.slice(1).join(' ') : name; }

  /* -> { factors, matched: {game id: true}, out, why } or null without a
   * team doc. `vol0` is his own decayed volume per field, the baseline the
   * role factor replaces. */
  function contextOf(ctx, opp, pid, pos, vol0) {
    var doc = ctx && ctx.doc;
    pid = String(pid);
    if (!doc || !doc.games || !doc.players) return null;
    var games = doc.games.filter(function (g) { return !g.postseason; });
    if (!games.length) return null;
    var adj = (ctx.adjust || {}).data || {}, off = adj.off || {}, mineAdj = (adj.players || {})[pid] || {};
    var game = adj.game || {};
    var mine = games.filter(function (g) { return played(g, pid); });
    var factors = [];
    // A factor about the team is switched off for the team; one about him,
    // for him alone.
    function add(f) {
      f.offKey = TEAM_FACTORS[f.key] ? f.key : f.key + ':' + pid;
      f.off = !!off[f.offKey];
      factors.push(f);
    }
    function everyField(m) { var o = {}; CTX_FIELDS.forEach(function (f) { o[f] = m; }); return o; }

    // Everyone who has had a share of this offense, his usual share when he
    // plays, and whether he is expected on the field this week: not out or
    // doubtful, and either on the report or in one of the last two games --
    // a starter traded or cut is simply gone.
    var recent = games.slice(0, 2);
    // A quarterback is in the lineup when he starts, not when he mops up:
    // the one who threw the most that game. Only the latest starter is key.
    var leadQb = function (g) {
      var best = null;
      for (var id in g.players) {
        if ((doc.players[id] || {}).pos === 'QB' && (!best || (g.players[id].pass_att || 0) > (g.players[best].pass_att || 0))) best = id;
      }
      return best;
    };
    var starterId = leadQb(games[0]);
    var inLineup = function (g, T) { return T.pos === 'QB' ? leadQb(g) === T.id : played(g, T.id); };
    var mates = Object.keys(doc.players).map(function (id) {
      var p = doc.players[id], st = statusOf(ctx, id);
      var share = {};
      CTX_FIELDS.forEach(function (f) {
        share[f] = decayed(games, function (g) { return shareIn(g, id, f); }, CTX.LAMBDA_SHARE) || 0;
      });
      var gone = !st.manual && !st.row && !recent.some(function (g) { return played(g, id); });
      var expected = st.status !== 'out' && st.status !== 'doubtful' && !gone;
      return {
        id: id, name: p.name, pos: p.pos, group: GROUP[p.pos], share: share, expected: expected, gone: gone, st: st,
        key: id !== pid && !!GROUP[p.pos] && (p.pos === 'QB' ? id === starterId
          : share.rush_att >= CTX.KEY_SHARE || share.targets >= CTX.KEY_SHARE)
      };
    });
    var me = mates.filter(function (m) { return m.id === pid; })[0];
    var keys = mates.filter(function (m) { return m.key; });
    var pool = mates.filter(function (m) { return m.expected || m.id === pid; });

    // How much of a teammate's share comes to him: by rank among the backs
    // for a back's carries, partly by position for targets, the rest pro
    // rata across everyone expected to play.
    function alloc(T, field) {
      // A quarterback's throws and scrambles go to the one who replaces him.
      if (field === 'pass_att' || T.group === 'QB') return T.group === 'QB' && GROUP[pos] === 'QB' ? 1 : 0;
      var others = pool.filter(function (m) { return m.id !== T.id; });
      var total = sum(others, function (m) { return m.share[field]; });
      var mineS = me ? me.share[field] : 0;
      var pro = total > 0 ? mineS / total : 0;
      if (field === 'rush_att') {
        if (T.group !== 'RB') return pro;
        var backs = others.filter(function (m) { return m.group === 'RB'; })
          .sort(function (a, b) { return b.share.rush_att - a.share.rush_att; });
        var used = 0, same = 0;
        backs.forEach(function (m, i) { var a = CTX.ALLOC_RUSH[i] || 0; used += a; if (m.id === pid) same = a; });
        return same + (1 - used) * pro;
      }
      var peers = others.filter(function (m) { return m.group === T.group; });
      var peerTot = sum(peers, function (m) { return m.share.targets; });
      var sameT = GROUP[pos] === T.group && peerTot > 0 ? CTX.TGT_SAME_POS * mineS / peerTot : 0;
      return sameT + (1 - (peers.length ? CTX.TGT_SAME_POS : 0)) * pro;
    }

    // Which of his games had this week's lineup.
    var matched = {};
    mine.forEach(function (g) {
      if (keys.every(function (T) { return inLineup(g, T) === T.expected; })) matched[g.game_id] = true;
    });

    var sAll = {}, sLine = {}, teamVol = {};
    CTX_FIELDS.forEach(function (f) {
      teamVol[f] = decayed(games, function (g) { return teamTotal(g, f); }, LAMBDA) || 0;
      sAll[f] = decayed(mine, function (g) { return shareIn(g, pid, f); }, CTX.LAMBDA_SHARE) || 0;
      var w = 1, sw = 0, sx = 0;
      mine.forEach(function (g) {
        var s = shareIn(g, pid, f);
        if (s == null) return;
        var a = s;
        keys.forEach(function (T) {
          var was = inLineup(g, T);
          if (was === T.expected) return;
          var k = alloc(T, f) * CTX.REDIST[f];
          a += was ? (shareIn(g, T.id, f) || 0) * k : -T.share[f] * k;
        });
        a = Math.max(a, s * 0.3);
        var wt = w * (matched[g.game_id] ? 1 : CTX.MISMATCH_W);
        sx += wt * a; sw += wt; w *= CTX.LAMBDA_SHARE;
      });
      sLine[f] = sw ? sx / sw : sAll[f];
    });

    var snapOf = function (g) { var p = g.players[pid]; return p && p.snap != null ? p.snap : null; };
    var snapRecent = avgOf(mine.slice(0, 3), snapOf), snapSeason = avgOf(mine, snapOf);
    var n = mine.length;
    var who = me ? lastName(me.name) : 'He';

    // role: his share of the team's volume, blended with his own log while
    // his games with the team are few.
    if (n) {
      var vol = {}, parts = [];
      CTX_FIELDS.forEach(function (f) {
        if (!(vol0[f] > 0)) return;
        var v = (n * sAll[f] * teamVol[f] + CTX.PRIOR_GAMES * vol0[f]) / (n + CTX.PRIOR_GAMES);
        vol[f] = v / vol0[f];
      });
      ['rush_att', 'targets'].forEach(function (f) {
        if (sAll[f] < 0.02) return;
        var last3 = avgOf(mine.slice(0, 3), function (g) { return shareIn(g, pid, f); });
        parts.push(Math.round(sAll[f] * 100) + '% of ' + (f === 'rush_att' ? 'carries' : 'targets') +
          (last3 != null && n > 3 ? ' (last 3: ' + Math.round(last3 * 100) + '%)' : ''));
      });
      if (snapSeason != null) {
        parts.push(Math.round(snapSeason * 100) + '% of snaps' +
          (snapRecent != null && n > 3 && Math.abs(snapRecent - snapSeason) >= 0.05 ? ' (last 3: ' + Math.round(snapRecent * 100) + '%)' : ''));
      }
      add({ key: 'role', label: 'Role', source: 'auto', vol: vol,
        why: who + ' this season, recent games weighted most: ' + (parts.join(' · ') || 'a small share') +
          ', of the ' + Math.round(teamVol.rush_att) + ' carries and ' + Math.round(teamVol.targets) + ' targets ' +
          doc.team + ' averages' });
    }

    // lineup: the key teammates whose presence differs from his games.
    var changes = keys.filter(function (T) { return mine.some(function (g) { return inLineup(g, T) !== T.expected; }); });
    if (n && changes.length) {
      var lv = {};
      CTX_FIELDS.forEach(function (f) { if (sAll[f] > 0) lv[f] = sLine[f] / sAll[f]; });
      var said = changes.map(function (T) {
        var missed = mine.filter(function (g) { return !inLineup(g, T); });
        if (!T.expected) {
          var why = T.st.manual ? 'set out by hand' : T.gone ? 'not played since ' + weekList(games.filter(function (g) { return inLineup(g, T); }).slice(0, 1)) :
            (T.st.row && (T.st.row.injury || T.st.row.label)) || T.st.status;
          return lastName(T.name) + ' out (' + why + ')' + (missed.length ? '; ' + missed.length + ' of ' + who + '\'s games without him' : '');
        }
        if (T.pos === 'QB') return lastName(T.name) + ' starting; another QB started ' + weekList(missed);
        return lastName(T.name) + ' back' + (T.st.manual ? ' (set in by hand)' : '') + '; missed ' + weekList(missed);
      });
      var nm = Object.keys(matched).length;
      var shares = ['rush_att', 'targets'].filter(function (f) { return sAll[f] >= 0.02; }).map(function (f) {
        return (f === 'rush_att' ? 'carries' : 'targets') + ' ' + Math.round(sAll[f] * 100) + '% → ' + Math.round(sLine[f] * 100) + '%';
      });
      add({ key: 'lineup', label: 'Teammates', source: changes.some(function (T) { return T.st.manual; }) ? 'manual' : 'auto', vol: lv,
        why: said.join(' · ') + '. ' + (nm ? nm + ' of his games match this week\'s lineup' : 'None of his games match this week\'s lineup') +
          (shares.length ? ': share of ' + shares.join(', ') : '') });
    }

    // tempo: the team's plays, against the opponent's pace and the total.
    var league = doc.league || {};
    var playsTeam = decayed(games, function (g) { return g.plays; }, LAMBDA), autoPlays = null;
    if (playsTeam) {
      var oppGames = ((opp && opp.doc && opp.doc.games) || []).filter(function (g) { return !g.postseason; });
      var oppFaced = avgOf(oppGames, function (g) { return g.opp_plays; });
      var total = game.total != null ? game.total : ctx.total;
      var usualTotal = avgOf(games, function (g) { return g.total; }) || league.total;
      var exp = playsTeam + (oppFaced != null && league.plays ? CTX.OPP_PACE_W * (oppFaced - league.plays) : 0);
      if (total != null && usualTotal) exp *= 1 + CTX.TOTAL_PER_PT * (total - usualTotal);
      var pm = clamp(exp / playsTeam, 1 - CTX.PLAYS_CAP, 1 + CTX.PLAYS_CAP);
      autoPlays = Math.round(playsTeam * pm);
      var tw = [doc.team + ' runs ' + r1(playsTeam) + ' plays a game'];
      if (oppFaced != null) tw.push((opp.doc.team || 'the opponent') + '\'s defense faces ' + r1(oppFaced) + ' (league ' + league.plays + ')');
      if (total != null) tw.push('total ' + total + (game.total != null ? ' (set by hand)' : '') + ' vs its usual ' + r1(usualTotal));
      if (game.plays != null) {
        pm = clamp(game.plays / playsTeam, 0.7, 1.3);
        tw = [doc.team + ' set to ' + game.plays + ' plays by hand, from ' + r1(playsTeam)];
      }
      add({ key: 'tempo', label: 'Tempo & total', source: game.plays != null || game.total != null ? 'manual' : 'auto',
        vol: everyField(pm), why: tw.join(' · ') + ' → ' + r1(playsTeam * pm) + ' plays' });

      // script: favored, they run more; behind, they throw.
      var spread = game.spread != null ? game.spread : ctx.spread;
      var rush0 = decayed(games, function (g) { return g.plays ? g.rush / g.plays : null; }, LAMBDA);
      if (spread != null && rush0) {
        var usual = avgOf(games, function (g) { return g.spread; }) || 0;
        var shift = clamp(CTX.SCRIPT_PER_PT * (usual - spread), -CTX.SCRIPT_CAP, CTX.SCRIPT_CAP);
        var passM = (1 - rush0 - shift) / (1 - rush0);
        add({ key: 'script', label: 'Game script', source: game.spread != null ? 'manual' : 'auto',
          vol: { rush_att: (rush0 + shift) / rush0, targets: passM, pass_att: passM },
          why: doc.team + ' ' + (spread > 0 ? '+' : '') + spread + (game.spread != null ? ' (set by hand)' : '') +
            ' vs its usual ' + (usual > 0 ? '+' : '') + r1(usual) + ': run share ' + Math.round(rush0 * 100) + '% → ' +
            Math.round((rush0 + shift) * 100) + '%' });
      }
    }

    // status: his own report.
    var mySt = statusOf(ctx, pid), out = mySt.status === 'out';
    var row = mySt.row || {};
    var stWhy = (mySt.manual ? 'Set ' + (mySt.status || 'in') + ' by hand' : (row.label || mySt.status || '')) +
      (row.injury ? ' (' + row.injury + ')' : '') +
      (row.practice && row.practice.length ? ' · practice: ' + row.practice.map(function (p) { return p.replace(/_/g, ' '); }).join(', ') : '');
    if (CTX.STATUS_MULT[mySt.status]) {
      add({ key: 'status', label: 'His status', source: mySt.manual ? 'manual' : 'auto',
        vol: everyField(CTX.STATUS_MULT[mySt.status]), why: stWhy });
    }

    // line: starters out, by the report or by hand.
    var olOut = (ctx.ol || []).filter(function (o) { return o.status === 'out' || o.status === 'doubtful'; });
    var nOl = adj.ol_out != null ? adj.ol_out : olOut.length;
    if (nOl) {
      add({ key: 'line', label: 'Offensive line', source: adj.ol_out != null ? 'manual' : 'auto',
        eff: { ypc: Math.pow(CTX.OL.ypc, nOl), ypa: Math.pow(CTX.OL.ypa, nOl) },
        why: nOl + ' starting ' + (nOl > 1 ? 'linemen' : 'lineman') + ' out' + (adj.ol_out != null ? ' (set by hand)' :
          ': ' + olOut.map(function (o) { return o.name + ' (' + Math.round(o.snap * 100) + '% of snaps)'; }).join(', ')) });
    }

    // qb: his receivers' rate under a quarterback who is not the starter.
    // The starter is whoever threw the most in the last game.
    var g0 = games[0];
    var starter = mates.filter(function (m) { return m.pos === 'QB' && m.id !== pid && played(g0, m.id); })
      .sort(function (a, b) { return (g0.players[b.id].pass_att || 0) - (g0.players[a.id].pass_att || 0); })[0];
    if (pos !== 'QB' && starter && !starter.expected) {
      var tw2 = 0, yw = 0, tWith = 0, yWith = 0;
      mine.forEach(function (g) {
        var p = g.players[pid];
        if (leadQb(g) === starter.id) { tWith += p.targets || 0; yWith += p.rec_yds || 0; } else { tw2 += p.targets || 0; yw += p.rec_yds || 0; }
      });
      var seen = tw2 && tWith ? (yw / tw2) / (yWith / tWith) : null;
      var qm = clamp(((seen != null ? tw2 * seen : 0) + CTX.K_QB * CTX.QB_YPT) / ((seen != null ? tw2 : 0) + CTX.K_QB), 0.8, 1.05);
      add({ key: 'qb', label: 'Quarterback', source: starter.st.manual ? 'manual' : 'auto',
        eff: { ypt: qm, catch: 1 - (1 - qm) / 3 },
        why: lastName(starter.name) + ' out' + (seen != null ? '; ' + who + ' had ' + tw2 + ' targets without him at ' +
          r1(yw / tw2) + ' yds each, ' + r1(yWith / tWith) + ' with' : '; no games without him to go on') });
    }

    // roleEff: his rate in games like this week's, where there are others.
    var nm2 = Object.keys(matched).length;
    if (nm2 >= CTX.EFF_MIN_GAMES && nm2 < n) {
      var eff = {}, ew = [];
      [['rush_att', 'rush_yds', 'ypc', 'yds/carry'], ['targets', 'rec_yds', 'ypt', 'yds/target']].forEach(function (r) {
        var oM = 0, yM = 0, oA = 0, yA = 0;
        mine.forEach(function (g) {
          var p = g.players[pid];
          oA += p[r[0]] || 0; yA += p[r[1]] || 0;
          if (matched[g.game_id]) { oM += p[r[0]] || 0; yM += p[r[1]] || 0; }
        });
        if (!oM || !oA || !yA) return;
        var ratio = (yM / oM) / (yA / oA);
        eff[r[2]] = clamp(1 + oM / (oM + CTX.K_EFF[r[2]]) * (ratio - 1), 1 - CTX.EFF_CAP, 1 + CTX.EFF_CAP);
        if (Math.abs(eff[r[2]] - 1) >= 0.005) ew.push(r1(yM / oM) + ' ' + r[3] + ' over ' + oM + ' vs ' + r1(yA / oA) + ' overall');
      });
      if (ew.length) {
        add({ key: 'roleEff', label: 'In games like this', source: 'auto', eff: eff,
          why: who + ' in his ' + nm2 + ' game' + (nm2 > 1 ? 's' : '') + ' with this week\'s lineup: ' + ew.join('; ') });
      }
    }

    // manual: what an editor set for him.
    // A share set by hand stands in for the role and lineup factors' share;
    // the team's volume (tempo, script) and his status still apply on top.
    var product = function (f, keys) {
      var m = 1;
      factors.forEach(function (x) { if (!x.off && keys.indexOf(x.key) >= 0 && x.vol && x.vol[f]) m *= x.vol[f]; });
      return m;
    };
    [['car_share', 'rush_att', 'carries'], ['tgt_share', 'targets', 'targets']].forEach(function (r) {
      var want = mineAdj[r[0]], f = r[1];
      if (want == null || !(vol0[f] > 0) || !(teamVol[f] > 0)) return;
      var o = {};
      o[f] = want * teamVol[f] * product(f, ['tempo', 'script']) /
        (vol0[f] * product(f, ['role', 'lineup', 'tempo', 'script']));
      add({ key: 'm_' + r[0], label: 'Share of ' + r[2], source: 'manual', vol: o,
        why: 'Set to ' + Math.round(want * 100) + '% of ' + doc.team + '\'s ' + r[2] + ' by hand (model ' +
          Math.round(sLine[f] * 100) + '%)' });
    });
    if (mineAdj.snap != null && snapRecent) {
      add({ key: 'm_snap', label: 'Snap share', source: 'manual', vol: everyField(mineAdj.snap / snapRecent),
        why: 'Set to ' + Math.round(mineAdj.snap * 100) + '% of snaps by hand, from ' + Math.round(snapRecent * 100) + '% over his last 3' });
    }
    if (mineAdj.vol_mult != null) {
      add({ key: 'm_vol', label: 'Volume', source: 'manual', vol: everyField(mineAdj.vol_mult),
        why: '×' + mineAdj.vol_mult + ' by hand' + (mineAdj.note ? ': ' + mineAdj.note : '') });
    }
    if (mineAdj.eff_mult != null) {
      add({ key: 'm_eff', label: 'Efficiency', source: 'manual',
        eff: { ypa: mineAdj.eff_mult, ypc: mineAdj.eff_mult, ypt: mineAdj.eff_mult },
        why: '×' + mineAdj.eff_mult + ' per play by hand' + (mineAdj.note && mineAdj.vol_mult == null ? ': ' + mineAdj.note : '') });
    }

    return {
      factors: factors, matched: matched, nMatched: nm2, n: n, out: out, statusWhy: stWhy,
      team: doc.team, mates: mates.filter(function (m) { return m.id !== pid && m.group; }),
      share: { car: sLine.rush_att, tgt: sLine.targets }, snap: snapRecent,
      // The model's own game inputs, before any hand: the form's placeholders.
      game: { spread: ctx.spread, total: ctx.total, plays: autoPlays }
    };
  }

  /* opts: { games (career, newest first), pos, season, def, defDoc, props,
   *         context: { team, opp, player_id } -- the two sides of
   *         /api/player-projections?context=, this week's game only }
   * -> { pos, stats: [model per stat], context } or { error } */
  function build(opts) {
    var pos = opts.pos, season = opts.season;
    var cur = opts.games.filter(function (g) { return g.season === season; });
    var prev = opts.games.filter(function (g) { return g.season === season - 1; });
    if (!cur.length && !prev.length) return { error: 'No games this season or last to project from.' };
    var recent = cur.concat(prev);
    var c = opts.context, context = null;
    if (c && c.team) {
      var vol0 = {};
      CTX_FIELDS.forEach(function (f) { vol0[f] = volumeOf(cur, prev, f).value; });
      context = contextOf(c.team, c.opp, c.player_id, pos, vol0);
    }
    var factors = context ? context.factors : [];
    // The product of the factors switched on, for one volume field or rate,
    // leaving out `skip` -- so each factor's worth is the mean with it less
    // the mean without it.
    function multOf(kind, name, skip) {
      var m = 1;
      factors.forEach(function (f) { if (!f.off && f.key !== skip && f[kind] && f[kind][name]) m *= f[kind][name]; });
      return m;
    }
    var stats = (BY_POS[pos] || []).map(function (key) {
      var spec = STATS[key];
      var volumes = [];
      spec.parts.forEach(function (p) {
        volumes.push({ field: p[0], volume: volumeOf(cur, prev, p[0]), rate: rateOf(recent, p[1], pos), rateKey: p[1] });
      });
      var baseWith = function (skip) {
        return sum(volumes, function (v) {
          return v.volume.value * multOf('vol', v.field, skip) * v.rate.value * (v.rateKey ? multOf('eff', v.rateKey, skip) : 1);
        });
      };
      var base = baseWith(null);
      var defense = defenseOf(opts.defDoc, pos, key, spec.kind);
      var history = historyOf(opts.games, opts.def, key, season);
      var mean = base * defense.factor * history.mult;
      var effects = factors.map(function (f) {
        return { key: f.key, delta: f.off ? null : (base - baseWith(f.key)) * defense.factor * history.mult };
      });
      var v0 = volumes[0], vm = multOf('vol', v0.field, null), vol = v0.volume.value * vm;
      // A role the context has moved is a role less certain than his log.
      var role = roleSpread(v0.field, vol) + (Math.abs(vm - 1) > CTX.BUMP_AT ? CTX.BUMP : 0);
      var cv = null, over = 0;
      if (spec.kind === 'yds') {
        var perSd = ((SD_PER[v0.rateKey] || {})[pos]) || 8;
        cv = spreadOf(recent, key, v0.field, pos, structuralCv(vol, v0.rate.value, perSd, role));
      } else if (spec.kind === 'count') {
        // Extra spread over Poisson, as 1/r of a negative binomial: the
        // volume's swing, plus its count noise for the volume stat itself.
        over = (key === 'rush_att' ? (VOL_PHI - 1) / Math.max(mean, 0.5) : 0) + role * role;
      }
      var dist = distribution(spec.kind, mean, cv, spec.family, over);
      var quote = null;
      if (spec.anytime) {
        var td = opts.props && opts.props.anytime_td;
        if (td) quote = { vendor: td.vendor, line: 0.5, over: td.odds, under: null };
      } else if (opts.props && opts.props.props) {
        quote = opts.props.props[spec.market] || null;
      }
      var median = dist.q(0.5);
      return {
        key: key, spec: spec, pos: pos, season: season,
        playerId: c ? c.player_id : null, playerName: opts.name || '',
        // base0: his own log alone, before any team context.
        cur: cur, prev: prev, base: base,
        base0: sum(volumes, function (v) { return v.volume.value * v.rate.value; }),
        volumes: volumes, context: context, effects: effects,
        defense: defense, history: history, mean: mean, median: median, cv: cv,
        dist: dist, lo: dist.q(0.1), hi: dist.q(0.9), quote: quote,
        defaultLine: quote ? quote.line : Math.max(0.5, Math.floor(median) + 0.5)
      };
    });
    return { pos: pos, stats: stats, context: context };
  }

  // -> { over, under, push } for a line.
  function chances(m, line) {
    var d = m.dist;
    if (d.discrete && Math.floor(line) === line) {
      var push = d.pmf(line);
      var under = d.cdf(line - 1);
      return { over: 1 - under - push, under: under, push: push };
    }
    var u = d.cdf(line);
    return { over: 1 - u, under: u, push: 0 };
  }


  /* ---------- drawing ---------- */

  function svgOpen(w, h, label) {
    return '<svg class="pp-svg" width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h +
      '" role="img" aria-label="' + esc(label) + '">';
  }

  function niceMax(x) {
    if (x <= 0) return 1;
    var p = Math.pow(10, Math.floor(Math.log10(x))), f = x / p;
    var steps = [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10];
    for (var i = 0; i < steps.length; i++) if (f <= steps[i] + 1e-9) return steps[i] * p;
    return 10 * p;
  }

  function ticks(max, count) {
    var raw = max / count, p = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / p;
    var step = (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p, out = [];
    for (var t = 0; t <= max + 1e-9; t += step) out.push(Math.round(t * 100) / 100);
    return out;
  }

  // A bar with its top corners rounded and its foot square on the baseline.
  function bar(x, y, w, h, r, cls, tip) {
    r = Math.min(r, w / 2, h);
    var d = h <= 0 ? '' : 'M' + x + ',' + (y + h) + 'V' + (y + r) + 'Q' + x + ',' + y + ' ' + (x + r) + ',' + y +
      'H' + (x + w - r) + 'Q' + (x + w) + ',' + y + ' ' + (x + w) + ',' + (y + r) + 'V' + (y + h) + 'Z';
    return d ? '<path class="' + cls + '" d="' + d + '" data-tip="' + esc(tip) + '"/>' : '';
  }

  function lineLabel(line) { return 'O/U ' + line; }

  // An over or under mark: ▲ or ▼, about a circle of radius r in size,
  // centered on its box so a stack of them lines up like dots.
  function mark(cls, cx, cy, r, over, tip) {
    var R = r * 1.25, w = R * Math.sqrt(3) / 2, d = over ? 1 : -1;
    var c = cy + d * R / 4;
    var path = 'M' + cx.toFixed(1) + ',' + (c - d * R).toFixed(1) +
      'L' + (cx + w).toFixed(1) + ',' + (c + d * R / 2).toFixed(1) +
      'L' + (cx - w).toFixed(1) + ',' + (c + d * R / 2).toFixed(1) + 'Z';
    return '<path class="' + cls + ' ' + (over ? 'is-over' : 'is-under') + '" d="' + path + '"' +
      (tip ? ' data-tip="' + esc(tip) + '"' : '') + '/>';
  }

  function glyph(over) { return over ? '▲' : '▼'; }

  function axis(x, xmax, y, width, pad, count) {
    var s = '<line class="pp-base" x1="' + pad.l + '" x2="' + (width - pad.r) + '" y1="' + y + '" y2="' + y + '"/>';
    ticks(xmax, count).forEach(function (t) {
      s += '<text class="pp-axis-t" x="' + x(t) + '" y="' + (y + 15) + '" text-anchor="middle">' + fmt(t) + '</text>';
    });
    return s;
  }

  function vline(x, y1, y2, label, flip) {
    return '<line class="pp-line" x1="' + x + '" x2="' + x + '" y1="' + y1 + '" y2="' + y2 + '"/>' +
      '<text class="pp-line-t" x="' + (x + (flip ? -4 : 4)) + '" y="' + (y1 + 8) + '"' + (flip ? ' text-anchor="end"' : '') + '>' + esc(label) + '</text>';
  }

  /* 1. The projection and what goes into it, on one axis. On top, the
   *    projection as N equally likely games (a quantile dotplot), each a
   *    circle -- blue over the line, orange under -- stacked by result, with
   *    the median's diamond on its 80% range under them. Below, one row per
   *    input: its real games as ▲ / ▼, and what it is worth beside the
   *    label. Circles are games that might
   *    happen and triangles games that did, so the two never share a shape.
   *    The line runs through every row. */
  function projectionChart(m, line, def, width) {
    var unit = m.spec.unit, base = m.base, key = m.key;
    var curSeason = m.cur;
    var rows = [];
    rows.push({
      label: 'This season', sub: 'n=' + curSeason.length + (m.prev.length ? ' + ' + (m.season - 1) + ' prior' : ''),
      dots: curSeason.map(function (g) { return { v: g[key] || 0, tip: 'Wk ' + g.week + ' ' + (g.home ? 'vs ' : '@ ') + g.opp + ': ' + (g[key] || 0) + ' ' + unit }; })
    });
    // The team context: his games with this week's lineup, and what the
    // context does to his baseline.
    var c = m.context;
    if (c) {
      var like = curSeason.filter(function (g) { return c.matched[g.game_id]; });
      rows.push({
        label: 'Team context', sub: (like.length ? 'n=' + like.length + ' like this week' : 'no games like this week') +
          ' · ' + signPct(m.base0 ? m.base / m.base0 : 1),
        dots: like.map(function (g) { return { v: g[key] || 0, tip: 'Wk ' + g.week + ' ' + (g.home ? 'vs ' : '@ ') + g.opp + ' with this week\'s lineup: ' + (g[key] || 0) + ' ' + unit }; })
      });
    }
    var h = m.history;
    rows.push({
      label: 'vs ' + def + ' career', sub: 'n=' + h.games.length + ' · ' + (h.share ? Math.round(h.share * 100) + '% say' : 'no say'),
      dots: h.games.map(function (e) {
        var g = e.g;
        return { v: g[key] || 0, old: g.season < m.season, tip: "'" + String(g.season).slice(2) + ' Wk ' + g.week + ': ' + (g[key] || 0) + ' ' + unit +
          (e.ratio != null ? ' (' + signPct(e.ratio) + ' vs his season avg)' : '') };
      })
    });
    var d = m.defense;
    rows.push({
      label: def + ' allowed', sub: d.pending ? 'awaiting build' : d.none ? 'no games yet' : 'n=' + d.n + ' · ×' + d.factor.toFixed(2),
      dots: d.games.map(function (g) {
        return { v: base * g.ratio, tip: 'Wk ' + g.week + ' vs ' + g.opp + ': allowed ' + fmt(g.allowed) + ', those players avg ' + fmt(g.exp) + ' (' + signPct(g.ratio) + ')' };
      })
    });

    // The projected games: N equally likely outcomes, fewer for touchdowns,
    // whose few whole numbers would otherwise stack into a tower.
    var N = width < 520 || m.spec.kind === 'td' ? 20 : 50;
    var qs = [];
    for (var qi = 0; qi < N; qi++) qs.push(m.dist.q((qi + 0.5) / N));

    var all = [line, m.hi, base, qs[N - 1]];
    rows.forEach(function (r) { r.dots.forEach(function (x) { all.push(x.v); }); });
    var xmax = niceMax(Math.max.apply(null, all) * 1.05);
    // Each row's name and count are a caption across its top left, so the
    // marks under it get the chart's full width.
    var CAP = 16;
    var pad = { l: 10, r: 12, t: 18, b: 22 }, rowH = CAP + 28;
    var pw = width - pad.l - pad.r;
    var x = function (v) { return pad.l + clamp(v, 0, xmax) / xmax * pw; };
    var caption = function (y, label, sub, cls) {
      return '<text class="pp-row-t' + (cls || '') + '" x="4" y="' + y + '">' + esc(label) +
        (sub ? '<tspan class="pp-row-s" dx="6">' + esc(sub) + '</tspan>' : '') + '</text>';
    };

    // Stack them: a count on its own value while each value has room for a
    // mark, otherwise into bins about half as many as the marks.
    var perValue = m.dist.discrete && pw / xmax >= 9;
    var bins = perValue ? xmax : Math.round(N / 2), binW = pw / bins;
    var r = clamp(binW / 2 - 1, 3.5, N === 20 ? 6 : 5), cell = 2 * r + 1.5;
    var stacks = {}, sims = [], over = 0;
    qs.forEach(function (q) {
      var b = perValue ? Math.round(q) : Math.min(bins - 1, Math.floor(q / xmax * bins));
      var k = stacks[b] = (stacks[b] || 0) + 1;
      if (q > line) over++;
      sims.push({ cx: perValue ? x(q) : x((b + 0.5) / bins * xmax), k: k, q: q, bin: b });
    });
    // A stack taller than MAX_ROWS -- touchdowns, where most of the games
    // are 0 -- folds into side-by-side columns when its bin has the room.
    var MAX_ROWS = 6, cols = Math.max(1, Math.floor(binW / cell));
    var tall = 0;
    Object.keys(stacks).forEach(function (b) {
      var n = stacks[b], c = Math.min(cols, Math.ceil(n / MAX_ROWS));
      stacks[b] = { n: n, cols: c, rows: Math.ceil(n / c) };
      tall = Math.max(tall, stacks[b].rows);
    });
    sims.forEach(function (d) {
      var st = stacks[d.bin], i = d.k - 1, col = i % st.cols, half = (st.cols - 1) / 2 * cell;
      d.k = Math.floor(i / st.cols) + 1;
      // A folded stack at 0 stays inside the plot.
      d.cx = Math.max(d.cx, pad.l + r + half) + (col - (st.cols - 1) / 2) * cell;
    });
    var projH = CAP + tall * cell + 22;

    var hgt = pad.t + projH + rows.length * rowH + pad.b;
    var s = svgOpen(width, hgt, over + ' of ' + N + ' projected games go over ' + line + '; median ' + fmt(m.median) + ' ' + unit);
    var yb = pad.t + CAP + tall * cell, yr = yb + 11;
    s += caption(pad.t + 11, 'Projection', '● = 1 in ' + N + ' games', ' is-proj');
    sims.forEach(function (d) {
      var isOver = d.q > line;
      s += '<circle class="pp-sim ' + (isOver ? 'is-over' : 'is-under') + '" cx="' + d.cx.toFixed(1) + '" cy="' + (yb - (d.k - 0.5) * cell).toFixed(1) +
        '" r="' + r + '" data-tip="' + esc('Projected game · ' + (isOver ? 'over' : 'under') + ' · ≈' + fmt(d.q) + ' ' + unit) + '"/>';
    });
    s += '<line class="pp-range" x1="' + x(m.lo) + '" x2="' + x(m.hi) + '" y1="' + yr + '" y2="' + yr + '" data-tip="' +
      esc('8 in 10 projected games: ' + fmt(m.lo) + '–' + fmt(m.hi) + ' ' + unit) + '"/>';
    var mx = x(m.median);
    s += '<path class="pp-diamond" d="M' + mx + ',' + (yr - 6) + 'L' + (mx + 6) + ',' + yr + 'L' + mx + ',' + (yr + 6) + 'L' + (mx - 6) + ',' + yr +
      'Z" data-tip="' + esc('Median ' + fmt(m.median) + ' ' + unit + ' (mean ' + fmt(m.mean) + ')') + '"/>';
    var top = pad.t + projH;
    s += '<line class="pp-rule" x1="0" x2="' + width + '" y1="' + top + '" y2="' + top + '"/>';

    rows.forEach(function (r, i) {
      var rt = top + i * rowH, y = rt + CAP + 15;
      if (i % 2 === 1) s += '<rect class="pp-band" x="0" y="' + rt + '" width="' + width + '" height="' + rowH + '"/>';
      s += caption(rt + 13, r.label, r.sub);
      // A season of games piles up on a phone, so a dot that would sit on
      // another steps up or down a lane (a small beeswarm).
      var lanes = [0, -5, 5, -10, 10], placed = [];
      r.dots.slice().sort(function (a, b) { return a.v - b.v; }).forEach(function (dt) {
        var cx = x(dt.v), lane = 0;
        for (var li = 0; li < lanes.length; li++) {
          if (!placed.some(function (p) { return p.lane === li && Math.abs(p.x - cx) < 9.5; })) { lane = li; break; }
          lane = li;
        }
        placed.push({ x: cx, lane: lane });
        s += mark('pp-ev-dot' + (dt.old ? ' is-old' : ''), cx, y + lanes[lane], 4.5, dt.v > line, dt.tip);
      });
    });
    var y0 = hgt - pad.b;
    s += axis(x, xmax, y0, width, pad, width < 420 ? 3 : 5);
    s += vline(x(line), pad.t - 12, y0, lineLabel(line), x(line) > width - 60);
    return s + '</svg>';
  }

  /* 2. The game log against the line: one bar per game this season, with
   *    last season's tail in front when this one is short. Blue filled is
   *    over, orange is under, the value printed on each; a game against this
   *    defense is ringed. Volume runs underneath. */
  // The games the log draws: this season, last season's tail in front when
  // this one is short, and no more than fit at about 30px a game -- on a
  // phone late in the season that is the latest eleven or so.
  var LOG_PAD = { l: 8, r: 50, t: 18, b: 34 };
  function logGames(m, width) {
    var fit = Math.max(6, Math.floor((width - LOG_PAD.l - LOG_PAD.r) / 30));
    var cur = m.cur.slice(0, fit).reverse();
    var need = Math.max(0, 6 - cur.length);
    var prev = need ? m.prev.slice(0, need).reverse() : [];
    return {
      games: prev.map(function (g) { return { g: g, old: true }; }).concat(cur.map(function (g) { return { g: g, old: false }; })),
      prev: prev.length, cur: cur.length, cut: m.cur.length - cur.length
    };
  }

  function gameLog(m, line, def, width) {
    var key = m.key, unit = m.spec.unit, volField = m.spec.parts[m.spec.parts.length > 1 ? 1 : 0][0];
    var picked = logGames(m, width), games = picked.games;
    var prev = { length: picked.prev }, cur = { length: picked.cur };
    if (!games.length) return '';
    // The right gutter holds the line's label, clear of the last bar.
    var pad = LOG_PAD, h = 150;
    var pw = width - pad.l - pad.r, slot = pw / games.length;
    var bw = Math.min(30, slot * 0.68);
    var vmax = Math.max(line, Math.max.apply(null, games.map(function (x) { return x.g[key] || 0; }))) * 1.12 || 1;
    var y0 = h - pad.b, ph = y0 - pad.t;
    var y = function (v) { return y0 - v / vmax * ph; };
    var s = svgOpen(width, h, 'Game log against ' + line);
    games.forEach(function (o, i) {
      var g = o.g, v = g[key] || 0, cx = pad.l + slot * (i + 0.5);
      var cls = 'pp-bar ' + (v > line ? 'is-over' : v === line ? 'is-push' : 'is-under') + (o.old ? ' is-old' : '');
      var tip = (o.old ? "'" + String(g.season).slice(2) + ' ' : '') + 'Wk ' + g.week + ' ' + (g.home ? 'vs ' : '@ ') + g.opp + ': ' + v + ' ' + unit +
        ' · ' + (g[volField] || 0) + ' ' + (VOL_LABEL[volField] || '');
      // The whole column is the tap target, not just the bar.
      s += '<rect class="pp-hit" x="' + (pad.l + slot * i) + '" y="' + pad.t + '" width="' + slot + '" height="' + (h - pad.t) + '" data-tip="' + esc(tip) + '"/>';
      s += bar(cx - bw / 2, y(v), bw, y0 - y(v), 4, cls, tip);
      if (v === 0) s += '<rect class="' + cls + '" x="' + (cx - bw / 2) + '" y="' + (y0 - 1.5) + '" width="' + bw + '" height="1.5" data-tip="' + esc(tip) + '"/>';
      if (g.opp === def) s += '<rect class="pp-ring" x="' + (cx - bw / 2 - 3) + '" y="' + (y(v) - 3) + '" width="' + (bw + 6) + '" height="' + (y0 - y(v) + 3) + '" rx="5"/>';
      // The glyph says over or under where a bar ends close to the line.
      s += '<text class="pp-val" x="' + cx + '" y="' + (y(v) - 4) + '" text-anchor="middle">' +
        (v === line ? '' : '<tspan class="pp-glyph">' + glyph(v > line) + '</tspan>') + fmt(v) + '</text>';
      s += '<text class="pp-axis-t' + (g.opp === def ? ' is-hi' : '') + '" x="' + cx + '" y="' + (y0 + 13) + '" text-anchor="middle">' + esc(g.opp) + '</text>';
      s += '<text class="pp-vol" x="' + cx + '" y="' + (y0 + 26) + '" text-anchor="middle">' + (g[volField] || 0) +
        (slot > 34 ? ' ' + (VOL_LABEL[volField] || '') : '') + '</text>';
    });
    if (prev.length && cur.length) {
      var xd = pad.l + slot * prev.length;
      s += '<line class="pp-rule" x1="' + xd + '" x2="' + xd + '" y1="' + pad.t + '" y2="' + y0 + '"/>';
      s += '<text class="pp-axis-t" x="' + (xd - 4) + '" y="' + (pad.t - 6) + '" text-anchor="end">' + (m.season - 1) + '</text>';
      s += '<text class="pp-axis-t" x="' + (xd + 4) + '" y="' + (pad.t - 6) + '">' + m.season + '</text>';
    }
    s += '<line class="pp-base" x1="' + pad.l + '" x2="' + (width - pad.r) + '" y1="' + y0 + '" y2="' + y0 + '"/>';
    s += '<line class="pp-line" x1="' + pad.l + '" x2="' + (width - pad.r + 4) + '" y1="' + y(line) + '" y2="' + y(line) + '"/>';
    s += '<text class="pp-line-t" x="' + (width - pad.r + 7) + '" y="' + (y(line) + 4) + '">' + line + '</text>';
    return s + '</svg>';
  }

  /* 3. The defense, by game: each stat's allowed-vs-expected, as a cell
   *    tinted toward blue (gave up more than those players usually get)
   *    or orange (less), its percentage printed in it. */
  function defensePanel(model, def) {
    var stats = model.stats.filter(function (m) { return m.spec.kind !== 'td' || m.key === 'tot_td'; });
    var first = model.stats[0].defense;
    if (first.pending) {
      return '<p class="pp-def-note">The ' + esc(def) + ' allowed-vs-expected numbers arrive with the next weekly defense build, so the defense counts as neutral for now.</p>';
    }
    if (first.none || !first.n) {
      return '<p class="pp-def-note">' + esc(def) + ' has no completed games this season, so the defense counts as neutral.</p>';
    }
    var primary = model.stats[0];
    var f = primary.defense.factor;
    var edge = f >= 1.06 ? ['Soft matchup', 'is-over'] : f <= 0.94 ? ['Tough matchup', 'is-under'] : ['Neutral matchup', ''];
    var weeks = first.games;
    var html = '<div class="pp-def-head"><span class="pp-edge ' + edge[1] + '">' + edge[0] + '</span>' +
      '<span>Opposing ' + esc(model.pos) + 's: ' + signPct(primary.defense.raw) + ' ' + esc(primary.spec.label.toLowerCase()) +
      ' over their norm · ' + signPct(f) + ' used</span></div>';
    html += '<div class="pp-def-scroll"><table class="pp-def"><thead><tr><th>Wk</th><th>Opp</th>';
    // A phone gets the short names, so five stats fit across 320px.
    stats.forEach(function (m) {
      html += '<th><span class="pp-long">' + esc(m.spec.label) + '</span><span class="pp-short">' + esc(m.spec.short) + '</span></th>';
    });
    html += '</tr></thead><tbody>';
    weeks.forEach(function (w, i) {
      html += '<tr><td class="num">' + esc(w.week) + '</td><td>' + esc(w.opp) + '</td>';
      stats.forEach(function (m) {
        var g = m.defense.games.filter(function (x) { return x.week === w.week; })[0];
        html += g ? cell(g.ratio, fmt(g.allowed) + ' allowed vs ' + fmt(g.exp) + ' expected') : '<td class="num is-zero">–</td>';
      });
      html += '</tr>';
    });
    html += '</tbody><tfoot><tr><td colspan="2">Season</td>';
    stats.forEach(function (m) { html += cell(m.defense.raw, 'All games: ' + signPct(m.defense.raw)); });
    html += '</tr><tr><td colspan="2">Used</td>';
    stats.forEach(function (m) { html += cell(m.defense.factor, 'Regressed toward even by ' + m.defense.k + ' games'); });
    html += '</tr></tfoot></table></div>';
    // The key is the cells' own scale, so a deep orange cell on the dark
    // surface (which reads brown) matches something in it.
    var ramp = function (cls, tints) {
      return tints.map(function (t) { return '<span class="pp-sw pp-cell ' + cls + '" style="--tint:' + t + '%"></span>'; }).join('');
    };
    html += '<p class="pp-legend"><span>allowed less than usual</span>' + ramp('is-under', [55, 33, 12]) +
      '<span class="pp-sw pp-cell"></span>' + ramp('is-over', [12, 33, 55]) + '<span>more</span></p>';
    html += '<section class="pp-notes"><h4 class="pp-h">How to read this table</h4><p>Each cell compares what this defense allowed the ' + esc(model.pos) + 's it faced that week with what ' +
      'those same players average in their other games: +20% means they got 20% more than usual. ' +
      'Deeper color is a bigger gap. <b>Season</b> is every game together. <b>Used</b> is what the projection applies: ' +
      'a defense\'s numbers swing a lot week to week and barely carry over, so the season figure is pulled most of the way back to ±0%.</p></section>';
    return html;
  }

  function cell(ratio, tip) {
    var dlt = clamp(ratio - 1, -0.5, 0.5);
    var tint = Math.round(Math.abs(dlt) / 0.5 * 55);
    var cls = dlt > 0.02 ? 'is-over' : dlt < -0.02 ? 'is-under' : '';
    // A big blowout reads better, and fits a phone column, as a multiple.
    var text = ratio >= 2.5 ? '×' + (ratio >= 10 ? Math.round(ratio) : r1(ratio)) : signPct(ratio);
    return '<td class="num pp-cell ' + cls + '" style="--tint:' + tint + '%" data-tip="' + esc(tip + ' (' + signPct(ratio) + ')') + '">' + text + '</td>';
  }

  /* ---------- the card ---------- */

  /* The bar over the charts: the line and its − / +, then what he projects
   * to, the model's chance of the over at that line, and the 80% range --
   * one row on a wide screen, two on a phone. A touchdown's median is nearly
   * always 0, which says nothing, so it shows the expected count. */
  // The chance of the over on the site's red/green scale: 55%+ green, 60%+
  // dark green, 45% and under red, 40% and under dark red. Read off the
  // rounded figure, so the color always agrees with the number printed.
  function chanceHeat(p) {
    var v = Math.round(p * 100);
    return v >= 60 ? 'is-good-2' : v >= 55 ? 'is-good-1' : v <= 40 ? 'is-bad-2' : v <= 45 ? 'is-bad-1' : '';
  }

  function topBar(m, line) {
    var c = chances(m, line), td = m.spec.kind === 'td', q = m.quote;
    var stat = function (v, k, tip, heat) {
      return '<span class="pp-top-stat" data-tip="' + esc(tip) + '"><b' + (heat ? ' class="pp-heat ' + heat + '"' : '') + '>' +
        esc(v) + '</b> ' + esc(k) + '</span>';
    };
    var html = '<div class="pp-top"><div class="pp-linectl" role="group" aria-label="Line">' +
      '<button type="button" class="dd-btn pp-step" data-step="-1" aria-label="Lower the line">−</button>' +
      '<span class="pp-line-v">' + lineLabel(line) + '</span>' +
      '<button type="button" class="dd-btn pp-step" data-step="1" aria-label="Raise the line">+</button>' +
      '<span class="pp-src" title="' + esc(q ? 'The book\'s line' : 'No book line yet: the line is the projection\'s') + '">' +
      (q ? BOOK[q.vendor] : 'model') + '</span>' +
      (q && q.line !== line ? '<button type="button" class="dd-btn pp-reset">Book ' + q.line + '</button>' : '') + '</div>';
    // The three numbers wrap as one, so a phone keeps them on one row.
    html += '<span class="pp-top-stats">';
    html += td
      ? stat((Math.round(m.mean * 100) / 100).toFixed(2), 'exp. TDs', 'How many touchdowns the model expects.')
      : stat(fmt(m.median), 'proj.', 'The middle outcome: half his projected games land above it, half below.');
    html += stat(pct(c.over), m.spec.anytime ? 'to score' : glyph(true) + ' over' + (c.push ? ' · push ' + pct(c.push) : ''),
      'The model\'s chance he clears the line.', chanceHeat(c.over));
    if (!td) html += '<span class="pp-top-range" data-tip="8 in 10 of his projected games land in this range.">80%: ' +
      fmt(m.lo) + '–' + fmt(m.hi) + '</span>';
    return html + '</span></div>';
  }


  // The symbols the card's charts share.
  function key(def) {
    function sw(inner, w) { return '<svg width="' + (w || 14) + '" height="14" viewBox="0 0 ' + (w || 14) + ' 14" aria-hidden="true">' + inner + '</svg>'; }
    var items = [
      [sw('<circle class="pp-sim is-over" cx="4" cy="7" r="3.5"/><circle class="pp-sim is-under" cx="12" cy="7" r="3.5"/>', 16), 'Projected game, over / under'],
      [sw(mark('pp-key-sw', 7, 7, 5, true)), 'Real game, over'],
      [sw(mark('pp-key-sw', 7, 7, 5, false)), 'Real game, under'],
      [sw('<line class="pp-line" x1="7" x2="7" y1="0" y2="14"/>'), 'The line'],
      [sw('<line class="pp-range" x1="1" x2="23" y1="7" y2="7"/><path class="pp-diamond" d="M12,1L18,7L12,13L6,7Z"/>', 24), 'Projection, 80% range'],
      [sw('<rect class="pp-ring" x="1.5" y="1.5" width="11" height="11" rx="3"/>'), 'vs ' + esc(def)],
      [sw(mark('pp-key-sw is-old', 7, 7, 5, false)), 'Earlier season']
    ];
    return '<div class="pp-key" aria-label="Key">' + items.map(function (i) { return '<span>' + i[0] + i[1] + '</span>'; }).join('') + '</div>';
  }

  // `context` is contextPanel's html, under the chart it explains.
  function card(m, line, def, width, context) {
    m.defense.def = def;
    var html = topBar(m, line);
    html += '<h4 class="pp-h">Projection and what goes into it</h4>' + projectionChart(m, line, def, width);
    html += context || '';
    var cut = logGames(m, width).cut;
    html += '<h4 class="pp-h">Game log' + (cut ? ' <span class="pp-h-note">latest ' + (m.cur.length - cut) + ' of ' + m.cur.length + '</span>' : '') + '</h4>' +
      gameLog(m, line, def, width);
    // The key to every chart's symbols, once they have been seen.
    html += key(def);
    return html;
  }

  /* ---------- team context ----------
   * What moved him off his own log this week, one factor a row, each worth
   * the projection with it less the projection without it, in the stat's
   * units. Everyone sees it; an editor also gets each factor's switch and
   * the Adjust form (adjustForm). opts: { canAdjust, adjust: { updated_by,
   * updated_at } | null }. */
  function contextPanel(m, opts) {
    var c = m.context;
    if (!c) return '';
    opts = opts || {};
    var td = m.spec.kind === 'td', unit = m.spec.unit;
    var num = function (x) { return td ? (Math.round(x * 100) / 100).toFixed(2) : fmt(x); };
    var own = m.base0 * m.defense.factor * m.history.mult;
    var html = '<section class="pp-ctx" aria-labelledby="pp-ctx-h"><div class="pp-ctx-head"><h4 class="pp-h" id="pp-ctx-h">Team context</h4>' +
      (opts.canAdjust ? '<button type="button" class="dd-btn pp-adj-open" aria-expanded="false" aria-controls="pp-adj">Adjust</button>' : '') + '</div>';
    if (c.out) {
      html += '<p class="pp-ctx-out">Listed out this week' + (c.statusWhy ? ': ' + esc(c.statusWhy) : '') +
        '. The projection is what he would do if he played.</p>';
    }
    html += '<p class="pp-ctx-sum">His own games project <b>' + num(own) + '</b> ' + esc(unit) + '; with ' + esc(c.team) +
      '’s lineup, pace and script this week, <b>' + num(m.mean) + '</b>.</p>';
    html += '<ul class="pp-ctx-list">' + c.factors.map(function (f, i) {
      var d = (m.effects[i] || {}).delta, flat = d == null || Math.abs(d) < (td ? 0.005 : 0.05);
      var cls = f.off || flat ? '' : d > 0 ? ' is-over' : ' is-under';
      var val = f.off ? 'off' : flat ? '±0' : glyph(d > 0) + ' ' + (d > 0 ? '+' : '−') + num(Math.abs(d));
      return '<li class="pp-ctx-f' + (f.off ? ' is-off' : '') + '">' +
        '<span class="pp-ctx-l">' + esc(f.label) + '<span class="pp-chip is-' + f.source + '">' + f.source + '</span></span>' +
        '<span class="pp-ctx-d' + cls + '">' + val + '</span>' +
        (opts.canAdjust ? '<button type="button" class="dd-btn pp-ctx-tog" data-factor="' + esc(f.offKey) + '" aria-pressed="' + !f.off + '">' +
          (f.off ? 'Turn on' : 'Turn off') + '</button>' : '') +
        '<span class="pp-ctx-why">' + esc(f.why) + '</span></li>';
    }).join('') + '</ul>';
    var a = opts.adjust;
    html += '<p class="pp-ctx-note">Each row is the projection with it less without it; together they compound.' +
      (a && a.updated_by ? ' Adjusted by ' + esc(a.updated_by) + (a.updated_at ? ' · ' + esc(new Date(a.updated_at).toLocaleString([], {
        weekday: 'short', hour: 'numeric', minute: '2-digit' })) : '') + '.' : '') + '</p>';
    if (opts.canAdjust) html += '<div class="pp-adj" id="pp-adj" hidden></div>';
    return html + '</section>';
  }

  /* The editor's form: this week's status for each teammate, his own
   * shares and multipliers, the game, the line. `data` is the team's saved
   * adjustments; empty fields fall back to the model, whose values are the
   * placeholders. */
  function adjustForm(m, data, olAuto) {
    var c = m.context;
    data = data || {};
    var st = data.status || {}, me = ((data.players || {})[String(m.playerId)]) || {}, g = data.game || {};
    var pctv = function (v) { return v == null ? '' : Math.round(v * 100); };
    var field = function (name, label, val, ph, attrs) {
      return '<label class="pp-adj-field"><span>' + esc(label) + '</span><input class="pp-input" type="number" name="' + name + '" value="' +
        esc(val == null ? '' : val) + '" placeholder="' + esc(ph == null ? '' : ph) + '" ' + (attrs || '') + '></label>';
    };
    var mates = c.mates.filter(function (t) {
      return t.key || t.share.rush_att >= 0.03 || t.share.targets >= 0.03 || st[t.id] || (t.st.row && t.st.row.status);
    }).sort(function (a, b) {
      return (b.share.rush_att + b.share.targets + b.share.pass_att) - (a.share.rush_att + a.share.targets + a.share.pass_att);
    });
    var opt = function (v, label, cur) { return '<option value="' + v + '"' + (cur === v ? ' selected' : '') + '>' + label + '</option>'; };
    var html = '<form class="pp-adj-form" novalidate>';
    html += '<fieldset><legend>Teammates this week</legend><div class="pp-adj-mates">' + mates.map(function (t) {
      var rep = t.st.row && t.st.row.status ? t.st.row.status : t.gone ? 'not playing lately' : 'active';
      return '<label class="pp-adj-mate"><span>' + esc(t.name) + ' <span class="pp-pos">' + esc(t.pos) + '</span></span>' +
        '<select class="dd-btn" name="status:' + esc(t.id) + '">' + opt('', 'Report: ' + rep, st[t.id] || '') + opt('in', 'Playing', st[t.id]) +
        opt('questionable', 'Questionable', st[t.id]) + opt('doubtful', 'Doubtful', st[t.id]) + opt('out', 'Out', st[t.id]) + '</select></label>';
    }).join('') + '</div></fieldset>';
    html += '<fieldset><legend>' + esc(m.playerName || 'Him') + '</legend><div class="pp-adj-grid">' +
      field('car_share', 'Carry share %', pctv(me.car_share), Math.round(c.share.car * 100), 'min="0" max="100" step="1"') +
      field('tgt_share', 'Target share %', pctv(me.tgt_share), Math.round(c.share.tgt * 100), 'min="0" max="100" step="1"') +
      field('snap', 'Snap share %', pctv(me.snap), c.snap != null ? Math.round(c.snap * 100) : '', 'min="0" max="100" step="1"') +
      field('vol_mult', 'Volume ×', me.vol_mult, '1.00', 'min="0.25" max="4" step="0.05"') +
      field('eff_mult', 'Per-play ×', me.eff_mult, '1.00', 'min="0.5" max="2" step="0.05"') +
      '<label class="pp-adj-field pp-adj-note"><span>Note</span><input class="pp-input" type="text" name="note" maxlength="200" value="' +
      esc(me.note || '') + '" placeholder="Why, for whoever reads it"></label></div>';
    var own = m.context.factors.filter(function (f) { return f.key === 'status'; })[0];
    html += '<label class="pp-adj-mate"><span>His status</span><select class="dd-btn" name="status:' + esc(String(m.playerId)) + '">' +
      opt('', 'Report' + (own ? ': ' + esc(own.why.split(' ')[0]) : ''), st[m.playerId] || '') + opt('in', 'Playing', st[m.playerId]) +
      opt('questionable', 'Questionable', st[m.playerId]) + opt('doubtful', 'Doubtful', st[m.playerId]) + opt('out', 'Out', st[m.playerId]) +
      '</select></label></fieldset>';
    html += '<fieldset><legend>The game</legend><div class="pp-adj-grid">' +
      field('spread', c.team + ' spread', g.spread, c.game.spread, 'min="-40" max="40" step="0.5"') +
      field('total', 'Total', g.total, c.game.total, 'min="20" max="90" step="0.5"') +
      field('plays', c.team + ' plays', g.plays, c.game.plays, 'min="40" max="95" step="1"') +
      field('ol_out', 'Linemen out', data.ol_out, olAuto, 'min="0" max="5" step="1"') + '</div></fieldset>';
    html += '<div class="pp-adj-actions"><button type="submit" class="dd-btn pp-adj-save">Save for ' + esc(c.team) + '</button>' +
      '<button type="button" class="dd-btn pp-adj-clear">Clear ' + esc(c.team) + '’s adjustments</button>' +
      '<span class="pp-adj-msg" role="status"></span></div>';
    return html + '<p class="pp-adj-hint">Saved for everyone, for this week only. A teammate’s status moves every ' + esc(c.team) +
      ' player’s projection; the rest are his own. Blank is the model’s value, shown greyed.</p></form>';
  }

  /* How to read the three charts, as plain paragraphs under them: the
   * charts come first, the explanation for whoever wants it after. */
  function notes(m, def, width) {
    var unit = { pass_att: 'pass attempts', rush_att: 'carries', targets: 'targets' }[m.spec.parts[m.spec.parts.length > 1 ? 1 : 0][0]];
    var cut = logGames(m, width).cut;
    var p = function (head, text) { return '<p><b>' + head + '.</b> ' + text + '</p>'; };
    return '<section class="pp-notes"><h4 class="pp-h">How to read these charts</h4>' +
      p('Projection and what goes into it', 'All on one scale, with the line through every row. ' +
        '<i>Projection</i> is ' + (width < 520 || m.spec.kind === 'td' ? 20 : 50) + ' equally likely games the model expects, one circle each, ' +
        'stacked by result: blue clears the line, orange falls short, and the share that are blue is the chance of the over. ' +
        'The diamond under them is the median and its bar spans 8 in 10 games. The fewer ' + esc(unit) + ' he gets, the wider the ' +
        'spread: one long play decides more of a game, and a smaller role swings more with game script and who else is healthy. ' +
        'The rows below are what built it, each ▲ or ▼ a real game over or under the line. <i>This season</i> is the baseline: recent games count most, ' +
        'last season fills in early. ' +
        (m.context ? '<i>Team context</i> is his games with the lineup ' + esc(m.context.team) + ' expects this week, and how far the team around him ' +
          'moves the baseline: his share of the carries and targets, who is in and out, the pace and the spread. ' : '') +
        '<i>vs ' + esc(def) + ' career</i> gets a few percent of say at most, because a handful of games years apart predict little. ' +
        '<i>' + esc(def) + ' allowed</i> puts each of its games in his terms: his baseline × how far that week\'s ' + esc(m.pos) +
        's went over or under their norm; ×1.00 is an average defense. Marks that would overlap are stacked a step apart.') +
      p('Game log', 'His games, oldest to newest, against the line, with ' + esc(unit) + ' under each. A ringed bar is a game against ' +
        'this defense; an outlined one is from last season.' +
        (cut ? ' The screen fits his latest ' + (m.cur.length - cut) + '; the projection uses all ' + m.cur.length + '.' : '')) +
      '</section>';
  }

  /* ---------- hover ----------
   * One tooltip for the whole projection: any mark with a data-tip shows
   * it, on hover or on tap. */
  function bindTips(root) {
    if (root._ppTips) return;
    root._ppTips = true;
    var tip = document.createElement('div');
    tip.className = 'pp-tip';
    tip.hidden = true;
    document.body.appendChild(tip);
    function show(e) {
      var t = e.target.closest ? e.target.closest('[data-tip]') : null;
      if (!t || !root.contains(t)) { tip.hidden = true; return; }
      tip.textContent = t.getAttribute('data-tip');
      tip.hidden = false;
      var b = t.getBoundingClientRect();
      var w = tip.offsetWidth;
      tip.style.left = clamp(b.left + b.width / 2 - w / 2, 8, window.innerWidth - w - 8) + 'px';
      tip.style.top = (b.top + window.scrollY - tip.offsetHeight - 8) + 'px';
    }
    root.addEventListener('pointerover', show);
    root.addEventListener('pointerdown', show);
    root.addEventListener('pointerleave', function () { tip.hidden = true; });
    document.addEventListener('pointerdown', function (e) { if (!root.contains(e.target)) tip.hidden = true; });
    window.addEventListener('scroll', function () { tip.hidden = true; }, { passive: true });
  }

  global.PlayerProjection = {
    STATS: STATS,
    BY_POS: BY_POS,
    build: build,
    chances: chances,
    card: card,
    notes: notes,
    defensePanel: defensePanel,
    contextPanel: contextPanel,
    adjustForm: adjustForm,
    bindTips: bindTips
  };
})(window);
