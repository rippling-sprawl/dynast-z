/* Baker's Oven — last season's weekly finishes (window.OvenWeekly).
 *
 * Pure model, no DOM. Given the committed raw stat lines from
 * scripts/fetch_nfl_weekly.py and a league's scoring_settings, it answers: how
 * many weeks did each player finish top 12 / 24 / 36 at his position?
 *
 * Why compute it here rather than fetch it
 * ----------------------------------------
 * Sleeper serves only three fixed rank formats (pos_rank_ppr, _half_ppr, _std).
 * There is no league-scored rank endpoint — their GraphQL schema is open and
 * introspectable, and not one of the fields taking a league_id returns stats or
 * scoring. Sleeper's own player card computes this client-side, and so do we.
 *
 * The arithmetic is exact, not an approximation: scoring_settings keys are the
 * same vocabulary as the stat keys, so a player's score is the dot product of
 * the two. (Verified against Sleeper's own pts_std, which reproduces to the
 * cent.) The work is ~340k multiply-adds and a hundred sorts — single-digit
 * milliseconds, so it runs once at boot rather than being precomputed per
 * league.
 */
(function (global) {
  'use strict';

  var C = global.OVEN;

  /* ---------- scoring ---------- */

  /* A league's scoring_settings omits every category it scores at zero, so a
   * missing key is 0, not an error. Iterate the player's stats rather than the
   * settings: stat lines are sparse (the fetch script drops zeros), and a
   * scoring table has ~70 keys against a typical line's ~15. */
  function score(stats, scoring) {
    var total = 0;
    for (var k in stats) {
      var w = scoring[k];
      if (w) total += w * stats[k];
    }
    return total;
  }

  /* ---------- weekly ranks ---------- */

  /* {playerKey: {t12, t24, t36, games, pos}}
   *
   * `games` counts weeks with a stat line, not weeks in the season, so a bye
   * reads as 11/16 rather than punishing a player for a week nobody could have
   * started him. A player who was injured all year still shows a small
   * denominator — availability stays visible instead of being averaged away.
   */
  function computeCounts(weekly, scoring) {
    if (!weekly || !scoring) return null;

    var tiers = C.WEEKLY_TIERS;
    var counts = {};
    var byWeekPos = {};   // "3|RB" -> [{pts, key}]

    for (var key in weekly) {
      var rec = weekly[key];
      if (!rec || !rec.w) continue;
      var pos = key.slice(0, key.indexOf('|'));

      var c = counts[key] = { pos: pos, games: 0 };
      for (var t = 0; t < tiers.length; t++) c['t' + tiers[t]] = 0;

      for (var wk in rec.w) {
        c.games++;
        var bucket = byWeekPos[wk + '|' + pos] || (byWeekPos[wk + '|' + pos] = []);
        bucket.push({ pts: score(rec.w[wk], scoring), key: key });
      }
    }

    for (var slot in byWeekPos) {
      var list = byWeekPos[slot];
      // Descending. Ties are broken arbitrarily but consistently — two players
      // on identical points at the tier boundary is rare enough, and under a
      // fractional-point scoring system it's near-impossible.
      list.sort(function (a, b) { return b.pts - a.pts; });
      for (var i = 0; i < list.length; i++) {
        var row = counts[list[i].key];
        for (var j = 0; j < tiers.length; j++) {
          // Sorted, so once a rank clears one cutoff it clears every wider one.
          if (i < tiers[j]) row['t' + tiers[j]]++;
        }
      }
    }

    return counts;
  }

  /* There was a starterDepth() here that derived each position's real starter
   * line from roster_positions x total_rosters (QB 24 in a superflex, and so
   * on) so the board could bold that one cutoff. It went out with the emphasis
   * it existed to drive: the three counts are now one evenly-weighted table, and
   * nothing consumed the answer. WEEKLY_SINGLE_TIER_POS still decides which
   * cutoffs a position shows at all — that outlived it. */

  global.OvenWeekly = {
    score: score,
    computeCounts: computeCounts,
  };
})(window);
