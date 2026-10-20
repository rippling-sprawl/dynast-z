// One player's projected stat line against one defense, and the charts that
// show where it came from. For /football/player-vs-defense.
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
// read it. Styles: .pvd-* in styles/primary/player-vs-defense.css.

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

  /* opts: { games (career, newest first), pos, season, def, defDoc, props }
   * -> { pos, stats: [model per stat] } or { error } */
  function build(opts) {
    var pos = opts.pos, season = opts.season;
    var cur = opts.games.filter(function (g) { return g.season === season; });
    var prev = opts.games.filter(function (g) { return g.season === season - 1; });
    if (!cur.length && !prev.length) return { error: 'No games this season or last to project from.' };
    var recent = cur.concat(prev);
    var stats = (BY_POS[pos] || []).map(function (key) {
      var spec = STATS[key];
      var base = 0, volumes = [];
      spec.parts.forEach(function (p) {
        var v = volumeOf(cur, prev, p[0]);
        var r = rateOf(recent, p[1], pos);
        base += v.value * r.value;
        volumes.push({ field: p[0], volume: v, rate: r, rateKey: p[1] });
      });
      var defense = defenseOf(opts.defDoc, pos, key, spec.kind);
      var history = historyOf(opts.games, opts.def, key, season);
      var mean = base * defense.factor * history.mult;
      var v0 = volumes[0], vol = v0.volume.value;
      var role = roleSpread(v0.field, vol);
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
        cur: cur, prev: prev, base: base, volumes: volumes,
        defense: defense, history: history, mean: mean, median: median, cv: cv,
        dist: dist, lo: dist.q(0.1), hi: dist.q(0.9), quote: quote,
        defaultLine: quote ? quote.line : Math.max(0.5, Math.floor(median) + 0.5)
      };
    });
    return { pos: pos, stats: stats };
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
    return '<svg class="pvd-svg" width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h +
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
    var s = '<line class="pvd-base" x1="' + pad.l + '" x2="' + (width - pad.r) + '" y1="' + y + '" y2="' + y + '"/>';
    ticks(xmax, count).forEach(function (t) {
      s += '<text class="pvd-axis-t" x="' + x(t) + '" y="' + (y + 15) + '" text-anchor="middle">' + fmt(t) + '</text>';
    });
    return s;
  }

  function vline(x, y1, y2, label, flip) {
    return '<line class="pvd-line" x1="' + x + '" x2="' + x + '" y1="' + y1 + '" y2="' + y2 + '"/>' +
      '<text class="pvd-line-t" x="' + (x + (flip ? -4 : 4)) + '" y="' + (y1 + 8) + '"' + (flip ? ' text-anchor="end"' : '') + '>' + esc(label) + '</text>';
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
      return '<text class="pvd-row-t' + (cls || '') + '" x="4" y="' + y + '">' + esc(label) +
        (sub ? '<tspan class="pvd-row-s" dx="6">' + esc(sub) + '</tspan>' : '') + '</text>';
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
      s += '<circle class="pvd-sim ' + (isOver ? 'is-over' : 'is-under') + '" cx="' + d.cx.toFixed(1) + '" cy="' + (yb - (d.k - 0.5) * cell).toFixed(1) +
        '" r="' + r + '" data-tip="' + esc('Projected game · ' + (isOver ? 'over' : 'under') + ' · ≈' + fmt(d.q) + ' ' + unit) + '"/>';
    });
    s += '<line class="pvd-range" x1="' + x(m.lo) + '" x2="' + x(m.hi) + '" y1="' + yr + '" y2="' + yr + '" data-tip="' +
      esc('8 in 10 projected games: ' + fmt(m.lo) + '–' + fmt(m.hi) + ' ' + unit) + '"/>';
    var mx = x(m.median);
    s += '<path class="pvd-diamond" d="M' + mx + ',' + (yr - 6) + 'L' + (mx + 6) + ',' + yr + 'L' + mx + ',' + (yr + 6) + 'L' + (mx - 6) + ',' + yr +
      'Z" data-tip="' + esc('Median ' + fmt(m.median) + ' ' + unit + ' (mean ' + fmt(m.mean) + ')') + '"/>';
    var top = pad.t + projH;
    s += '<line class="pvd-rule" x1="0" x2="' + width + '" y1="' + top + '" y2="' + top + '"/>';

    rows.forEach(function (r, i) {
      var rt = top + i * rowH, y = rt + CAP + 15;
      if (i % 2 === 1) s += '<rect class="pvd-band" x="0" y="' + rt + '" width="' + width + '" height="' + rowH + '"/>';
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
        s += mark('pvd-ev-dot' + (dt.old ? ' is-old' : ''), cx, y + lanes[lane], 4.5, dt.v > line, dt.tip);
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
      var cls = 'pvd-bar ' + (v > line ? 'is-over' : v === line ? 'is-push' : 'is-under') + (o.old ? ' is-old' : '');
      var tip = (o.old ? "'" + String(g.season).slice(2) + ' ' : '') + 'Wk ' + g.week + ' ' + (g.home ? 'vs ' : '@ ') + g.opp + ': ' + v + ' ' + unit +
        ' · ' + (g[volField] || 0) + ' ' + (VOL_LABEL[volField] || '');
      // The whole column is the tap target, not just the bar.
      s += '<rect class="pvd-hit" x="' + (pad.l + slot * i) + '" y="' + pad.t + '" width="' + slot + '" height="' + (h - pad.t) + '" data-tip="' + esc(tip) + '"/>';
      s += bar(cx - bw / 2, y(v), bw, y0 - y(v), 4, cls, tip);
      if (v === 0) s += '<rect class="' + cls + '" x="' + (cx - bw / 2) + '" y="' + (y0 - 1.5) + '" width="' + bw + '" height="1.5" data-tip="' + esc(tip) + '"/>';
      if (g.opp === def) s += '<rect class="pvd-ring" x="' + (cx - bw / 2 - 3) + '" y="' + (y(v) - 3) + '" width="' + (bw + 6) + '" height="' + (y0 - y(v) + 3) + '" rx="5"/>';
      // The glyph says over or under where a bar ends close to the line.
      s += '<text class="pvd-val" x="' + cx + '" y="' + (y(v) - 4) + '" text-anchor="middle">' +
        (v === line ? '' : '<tspan class="pvd-glyph">' + glyph(v > line) + '</tspan>') + fmt(v) + '</text>';
      s += '<text class="pvd-axis-t' + (g.opp === def ? ' is-hi' : '') + '" x="' + cx + '" y="' + (y0 + 13) + '" text-anchor="middle">' + esc(g.opp) + '</text>';
      s += '<text class="pvd-vol" x="' + cx + '" y="' + (y0 + 26) + '" text-anchor="middle">' + (g[volField] || 0) +
        (slot > 34 ? ' ' + (VOL_LABEL[volField] || '') : '') + '</text>';
    });
    if (prev.length && cur.length) {
      var xd = pad.l + slot * prev.length;
      s += '<line class="pvd-rule" x1="' + xd + '" x2="' + xd + '" y1="' + pad.t + '" y2="' + y0 + '"/>';
      s += '<text class="pvd-axis-t" x="' + (xd - 4) + '" y="' + (pad.t - 6) + '" text-anchor="end">' + (m.season - 1) + '</text>';
      s += '<text class="pvd-axis-t" x="' + (xd + 4) + '" y="' + (pad.t - 6) + '">' + m.season + '</text>';
    }
    s += '<line class="pvd-base" x1="' + pad.l + '" x2="' + (width - pad.r) + '" y1="' + y0 + '" y2="' + y0 + '"/>';
    s += '<line class="pvd-line" x1="' + pad.l + '" x2="' + (width - pad.r + 4) + '" y1="' + y(line) + '" y2="' + y(line) + '"/>';
    s += '<text class="pvd-line-t" x="' + (width - pad.r + 7) + '" y="' + (y(line) + 4) + '">' + line + '</text>';
    return s + '</svg>';
  }

  /* 3. The defense, by game: each stat's allowed-vs-expected, as a cell
   *    tinted toward blue (gave up more than those players usually get)
   *    or orange (less), its percentage printed in it. */
  function defensePanel(model, def) {
    var stats = model.stats.filter(function (m) { return m.spec.kind !== 'td' || m.key === 'tot_td'; });
    var first = model.stats[0].defense;
    if (first.pending) {
      return '<p class="pvd-def-note">The ' + esc(def) + ' allowed-vs-expected numbers arrive with the next weekly defense build, so the defense counts as neutral for now.</p>';
    }
    if (first.none || !first.n) {
      return '<p class="pvd-def-note">' + esc(def) + ' has no completed games this season, so the defense counts as neutral.</p>';
    }
    var primary = model.stats[0];
    var f = primary.defense.factor;
    var edge = f >= 1.06 ? ['Soft matchup', 'is-over'] : f <= 0.94 ? ['Tough matchup', 'is-under'] : ['Neutral matchup', ''];
    var weeks = first.games;
    var html = '<div class="pvd-def-head"><span class="pvd-edge ' + edge[1] + '">' + edge[0] + '</span>' +
      '<span>Opposing ' + esc(model.pos) + 's: ' + signPct(primary.defense.raw) + ' ' + esc(primary.spec.label.toLowerCase()) +
      ' over their norm · ' + signPct(f) + ' used</span></div>';
    html += '<div class="pvd-def-scroll"><table class="pvd-def"><thead><tr><th>Wk</th><th>Opp</th>';
    // A phone gets the short names, so five stats fit across 320px.
    stats.forEach(function (m) {
      html += '<th><span class="pvd-long">' + esc(m.spec.label) + '</span><span class="pvd-short">' + esc(m.spec.short) + '</span></th>';
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
      return tints.map(function (t) { return '<span class="pvd-sw pvd-cell ' + cls + '" style="--tint:' + t + '%"></span>'; }).join('');
    };
    html += '<p class="pvd-legend"><span>allowed less than usual</span>' + ramp('is-under', [55, 33, 12]) +
      '<span class="pvd-sw pvd-cell"></span>' + ramp('is-over', [12, 33, 55]) + '<span>more</span></p>';
    html += '<section class="pvd-notes"><h4 class="pvd-h">How to read this table</h4><p>Each cell compares what this defense allowed the ' + esc(model.pos) + 's it faced that week with what ' +
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
    return '<td class="num pvd-cell ' + cls + '" style="--tint:' + tint + '%" data-tip="' + esc(tip + ' (' + signPct(ratio) + ')') + '">' + text + '</td>';
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
      return '<span class="pvd-top-stat" data-tip="' + esc(tip) + '"><b' + (heat ? ' class="pvd-heat ' + heat + '"' : '') + '>' +
        esc(v) + '</b> ' + esc(k) + '</span>';
    };
    var html = '<div class="pvd-top"><div class="pvd-linectl" role="group" aria-label="Line">' +
      '<button type="button" class="dd-btn pvd-step" data-step="-1" aria-label="Lower the line">−</button>' +
      '<span class="pvd-line-v">' + lineLabel(line) + '</span>' +
      '<button type="button" class="dd-btn pvd-step" data-step="1" aria-label="Raise the line">+</button>' +
      '<span class="pvd-src" title="' + esc(q ? 'The book\'s line' : 'No book line yet: the line is the projection\'s') + '">' +
      (q ? BOOK[q.vendor] : 'model') + '</span>' +
      (q && q.line !== line ? '<button type="button" class="dd-btn pvd-reset">Book ' + q.line + '</button>' : '') + '</div>';
    // The three numbers wrap as one, so a phone keeps them on one row.
    html += '<span class="pvd-top-stats">';
    html += td
      ? stat((Math.round(m.mean * 100) / 100).toFixed(2), 'exp. TDs', 'How many touchdowns the model expects.')
      : stat(fmt(m.median), 'proj.', 'The middle outcome: half his projected games land above it, half below.');
    html += stat(pct(c.over), m.spec.anytime ? 'to score' : glyph(true) + ' over' + (c.push ? ' · push ' + pct(c.push) : ''),
      'The model\'s chance he clears the line.', chanceHeat(c.over));
    if (!td) html += '<span class="pvd-top-range" data-tip="8 in 10 of his projected games land in this range.">80%: ' +
      fmt(m.lo) + '–' + fmt(m.hi) + '</span>';
    return html + '</span></div>';
  }


  // The symbols the card's charts share.
  function key(def) {
    function sw(inner, w) { return '<svg width="' + (w || 14) + '" height="14" viewBox="0 0 ' + (w || 14) + ' 14" aria-hidden="true">' + inner + '</svg>'; }
    var items = [
      [sw('<circle class="pvd-sim is-over" cx="4" cy="7" r="3.5"/><circle class="pvd-sim is-under" cx="12" cy="7" r="3.5"/>', 16), 'Projected game, over / under'],
      [sw(mark('pvd-key-sw', 7, 7, 5, true)), 'Real game, over'],
      [sw(mark('pvd-key-sw', 7, 7, 5, false)), 'Real game, under'],
      [sw('<line class="pvd-line" x1="7" x2="7" y1="0" y2="14"/>'), 'The line'],
      [sw('<line class="pvd-range" x1="1" x2="23" y1="7" y2="7"/><path class="pvd-diamond" d="M12,1L18,7L12,13L6,7Z"/>', 24), 'Projection, 80% range'],
      [sw('<rect class="pvd-ring" x="1.5" y="1.5" width="11" height="11" rx="3"/>'), 'vs ' + esc(def)],
      [sw(mark('pvd-key-sw is-old', 7, 7, 5, false)), 'Earlier season']
    ];
    return '<div class="pvd-key" aria-label="Key">' + items.map(function (i) { return '<span>' + i[0] + i[1] + '</span>'; }).join('') + '</div>';
  }

  function card(m, line, def, width) {
    m.defense.def = def;
    var html = topBar(m, line);
    html += '<h4 class="pvd-h">Projection and what goes into it</h4>' + projectionChart(m, line, def, width);
    var cut = logGames(m, width).cut;
    html += '<h4 class="pvd-h">Game log' + (cut ? ' <span class="pvd-h-note">latest ' + (m.cur.length - cut) + ' of ' + m.cur.length + '</span>' : '') + '</h4>' +
      gameLog(m, line, def, width);
    // The key to every chart's symbols, once they have been seen.
    html += key(def);
    return html;
  }

  /* How to read the three charts, as plain paragraphs under them: the
   * charts come first, the explanation for whoever wants it after. */
  function notes(m, def, width) {
    var unit = { pass_att: 'pass attempts', rush_att: 'carries', targets: 'targets' }[m.spec.parts[m.spec.parts.length > 1 ? 1 : 0][0]];
    var cut = logGames(m, width).cut;
    var p = function (head, text) { return '<p><b>' + head + '.</b> ' + text + '</p>'; };
    return '<section class="pvd-notes"><h4 class="pvd-h">How to read these charts</h4>' +
      p('Projection and what goes into it', 'All on one scale, with the line through every row. ' +
        '<i>Projection</i> is ' + (width < 520 || m.spec.kind === 'td' ? 20 : 50) + ' equally likely games the model expects, one circle each, ' +
        'stacked by result: blue clears the line, orange falls short, and the share that are blue is the chance of the over. ' +
        'The diamond under them is the median and its bar spans 8 in 10 games. The fewer ' + esc(unit) + ' he gets, the wider the ' +
        'spread: one long play decides more of a game, and a smaller role swings more with game script and who else is healthy. ' +
        'The rows below are what built it, each ▲ or ▼ a real game over or under the line. <i>This season</i> is the baseline: recent games count most, ' +
        'last season fills in early. ' +
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
    if (root._pvdTips) return;
    root._pvdTips = true;
    var tip = document.createElement('div');
    tip.className = 'pvd-tip';
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

  global.PvdProjection = {
    STATS: STATS,
    BY_POS: BY_POS,
    build: build,
    card: card,
    notes: notes,
    defensePanel: defensePanel,
    bindTips: bindTips
  };
})(window);
