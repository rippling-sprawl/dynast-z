// One player's game logs as a table, in the defense-vs-players look.
//
// For a page or card that already names the player, so it is one row per
// game: the first column is the season and week where defense-vs-players has
// the player, the second the result. The opponent is added to the first
// column only in a section flagged `opp` — "last five" runs across teams,
// "career vs. this defense" does not. Rows come from /api/player-vs-defense
// in its row shape. Sections stack in one table so their columns line up,
// each with an optional title row above and a per-game average under it,
// whose result cell is the W-L record.
//
// Column groups follow the position, as on defense-vs-players: passing for a
// QB, rushing for a QB or RB, receiving for everyone but the QB. A group the
// position does not get comes back if any row has a number in it, so a
// receiver's jet sweeps still show. Passing has no Lng: balldontlie's box
// score carries no long completion.
//
// Styles: .dvp-* in styles/primary/defense-vs-players.css, .pl-* beside them.

(function (global) {
  'use strict';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function num(v, strong, start, title) {
    var cls = 'num' + (start ? ' grp-start' : '') + (Number(v) ? '' : ' is-zero') + (strong ? ' is-strong' : '');
    return '<td class="' + cls + '"' + (title ? ' title="' + esc(title) + '"' : '') + '>' + esc(v || 0) + '</td>';
  }

  function any(rows, k) {
    return rows.some(function (r) { return r[k]; });
  }

  function avg(rows, k) {
    var s = 0;
    rows.forEach(function (r) { s += r[k] || 0; });
    return rows.length ? (s / rows.length).toFixed(1) : 0;
  }

  function max(rows, k) {
    return rows.reduce(function (m, r) { return Math.max(m, r[k] || 0); }, 0);
  }

  // 'W' | 'L' | 'T', or '' for a game without a final score.
  function outcome(g) {
    if (g.status !== 'final' || g.pts_for == null || g.pts_against == null) return '';
    return g.pts_for > g.pts_against ? 'W' : g.pts_for < g.pts_against ? 'L' : 'T';
  }

  function result(g) {
    var r = outcome(g);
    return '<td class="pl-rescol' + (r ? ' is-' + r.toLowerCase() : '') + '">' +
      (r ? r + ' ' + esc(g.pts_for) + '-' + esc(g.pts_against) : '') + '</td>';
  }

  function record(rows) {
    var n = { W: 0, L: 0, T: 0 };
    rows.forEach(function (g) { var r = outcome(g); if (r) n[r]++; });
    return '<td class="pl-rescol">' + n.W + '-' + n.L + (n.T ? '-' + n.T : '') + '</td>';
  }

  // player: { pos, team }. sections: [{ title?, rows, empty, opp? }].
  function playerLogTable(player, sections) {
    var all = [];
    sections.forEach(function (s) { all = all.concat(s.rows); });
    var pos = player.pos;
    var show = {
      pass: pos === 'QB' || any(all, 'pass_att'),
      rush: pos === 'QB' || pos === 'RB' || any(all, 'rush_att'),
      rec: pos !== 'QB' || any(all, 'targets')
    };
    show.tot = show.rush && show.rec;
    var cols = 2 + (show.pass ? 5 : 0) + (show.rush ? 4 : 0) + (show.rec ? 5 : 0) + (show.tot ? 2 : 0);

    var head =
      '<thead>' +
        '<tr class="dvp-groups"><th class="dvp-name"></th><th></th>' +
          (show.pass ? '<th colspan="5" class="grp">Passing</th>' : '') +
          (show.rush ? '<th colspan="4" class="grp">Rushing</th>' : '') +
          (show.rec ? '<th colspan="5" class="grp">Receiving</th>' : '') +
          (show.tot ? '<th colspan="2" class="grp">Total</th>' : '') +
        '</tr>' +
        '<tr><th class="dvp-name">Game</th><th class="pl-rescol">Result</th>' +
          (show.pass ? '<th class="num grp-start">Cmp</th><th class="num">Att</th><th class="num">Yds</th><th class="num">TD</th><th class="num">Int</th>' : '') +
          (show.rush ? '<th class="num grp-start">Att</th><th class="num">Yds</th><th class="num">TD</th><th class="num">Lng</th>' : '') +
          (show.rec ? '<th class="num grp-start">Tgt</th><th class="num">Rec</th><th class="num">Yds</th><th class="num">TD</th><th class="num">Lng</th>' : '') +
          (show.tot ? '<th class="num grp-start">Yds</th><th class="num">TD</th>' : '') +
        '</tr>' +
      '</thead>';

    // r: one game, or the section's rows for its average line.
    function line(r, rows) {
      var v = rows ? function (k) { return avg(rows, k); } : function (k) { return r[k]; };
      var lng = rows ? function (k) { return max(rows, k); } : v;
      var lt = rows ? 'Longest in these games' : '';
      return (show.pass ? num(v('pass_cmp'), false, true) + num(v('pass_att')) + num(v('pass_yds')) + num(v('pass_td')) + num(v('pass_int')) : '') +
        (show.rush ? num(v('rush_att'), false, true) + num(v('rush_yds')) + num(v('rush_td')) + num(lng('rush_lng'), false, false, lt) : '') +
        (show.rec ? num(v('targets'), false, true) + num(v('rec')) + num(v('rec_yds')) + num(v('rec_td')) + num(lng('rec_lng'), false, false, lt) : '') +
        (show.tot ? num(v('tot_yds'), true, true) + num(v('tot_td'), true) : '');
    }

    var body = sections.map(function (s) {
      var out = s.title ? '<tr class="dvp-game"><th colspan="' + cols + '"><span class="dvp-label"><span class="dvp-wk">' +
        esc(s.title) + '</span></span></th></tr>' : '';
      if (!s.rows.length) {
        return out + '<tr><td class="dvp-none" colspan="' + cols + '">' + esc(s.empty || 'No games') + '</td></tr>';
      }
      out += s.rows.map(function (g) {
        // The team he played for, when it was not the one he is on now.
        var was = g.team && player.team && g.team !== player.team
          ? '<span class="pl-was" title="Played for ' + esc(g.team) + '">' + esc(g.team) + '</span>' : '';
        return '<tr><td class="dvp-name"><span class="pl-game">' +
          '<b>' + esc(g.season) + ' ' + (g.postseason ? 'Playoffs' : 'Wk ' + esc(g.week)) + '</b>' +
          (s.opp ? '<span class="dvp-opp">' + (g.home ? 'vs' : '@') +
            '<img src="/assets/icons/nfl/' + esc(g.opp) + '.svg" alt="' + esc(g.opp) + '" title="' + esc(g.opp) + '"></span>' : '') +
          was + '</span></td>' + result(g) + line(g) + '</tr>';
      }).join('');
      return out + '<tr class="pl-avg"><td class="dvp-name" title="Per game; Lng is the longest">Avg (' +
        s.rows.length + ' g)</td>' + record(s.rows) + line(null, s.rows) + '</tr>';
    }).join('');

    return '<div class="dvp-scroll pl-scroll"><table class="dvp-table no-pos">' + head +
      '<tbody>' + body + '</tbody></table></div>';
  }

  global.playerLogTable = playerLogTable;
})(window);
