// The defense-vs-players table: every opposing passer, rusher and receiver a
// defense has faced in a completed game this season, a game at a time.
//
// The rows are /api/defense-vs-players?team=…, built weekly by
// scripts/build_defense_vs_players.py. Shared by /football/defense-vs-players
// and the Player Projections defense tab; each page owns its filters and
// passes them in as `view`.
//
// Styles: .dvp-* in styles/primary/defense-vs-players.css.

(function (global) {
  'use strict';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  // A zero is drawn faint rather than blank: "no carries" is an answer, and a
  // blank cell reads as missing data.
  // `start` opens a column group (Rushing, Receiving, Total) with a rule.
  function num(v, strong, start) {
    var cls = 'num' + (start ? ' grp-start' : '') + (v ? '' : ' is-zero') +
      (strong ? ' is-strong' : '');
    return '<td class="' + cls + '">' + esc(v || 0) + '</td>';
  }

  // "Nico Collins" -> "N. Collins": the first name to its initial, the rest
  // as given, so "Amon-Ra St. Brown" keeps his whole surname. The full name
  // stays on the cell's tooltip.
  function shortName(name) {
    var parts = String(name || '').trim().split(/\s+/);
    return parts.length > 1 ? parts[0].charAt(0) + '. ' + parts.slice(1).join(' ') : parts[0] || '';
  }

  function weekLabel(g) {
    return g && g.postseason ? 'P' + g.week : String(g ? g.week : '');
  }

  // Latest week first (in game order, so the postseason sits above week 18),
  // then position QB → RB → WR → TE → anything else, then total yards.
  var POS_RANK = { QB: 0, RB: 1, WR: 2, TE: 3 };
  function posRank(p) { return p in POS_RANK ? POS_RANK[p] : 4; }

  // The position filter hides the groups its players never have: no passing
  // unless QB is in (or All), no rushing for WR/TE alone, no receiving for
  // QB alone. p: the positions picked, none meaning all.
  function posDefaults(p) {
    var qb = p.indexOf('QB') >= 0;
    var rest = p.filter(function (x) { return x !== 'QB'; });
    return {
      pass: !!p.length && !qb,
      rush: !!p.length && p.every(function (x) { return x === 'WR' || x === 'TE'; }),
      rec: qb && !rest.length
    };
  }

  // doc: the defense's payload. view: { pos: { QB: true, … } (none = all),
  // att, tgt (minimums), hide: { pass, rush, rec } }. lead(c): optional rows
  // to open the body with, given the column layout c, under which the
  // defense's own games get a group row titled by `leadGroup(c)`.
  // -> the table's HTML, or '' when the defense has no completed games.
  function render(doc, view, lead, leadGroup) {
    var byGame = {}, gameOrder = {};
    doc.games.forEach(function (g, i) { byGame[g.game_id] = g; gameOrder[g.game_id] = i; });
    if (!doc.rows.length) return '';

    var anyPos = !Object.keys(view.pos).length;
    // Total is rushing plus receiving, so it goes when either is hidden:
    // beside a single group it only repeats.
    var showPass = !view.hide.pass;
    var showRush = !view.hide.rush;
    var showRec = !view.hide.rec;
    var showTot = showRush && showRec;
    var rows = doc.rows.filter(function (r) {
      return (anyPos || view.pos[r.pos]) &&
        r.rush_att >= view.att && r.targets >= view.tgt;
    }).sort(function (a, b) {
      return (gameOrder[b.game_id] - gameOrder[a.game_id]) ||
        (posRank(a.pos) - posRank(b.pos)) || String(a.pos).localeCompare(String(b.pos)) ||
        (b.tot_yds - a.tot_yds) || String(a.player).localeCompare(String(b.player));
    });

    // One position picked makes the position column say the same thing on every row.
    var showPos = Object.keys(view.pos).length !== 1;
    var cols = (showPos ? 2 : 1) + (showPass ? 6 : 0) + (showRush ? 4 : 0) + (showRec ? 5 : 0) + (showTot ? 2 : 0);
    var head =
      '<thead>' +
        '<tr class="dvp-groups">' +
          (showPos ? '<th class="dvp-poscol"></th>' : '') + '<th class="dvp-name"></th>' +
          (showPass ? '<th colspan="6" class="grp">Passing</th>' : '') +
          (showRush ? '<th colspan="4" class="grp">Rushing</th>' : '') +
          (showRec ? '<th colspan="5" class="grp">Receiving</th>' : '') +
          (showTot ? '<th colspan="2" class="grp">Total</th>' : '') +
        '</tr>' +
        '<tr>' +
          (showPos ? '<th class="dvp-poscol"></th>' : '') + '<th class="dvp-name">Player</th>' +
          (showPass ? '<th class="num grp-start">Cmp</th><th class="num">Att</th><th class="num">Yds</th><th class="num">TD</th><th class="num">Int</th><th class="num">Lng</th>' : '') +
          (showRush ? '<th class="num grp-start">Att</th><th class="num">Yds</th><th class="num">TD</th><th class="num">Lng</th>' : '') +
          (showRec ? '<th class="num grp-start">Tgt</th><th class="num">Rec</th><th class="num">Yds</th><th class="num">TD</th><th class="num">Lng</th>' : '') +
          (showTot ? '<th class="num grp-start">Yds</th><th class="num">TD</th>' : '') +
        '</tr>' +
      '</thead>';

    // A game opens with one full-width row carrying the week and opponent.
    // Within it each position is a narrow column cell spanning its players'
    // rows, its label turned on its side. A bye is a thin row of its own
    // wherever the regular-season weeks skip one. The labels are sticky so
    // they stay in view on a horizontal scroll.
    var lastGame = null, lastPos = null, lastWeek = null;
    var span = {};
    rows.forEach(function (r) { var k = r.game_id + '|' + r.pos; span[k] = (span[k] || 0) + 1; });
    var body = rows.map(function (r) {
      var out = '';
      if (r.game_id !== lastGame) {
        var g = byGame[r.game_id];
        // Games run latest first, so a skipped week sits between this game's
        // week and the one before it in the list.
        if (lastWeek != null && g && !g.postseason) {
          for (var w = lastWeek - 1; w > g.week; w--) {
            out += '<tr class="dvp-bye"><th colspan="' + cols + '"><span class="dvp-label">Wk ' + w + ' &middot; Bye</span></th></tr>';
          }
        }
        lastWeek = g && !g.postseason ? g.week : null;
        // The opponent is its logo alone; @ / vs still says home or away.
        out += '<tr class="dvp-game"><th colspan="' + cols + '"><span class="dvp-label">' +
          '<span class="dvp-wk">' + (g && g.postseason ? '' : 'Wk ') + esc(weekLabel(g)) + '</span>' +
          '<span class="dvp-opp">' + (g && !g.home ? '@' : 'vs') +
          '<img src="/assets/icons/nfl/' + esc(r.opp) + '.svg" alt="' + esc(r.opp) +
          '" title="' + esc(r.opp) + '"></span></span></th></tr>';
        lastGame = r.game_id;
        lastPos = null;
      }
      var posCell = '';
      if (r.pos !== lastPos) {
        if (showPos) posCell = '<th class="dvp-poscell" rowspan="' + span[r.game_id + '|' + r.pos] + '" scope="rowgroup">' +
          '<span title="' + esc(r.pos) + '">' + esc((r.pos || '—').charAt(0)) + '</span></th>';
        lastPos = r.pos;
      }
      return out + '<tr' + (posCell ? ' class="dvp-first"' : '') + '>' + posCell +
        '<td class="dvp-name" title="' + esc(r.player) + '"><b>' + esc(shortName(r.player)) + '</b></td>' +
        (showPass ? num(r.pass_cmp, false, true) + num(r.pass_att) + num(r.pass_yds) + num(r.pass_td) + num(r.pass_int) + num(r.pass_lng) : '') +
        (showRush ? num(r.rush_att, false, true) + num(r.rush_yds) + num(r.rush_td) + num(r.rush_lng) : '') +
        (showRec ? num(r.targets, false, true) + num(r.rec) + num(r.rec_yds) + num(r.rec_td) + num(r.rec_lng) : '') +
        (showTot ? num(r.tot_yds, true, true) + num(r.tot_td, true) : '') +
        '</tr>';
    }).join('') || '<tr><td class="dvp-none" colspan="' + cols + '">No players match these filters.</td></tr>';

    var c = { cols: cols, showPos: showPos, showPass: showPass, showRush: showRush, showRec: showRec, showTot: showTot };
    var opening = lead ? lead(c) : '';
    if (opening) body = opening + leadGroup(c) + body;

    return '<div class="dvp-scroll"><table class="dvp-table' + (showPos ? '' : ' no-pos') + '">' + head +
      '<tbody>' + body + '</tbody></table></div>';
  }

  // The column header and the week row stack as they pin
  // on a vertical scroll, each just under the one above. Their heights are
  // whatever the font made them, so they are read off the drawn table —
  // unrounded, and overlapped by half a pixel, because a rounded-up offset
  // leaves a sliver of the rows scrolling underneath showing through.
  // A table drawn while hidden measures 0; pin it again once shown.
  function pin(container) {
    var table = container.querySelector('.dvp-table');
    if (!table) return;
    function h(el) { return el ? el.getBoundingClientRect().height : 0; }
    var heads = table.tHead.rows;
    var h0 = h(heads[0]) - 0.5;
    var h1 = h0 + h(heads[1]) - 0.5;
    table.style.setProperty('--pin-1', h0 + 'px');
    table.style.setProperty('--pin-game', h1 + 'px');
  }

  global.DefenseTable = {
    render: render,
    pin: pin,
    num: num,
    shortName: shortName,
    posDefaults: posDefaults
  };
})(window);
