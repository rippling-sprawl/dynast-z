/*
  Baker's Buns — the market layer.

  The Board used to have exactly one market in it: the playoff make/miss pair
  the projections JSON carries per team. This turns that into one of five, so a
  reader can ask the same question — where does the model disagree with the
  price — of a win total, a division, a conference or the Super Bowl. The model
  never moves. Only the thing it is being argued with does.

  Everything here is a de-vig and a rank, and both are worth stating:

  1. De-vigging generalises from a pair to a field. Make/miss are two sides of
     one market, so their implied probabilities sum to 1 plus the hold and
     dividing by that sum strips it. A division is the same shape with four
     sides instead of two, a conference with sixteen, the Super Bowl with
     thirty-two. In every case the book's prices sum to more than one whole
     outcome and the excess is the hold, so every market here is normalised the
     same way: divide each price's implied probability by the sum of the field
     it belongs to.

     What makes that checkable rather than merely plausible is that each market
     has a structural total it must land on, and they are not the same number:
     14 playoff berths, 8 division winners, 2 conference champions, 1 Super
     Bowl winner. A de-vig that is wrong will miss its total. All four hit
     (14.05, 8.00, 2.00, 1.00), and `total` / `expected` are carried on every
     market so the page can print the check rather than assert it.

  2. Win total is not a probability and is not treated as one. De-vigging its
     over/under gives a number between 42% and 57% for all thirty-two teams,
     because that is exactly what a book prices a line to do — balance it. The
     market's actual opinion is the line, so the line is what this returns, in
     wins. Its structural check is the league's 272 games-worth of wins; the
     posted lines sum to 274, and that +2 is the books' remaining lean after
     the per-team hold has already been divided out.

  3. Everything is exposed twice: as its own value, and as a percentile within
     the field. The values are not comparable — 11.5 wins, a 52% division
     price and a 0.2% Super Bowl price are four different units and four wildly
     different spreads, the Super Bowl's best price being 60x its worst. A
     chart axis that has to serve all five needs one scale, and a chart that
     puts five markets on five spokes at once needs the five to mean the same
     thing at the same radius. The percentile is that common scale. The raw
     value is kept alongside it for every tooltip and read-out, because the
     percentile is the geometry and the price is the fact.
*/
(function () {
  'use strict';

  // The projections sheet says WSH; the sportsbooks' feed says WAS.
  var ALIAS = { WAS: 'WSH' };

  /* The five markets, in the order they escalate — a win total is an opinion
   * about September, the Super Bowl is an opinion about February. `expected`
   * is the structural total described in the file comment. */
  var MARKETS = [
    {
      key: 'winTotal', label: 'Win total', kind: 'line',
      axis: 'market — posted win total',
      tipLabel: 'win total', sumLabel: 'posted lines',
      expected: 272, expectedNote: '272 wins across the league',
      fmt: function (v) { return v.toFixed(1) + ' wins'; },
      totalFmt: function (v) { return v.toFixed(0); }
    },
    {
      key: 'playoffs', label: 'Make playoffs', kind: 'pair',
      axis: 'market — de-vigged chance to make the playoffs',
      tipLabel: 'to make', sumLabel: 'de-vigged prices',
      expected: 14, expectedNote: '14 playoff berths',
      fmt: pctFmt, totalFmt: function (v) { return v.toFixed(1); }
    },
    {
      key: 'division', label: 'Win division', kind: 'group',
      sources: ['afc_east_winner', 'afc_north_winner', 'afc_south_winner', 'afc_west_winner',
        'nfc_east_winner', 'nfc_north_winner', 'nfc_south_winner', 'nfc_west_winner'],
      axis: 'market — de-vigged chance to win the division',
      tipLabel: 'to win the division', sumLabel: 'de-vigged prices',
      expected: 8, expectedNote: '8 division winners',
      fmt: pctFmt, totalFmt: function (v) { return v.toFixed(2); }
    },
    {
      key: 'conference', label: 'Win conference', kind: 'group',
      sources: ['afc_winner', 'nfc_winner'],
      axis: 'market — de-vigged chance to win the conference',
      tipLabel: 'to win the conference', sumLabel: 'de-vigged prices',
      expected: 2, expectedNote: '2 conference champions',
      fmt: pctFmt, totalFmt: function (v) { return v.toFixed(2); }
    },
    {
      key: 'superBowl', label: 'Win Super Bowl', kind: 'group',
      sources: ['super_bowl_winner'],
      axis: 'market — de-vigged chance to win the Super Bowl',
      tipLabel: 'to win it all', sumLabel: 'de-vigged prices',
      expected: 1, expectedNote: '1 champion',
      fmt: pctFmt, totalFmt: function (v) { return v.toFixed(2); }
    }
  ];

  function pctFmt(v) {
    // A 0.21% Super Bowl price and an 81% playoff price want different
    // precision, and rounding the first to "0%" would erase it.
    return v >= 0.1 ? (v * 100).toFixed(0) + '%'
      : v >= 0.01 ? (v * 100).toFixed(1) + '%'
        : (v * 100).toFixed(2) + '%';
  }

  function imp(o) {
    o = typeof o === 'string' ? parseFloat(o.replace('+', '')) : o;
    if (!isFinite(o)) return null;
    return o > 0 ? 100 / (o + 100) : -o / (-o + 100);
  }

  /* One price per team from however many books quoted it. The mean rather than
   * the best: this is being read as an estimate of what the field thinks, not
   * as a line anyone is about to bet, and taking the best price from each book
   * in turn would build a team that no single book ever offered. */
  function consensus(prices) {
    var v = [], k;
    for (k in prices) {
      if (Object.prototype.hasOwnProperty.call(prices, k)) {
        var p = imp(prices[k]);
        if (p != null) v.push(p);
      }
    }
    if (!v.length) return null;
    return v.reduce(function (s, x) { return s + x; }, 0) / v.length;
  }

  /* A field normalised to one whole outcome. Each sub-market is normalised on
   * its own before the union, which is what makes a division market work: the
   * eight divisions are eight separate books each summing to 1, and pooling
   * them before dividing would hand every team an eighth of its real price. */
  function devigField(market) {
    var raw = {}, total = 0;
    ((market && market.candidates) || []).forEach(function (c) {
      var p = consensus(c.prices);
      if (p == null) return;
      raw[ALIAS[c.key] || c.key] = p;
      total += p;
    });
    var out = {};
    if (!total) return out;
    Object.keys(raw).forEach(function (k) { out[k] = raw[k] / total; });
    return out;
  }

  /* Percentile within the field, 0 for the worst price and 100 for the best.
   * Ties share the midpoint of the range they span, so four teams the book
   * cannot separate do not get four different ranks. */
  function percentiles(byTeam) {
    var keys = Object.keys(byTeam);
    var n = keys.length;
    var out = {};
    if (n < 2) { keys.forEach(function (k) { out[k] = 100; }); return out; }
    keys.forEach(function (k) {
      var below = 0, equal = 0;
      keys.forEach(function (j) {
        if (byTeam[j] < byTeam[k]) below++;
        else if (byTeam[j] === byTeam[k]) equal++;
      });
      out[k] = 100 * (below + (equal - 1) / 2) / (n - 1);
    });
    return out;
  }

  /* ---------- public ---------- */

  /* Builds every market against the loaded field. Returns descriptors that
   * carry their own data, so a caller picks one and never has to know which of
   * the four shapes it came from. A market whose feed is missing comes back
   * `ok: false` rather than absent, so the picker can show it disabled instead
   * of silently offering four options where the page promises five. */
  function build(teams, outrights) {
    var src = (outrights && outrights.markets) || {};
    var field = {};
    (teams || []).forEach(function (t) { if (t.abbr) field[t.abbr] = t; });

    return MARKETS.map(function (m) {
      var byTeam = {};

      if (m.kind === 'line') {
        (teams || []).forEach(function (t) {
          var v = (t.odds || {}).winTotal;
          if (v != null) byTeam[t.abbr] = v;
        });
      } else if (m.kind === 'pair') {
        (teams || []).forEach(function (t) {
          var o = t.odds || {};
          var a = imp(o.make), b = imp(o.miss);
          if (a == null || b == null) return;
          byTeam[t.abbr] = a / (a + b);
        });
      } else {
        m.sources.forEach(function (name) {
          var part = devigField(src[name]);
          Object.keys(part).forEach(function (k) {
            // A team priced in a market it does not belong to would be a feed
            // error, not a reading — drop anything the projections don't know.
            if (field[k]) byTeam[k] = part[k];
          });
        });
      }

      var keys = Object.keys(byTeam);
      var total = keys.reduce(function (s, k) { return s + byTeam[k]; }, 0);

      return {
        key: m.key, label: m.label, axis: m.axis,
        tipLabel: m.tipLabel, sumLabel: m.sumLabel,
        expected: m.expected, expectedNote: m.expectedNote,
        fmt: m.fmt, totalFmt: m.totalFmt,
        ok: keys.length >= 3,
        count: keys.length,
        total: total,
        value: byTeam,
        pct: percentiles(byTeam)
      };
    });
  }

  function load() {
    return fetch('/data/outrights.json')
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; });   // the page still has win total and playoffs
  }

  window.bunMarkets = { build: build, load: load, MARKETS: MARKETS };
})();
