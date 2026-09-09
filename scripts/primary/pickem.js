/* Shared Pick 'Em rendering and the confidence model.
 *
 * Three pages use this: the hub, the picks board and the standings. Everything
 * here either returns an HTML string or transforms a plain picks object — no
 * DOM, no fetching, no page state, the same discipline
 * scripts/components/nfl-schedule.js follows. The pages own their state and
 * their event wiring; this owns what a row looks like and what the rules are.
 *
 * THE CONFIDENCE MODEL
 *
 * A week's confidences are distinct integers in 1..N, where N is how many games
 * the week has a line for. A full week therefore uses exactly 1..N; a partial
 * week uses any k of those values, so three picks may sit on 16/15/14 or on
 * 3/2/1.
 *
 * The range is 1..N and not a gapless 1..k because a gapless one cannot survive
 * per-game locking: pick four games ranked 1-4, let the Thursday game holding 4
 * kick off, then drop a Sunday game holding 2, and the remainder {1, 3, 4} has
 * a hole that only the locked pick could fill. See the note in
 * api/_pickem/scoring.py.
 *
 * The three mutations below are written so that an invalid state is
 * unreachable rather than merely rejected. Picking a game takes the highest
 * free value, un-picking one simply releases its value, and choosing a value
 * another game holds swaps the two rather than duplicating it. The server
 * validates all of this again (api/_pickem/scoring.py) — it has to, since the
 * client is not trusted — but a page that can only ever submit a legal week
 * never has to explain a rejection.
 *
 * Everything is ES5 globals, like the rest of scripts/ — no modules.
 */
(function (global) {
  'use strict';

  /* Served from this app, not hotlinked — the same 32 files the schedule rows
   * and the team picker use. The abbreviations in pickem_games come from
   * balldontlie and match these filenames exactly, WSH and JAX included
   * (see the note on team_index in scripts/bdl_common.py). */
  var LOGO_DIR = '/assets/icons/nfl/';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  /* ---------- time ----------
   * Kickoffs arrive as UTC instants and every label is US Eastern, because that
   * is the zone the league schedules in and the zone the Tuesday 3:00am freeze
   * is defined against. Rendering in the viewer's own zone would put a "1:00
   * slate" game at 10:00 for a west-coast reader and make the deadline copy
   * read as a lie. The formatters are built once: a week is sixteen rows and a
   * standings page can be eighteen columns. */

  var TZ = 'America/New_York';
  var fmt = null;

  function formats() {
    if (!fmt) {
      fmt = {
        time: new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit', timeZone: TZ }),
        dayLong: new Intl.DateTimeFormat('en-US', { weekday: 'long', month: 'long', day: 'numeric', timeZone: TZ }),
        dayShort: new Intl.DateTimeFormat('en-US', { weekday: 'short', hour: 'numeric', minute: '2-digit', timeZone: TZ }),
        dayKey: new Intl.DateTimeFormat('en-CA', { year: 'numeric', month: '2-digit', day: '2-digit', timeZone: TZ })
      };
    }
    return fmt;
  }

  function toDate(iso) {
    return iso ? new Date(String(iso).replace(' ', 'T')) : null;
  }

  // "1:00" — the meridiem is dropped for the same reason the schedule drops it:
  // every kickoff renders as 1:00 through 9:30 and no NFL game starts in the
  // morning except the international window, which the date beside it names.
  function timeLabel(d) {
    return formats().time.formatToParts(d).filter(function (p) {
      return p.type !== 'dayPeriod' && !(p.type === 'literal' && p.value !== ':');
    }).map(function (p) { return p.value; }).join('');
  }

  function pkKickoffLabel(iso) {
    var d = toDate(iso);
    return d ? formats().dayShort.format(d) : 'TBD';
  }

  /* ---------- the line ----------
   * spread_home is stored from the home team's side, the way a book quotes it.
   * A row shows each team its own number, so the away side is the negation. */

  function spreadFor(game, side) {
    if (game.spread_home === null || game.spread_home === undefined) return null;
    return side === 'home' ? game.spread_home : -game.spread_home;
  }

  // "-3.5", "+3.5", "PK". The minus is a real minus sign (U+2212) rather than a
  // hyphen so it lines up with the digits and does not read as a bullet.
  function pkSpreadLabel(value) {
    if (value === null || value === undefined) return '';
    if (value === 0) return 'PK';
    return (value > 0 ? '+' : '−') + Math.abs(value);
  }

  /* ---------- the confidence model ---------- */

  // `picks` is { game_id: { pick: 'GB', confidence: 12 } } and is never mutated
  // in place: each of these returns a new object, so a page can hand the old one
  // back if a save is refused.
  function pkPickCount(picks) {
    return Object.keys(picks).length;
  }

  // The highest value in 1..n nobody is using. Highest rather than lowest
  // because a game you have just decided to pick is, more often than not, one
  // you feel strongly about — and it is trivially demoted from there.
  function highestFree(picks, n) {
    var taken = {}, key;
    for (key in picks) if (picks.hasOwnProperty(key)) taken[picks[key].confidence] = true;
    for (var v = n; v >= 1; v--) if (!taken[v]) return v;
    return null;
  }

  /* Pick a side. A game that is already picked on that side is un-picked, which
   * is what a second tap on the same button means. Switching sides keeps the
   * confidence: it is the same slot in your ranking, just the other team.
   *
   * `n` is the week's pickable-game count, the top of the confidence range. */
  function pkTogglePick(picks, gameId, side, n) {
    var next = {}, key;
    for (key in picks) if (picks.hasOwnProperty(key)) next[key] = picks[key];
    var current = next[gameId];
    if (current && current.pick === side) return pkClearPick(picks, gameId);
    if (current) {
      next[gameId] = { pick: side, confidence: current.confidence };
      return next;
    }
    // +1 because `next` does not contain this game yet: with k picks already
    // down, the one free value in 1..k+1 is k+1.
    var free = highestFree(next, n || pkPickCount(next) + 1);
    // Nothing free can only happen if every value in 1..n is already spoken
    // for, i.e. the whole week is picked, in which case there is no game left
    // to pick anyway. Refusing beats inventing a duplicate.
    if (free === null) return picks;
    next[gameId] = { pick: side, confidence: free };
    return next;
  }

  /* Un-pick a game. Its confidence is simply released — nothing renumbers,
   * which is exactly what makes this safe to do after another game in the week
   * has locked. */
  function pkClearPick(picks, gameId) {
    if (!picks[gameId]) return picks;
    var next = {}, key;
    for (key in picks) {
      if (!picks.hasOwnProperty(key) || key === gameId) continue;
      next[key] = { pick: picks[key].pick, confidence: picks[key].confidence };
    }
    return next;
  }

  /* Give a game a confidence. Whoever held that value takes this game's old one
   * — a swap, so the permutation survives and the reader never has to resolve a
   * duplicate the page created. */
  function pkSetConfidence(picks, gameId, value) {
    var mine = picks[gameId];
    if (!mine || value === mine.confidence) return picks;
    var next = {}, key;
    for (key in picks) {
      if (!picks.hasOwnProperty(key)) continue;
      var p = picks[key];
      if (key === gameId) next[key] = { pick: p.pick, confidence: value };
      else if (p.confidence === value) next[key] = { pick: p.pick, confidence: mine.confidence };
      else next[key] = { pick: p.pick, confidence: p.confidence };
    }
    return next;
  }

  // The wire shape the PUT wants: the complete intended set for the week.
  function pkToPayload(picks) {
    return Object.keys(picks).map(function (gameId) {
      return {
        game_id: gameId,
        pick: picks[gameId].pick,
        confidence: picks[gameId].confidence
      };
    });
  }

  // Read the server's `mine` map back into the model, dropping the scoring it
  // carries. A pick with no confidence is dropped rather than defaulted: it
  // cannot happen through the API, and inventing a value would silently move
  // somebody else's.
  function pkFromServer(mine) {
    var picks = {}, key;
    for (key in mine) {
      if (!mine.hasOwnProperty(key)) continue;
      if (mine[key] && mine[key].pick && mine[key].confidence) {
        picks[key] = { pick: mine[key].pick, confidence: mine[key].confidence };
      }
    }
    return picks;
  }

  /* ---------- rows ---------- */

  /* The crest carries the identity, so it leads and it is large. Under it, the
   * abbreviation and the line read as one unit — "SEA −3" is the thing being
   * chosen, and splitting them across the row made the reader pair them up
   * themselves on sixteen rows. The full club name is gone: a 40px crest above
   * its own abbreviation says "Seahawks" without spending a column on it. */
  function teamCell(abbr, line) {
    return '<img class="pk-logo" src="' + LOGO_DIR + esc(abbr) + '.svg" alt="" ' +
      'aria-hidden="true" loading="lazy">' +
      '<span class="pk-meta">' +
        '<span class="pk-abbr">' + esc(abbr) + '</span>' +
        (line ? '<span class="pk-line">' + esc(line) + '</span>' : '') +
      '</span>';
  }

  /* One side of one game, as a button. Disabled once the game has kicked off:
   * the server refuses a late edit anyway, and a control that looks live and
   * then fails is worse than one that says up front it is closed. */
  function sideButton(game, side, picks) {
    var abbr = side === 'home' ? game.home : game.away;
    var chosen = picks[game.game_id] && picks[game.game_id].pick === abbr;
    var covered = game.result === side;
    return '<button type="button" class="pk-side' +
      (chosen ? ' is-picked' : '') + (covered ? ' is-covered' : '') +
      '" data-game="' + esc(game.game_id) + '" data-side="' + esc(abbr) + '"' +
      (game.locked ? ' disabled' : '') +
      ' aria-pressed="' + (chosen ? 'true' : 'false') + '">' +
      teamCell(abbr, pkSpreadLabel(spreadFor(game, side))) + '</button>';
  }

  /* The confidence control. A <select> rather than a drag handle: sixteen rows
   * of drag targets is unusable on a phone, and the value is a number the
   * player is choosing deliberately rather than an order they are arranging. */
  function confidenceCell(game, picks, n) {
    var mine = picks[game.game_id];
    if (game.locked) {
      return '<span class="pk-conf is-locked">' +
        (mine ? esc(mine.confidence) : '—') + '</span>';
    }
    if (!mine) return '<span class="pk-conf is-empty">–</span>';
    // The whole range, not just the values in play: choosing one another game
    // holds swaps them, so every option is reachable and none of them can
    // produce a duplicate.
    var opts = '';
    for (var v = n; v >= 1; v--) {
      opts += '<option value="' + v + '"' +
        (v === mine.confidence ? ' selected' : '') + '>' + v + '</option>';
    }
    return '<span class="pk-conf"><select class="pk-conf-select" ' +
      'data-game="' + esc(game.game_id) + '" ' +
      'aria-label="Confidence for ' + esc(game.away + ' at ' + game.home) + '">' +
      opts + '</select></span>';
  }

  /* What happened, on the right of the row. Three states, in the order a game
   * passes through them: the kickoff time, then who is on it once it locks,
   * then the verdict and what it paid once it is graded.
   *
   * The chips stay through the final state. Dropping them there was the first
   * version and it was backwards — the moment a game is graded is exactly when
   * who-picked-what is worth reading, and it is also the only view of the pool
   * that survives the week. */
  /* The kickoff, leading the row. It used to share the trailing cell with the
   * result and the chips, which meant the one column that is always populated
   * kept moving and changing shape. On its own at the left it is a fixed,
   * scannable gutter, and the trailing cell is free to be the input. */
  function timeCell(game) {
    var d = toDate(game.kickoff);
    return '<span class="pk-time">' + esc(d ? timeLabel(d) : 'TBD') + '</span>';
  }

  function stateCell(game, picks, others) {
    if (game.result) {
      var mine = picks[game.game_id];
      var verdict = game.result === 'push' ? 'Push'
        : esc(game.result === 'home' ? game.home : game.away) + ' covered';
      var score = (game.away_score === null || game.away_score === undefined) ? ''
        : ' <span class="pk-score">' + esc(game.away_score) + '–' +
          esc(game.home_score) + '</span>';
      var won = mine && game.result !== 'push' &&
        mine.pick === (game.result === 'home' ? game.home : game.away);
      var points = mine
        ? '<span class="pk-points' + (won ? ' is-hit' : ' is-miss') + '">' +
            (won ? '+' + esc(mine.confidence) : '0') + '</span>'
        : '';
      return '<span class="pk-state is-final">' + verdict + score + points +
        chips(game, others) + '</span>';
    }
    if (game.locked) {
      return '<span class="pk-state is-locked">' +
        (chips(game, others) || '<span class="pk-lock">Locked</span>') + '</span>';
    }
    // Nothing to say yet: the row is the time, the two sides and the control,
    // and an empty trailing line would only add a gap between rows.
    return '';
  }

  /* Everyone else's picks, once the game has kicked off and the server has
   * therefore sent them. Before kickoff `others` simply does not contain the
   * game — the filter is a WHERE clause in api/_pickem/store.py, not something
   * this function is trusted to apply. Returns '' when there are none, so the
   * caller decides what an empty pool looks like in its own state. */
  function chips(game, others) {
    if (!others || !others.length) return '';
    var out = others.map(function (row) {
      var p = row.picks[game.game_id];
      if (!p) return '';
      // The chip is marked against the result once there is one, so a graded
      // row shows at a glance who was on the right side of it.
      var hit = game.result && game.result !== 'push' &&
        p.pick === (game.result === 'home' ? game.home : game.away);
      var cls = !game.result ? '' : (game.result === 'push' ? ' is-push'
        : (hit ? ' is-hit' : ' is-miss'));
      return '<span class="pk-chip' + cls + '" title="' + esc(row.username) +
        ' picked ' + esc(p.pick) + ' for ' + esc(p.confidence) + '">' +
        '<span class="pk-chip-who">' + esc(row.username) + '</span>' +
        '<span class="pk-chip-pick">' + esc(p.pick) + '</span>' +
        '<span class="pk-chip-conf">' + esc(p.confidence) + '</span></span>';
    }).filter(Boolean).join('');
    return out;
  }

  function pkGameRow(game, picks, others, n) {
    if (game.spread_home === null || game.spread_home === undefined) {
      // Off the board: no line ever froze for it, so there is nothing to grade
      // a pick against. Shown rather than hidden, because a missing row reads
      // as a bug and this is a stated outcome.
      return '<div class="pk-game is-off">' + timeCell(game) +
        '<span class="pk-off">' + esc(game.away) + ' at ' + esc(game.home) +
        ' — no line was available at the deadline, so this game is not ' +
        'part of the week.</span></div>';
    }
    return '<div class="pk-game' + (game.locked ? ' is-locked' : '') +
      (game.result ? ' is-final' : '') + '" data-game="' + esc(game.game_id) + '">' +
      timeCell(game) +
      '<span class="pk-matchup">' +
        sideButton(game, 'away', picks) +
        '<span class="pk-at">@</span>' +
        sideButton(game, 'home', picks) +
      '</span>' +
      confidenceCell(game, picks, n) +
      stateCell(game, picks, others) +
      '</div>';
  }

  /* The week, grouped by calendar day so it reads Thu / Sun / Mon the way the
   * schedule page does. */
  function pkRenderWeek(games, picks, others, n) {
    if (!games || !games.length) {
      return '<p class="pk-empty">This week has not been opened yet. Lines are ' +
        'frozen at 3:00 AM ET on Tuesday.</p>';
    }
    var f = formats();
    var html = '', lastKey = null;
    games.forEach(function (g) {
      var d = toDate(g.kickoff);
      var key = d ? f.dayKey.format(d) : 'tbd';
      if (key !== lastKey) {
        if (lastKey !== null) html += '</div>';
        html += '<div class="pk-day"><h3>' +
          esc(d ? f.dayLong.format(d) : 'Time to be announced') + '</h3></div>' +
          '<div class="pk-rows">';
        lastKey = key;
      }
      html += pkGameRow(g, picks, others, n);
    });
    return html + '</div>';
  }

  /* ---------- standings ---------- */

  /* Rank, player, one column per graded week, total, correct.
   *
   * The week cells carry a bare --heat number rather than a colour, so the
   * scale re-mixes on a theme change without the table being rebuilt — the
   * discipline ARCHITECTURE.md describes for every data-driven colour here.
   * Normalised against the best score in each column rather than against the
   * week's maximum: a week nobody did well in should still show who did best.
   */
  function pkStandingsTable(data, options) {
    var opts = options || {};
    var rows = data.rows || [];
    if (!rows.length) {
      return '<p class="pk-empty">No picks have been made yet.</p>';
    }
    var weeks = (data.weeks || []).slice();
    var single = data.week != null;

    var best = {};
    weeks.forEach(function (wk) {
      best[wk] = rows.reduce(function (m, r) {
        var cell = r.byWeek[String(wk)];
        return Math.max(m, cell ? cell.points : 0);
      }, 0);
    });

    var head = '<tr><th class="pk-rank">#</th><th class="pk-who">Player</th>' +
      (single ? '' : weeks.map(function (wk) {
        return '<th class="pk-wk">' +
          '<a href="?week=' + esc(wk) + '" title="Week ' + esc(wk) + ' only">' +
          esc(wk) + '</a></th>';
      }).join('')) +
      '<th class="pk-total">Points</th><th class="pk-correct">Correct</th>' +
      (single ? '' : '<th class="pk-pending">Open</th>') + '</tr>';

    var body = rows.map(function (r) {
      var cells = single ? '' : weeks.map(function (wk) {
        var cell = r.byWeek[String(wk)];
        if (!cell) return '<td class="pk-wk is-none">–</td>';
        var heat = best[wk] ? (cell.points / best[wk]).toFixed(3) : '0';
        return '<td class="pk-wk" style="--heat:' + heat + '" ' +
          'title="' + esc(cell.correct) + ' of ' +
          esc(cell.picked - cell.pending) + ' graded' +
          (cell.pending ? ', ' + esc(cell.pending) + ' still open' : '') + '">' +
          esc(cell.points) + '</td>';
      }).join('');
      return '<tr' + (opts.me && opts.me === r.user_id ? ' class="is-me"' : '') + '>' +
        '<td class="pk-rank">' + esc(r.rank) + '</td>' +
        '<td class="pk-who">' + esc(r.username) + '</td>' + cells +
        '<td class="pk-total">' + esc(r.points) + '</td>' +
        '<td class="pk-correct">' + esc(r.correct) + '<span class="pk-of">/' +
          esc(r.picked - r.pending) + '</span></td>' +
        (single ? '' : '<td class="pk-pending">' +
          (r.pending ? esc(r.pending) : '–') + '</td>') +
        '</tr>';
    }).join('');

    return '<div class="pk-table-wrap"><table class="pk-table">' +
      '<thead>' + head + '</thead><tbody>' + body + '</tbody></table></div>';
  }

  // The top few, for the hub. Same numbers, no week columns and no scrolling.
  function pkMiniStandings(data, limit) {
    var rows = (data.rows || []).slice(0, limit || 5);
    if (!rows.length) return '<p class="pk-empty">No picks have been made yet.</p>';
    return '<ol class="pk-mini">' + rows.map(function (r) {
      return '<li><span class="pk-mini-rank">' + esc(r.rank) + '</span>' +
        '<span class="pk-mini-who">' + esc(r.username) + '</span>' +
        '<span class="pk-mini-pts">' + esc(r.points) + '</span></li>';
    }).join('') + '</ol>';
  }

  global.PICKEM_TZ = TZ;
  global.pkEsc = esc;
  global.pkSpreadFor = spreadFor;
  global.pkSpreadLabel = pkSpreadLabel;
  global.pkKickoffLabel = pkKickoffLabel;
  global.pkTimeLabel = function (iso) { var d = toDate(iso); return d ? timeLabel(d) : 'TBD'; };
  global.pkPickCount = pkPickCount;
  global.pkTogglePick = pkTogglePick;
  global.pkClearPick = pkClearPick;
  global.pkSetConfidence = pkSetConfidence;
  global.pkToPayload = pkToPayload;
  global.pkFromServer = pkFromServer;
  global.pkGameRow = pkGameRow;
  global.pkRenderWeek = pkRenderWeek;
  global.pkStandingsTable = pkStandingsTable;
  global.pkMiniStandings = pkMiniStandings;
})(window);
