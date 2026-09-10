/* Shared Survivor rendering. Three pages use this: the hub, the pick board and
 * the standings. Everything here either returns an HTML string or reads a plain
 * payload — no DOM, no fetching, no page state, the same discipline
 * scripts/primary/pickem.js follows. The pages own their state and their event
 * wiring; this owns what a row looks like.
 *
 * WHY THIS LOADS pickem.js AND WEARS pickem.css
 *
 * Survivor and the Pick 'Em are two games played on one board. The fixture, the
 * crest, the kickoff in Eastern, the way a spread is written — none of that is
 * different here, and a second implementation of it would drift: the Pick 'Em
 * would drop the meridiem from a kickoff and Survivor would keep it, and the
 * reader crossing between them would find two apps. So the vocabulary is
 * imported (pkEsc, pkKickoffLabel, pkSpreadFor, pkSpreadLabel) and the class
 * names are the same .pk-* ones, and what this file adds is only the part where
 * the two games actually differ.
 *
 * WHAT THE TWO GAMES ACTUALLY DIFFER ON
 *
 *   one pick, not sixteen   so there is no ranking, no drag handle, no
 *                           confidence column, and the row is just a matchup.
 *   straight up, not ATS    so a game whose line never froze is on this board
 *                           like any other. The spread is still printed, greyed
 *                           — it is not what you are graded on and it is still
 *                           the best one-number answer to "who wins".
 *   a team is spent         so a side you have already used is rendered dead,
 *                           carrying the week you spent it in. This is the rule
 *                           that makes the game, and the board is where it has
 *                           to be legible. The server refuses a reused team and
 *                           a unique index refuses it again — the grey is not
 *                           the enforcement, it is the explanation.
 *
 * Everything is ES5 globals, like the rest of scripts/ — no modules.
 */
(function (global) {
  'use strict';

  var LOGO_DIR = '/assets/icons/nfl/';

  function esc(s) { return global.pkEsc(s); }

  /* ---------- one side of a matchup ----------
   *
   * Four states, and they are not mutually exclusive in the data, so the order
   * they are resolved in is the order of what the reader most needs to know:
   *
   *   used     spent in an earlier week. Dead, and says which week.
   *   picked   this week's pick.
   *   won/lost once the game is final, which side actually won it.
   *
   * A used team is disabled rather than merely dimmed. The rule is absolute, so
   * offering the tap and then refusing it server-side would be a worse way of
   * saying the same thing.
   */
  function sideButton(game, side, ctx) {
    var abbr = side === 'home' ? game.home : game.away;
    var chosen = ctx.pick && ctx.pick.game_id === game.game_id && ctx.pick.team === abbr;
    var spentIn = ctx.used[abbr];
    var used = spentIn !== undefined && spentIn !== null && !chosen;
    var winner = svWinner(game);
    // Two reasons a side cannot be tapped, and being eliminated is no longer one
    // of them: a spent team (the rule is absolute) and a kicked-off game (the
    // lock). There is no whole-board read-only state any more, which is why the
    // ctx flag that used to carry one is gone rather than left set to false.
    var dead = used || game.locked;

    var cls = ['pk-side', 'sv-side'];
    if (chosen) cls.push('is-picked');
    if (used) cls.push('is-used');
    if (winner === abbr) cls.push('is-covered');
    if (winner && winner !== 'tie' && winner !== abbr) cls.push('sv-fell');

    var line = global.pkSpreadLabel(global.pkSpreadFor(game, side));

    return '<button type="button" class="' + cls.join(' ') + '"' +
      ' data-game="' + esc(game.game_id) + '" data-team="' + esc(abbr) + '"' +
      (dead ? ' disabled' : '') +
      ' aria-pressed="' + (chosen ? 'true' : 'false') + '"' +
      ' title="' + (used ? 'Already used in week ' + esc(spentIn)
                         : esc(game.away + ' at ' + game.home)) + '">' +
      '<img class="pk-logo" src="' + LOGO_DIR + esc(abbr) + '.svg" alt="" ' +
        'aria-hidden="true" loading="lazy">' +
      '<span class="pk-meta">' +
        '<span class="pk-abbr">' + esc(abbr) + '</span>' +
        (line ? '<span class="pk-line sv-line">' + esc(line) + '</span>' : '') +
      '</span>' +
      (used ? '<span class="sv-spent">Used wk ' + esc(spentIn) + '</span>' : '') +
      '</button>';
  }

  /* The centre of the matchup: the separator, when the game is, and the way out
   * to the game's own page, stacked. Identical to the Pick 'Em's, deliberately —
   * see the header. The link comes from pickem.js rather than being written
   * again: the id it points at is the same id, and two copies of a URL is how
   * one of them ends up on last season's route. */
  function centreCell(game) {
    return '<span class="pk-centre">' +
      '<span class="pk-at">@</span>' +
      '<span class="pk-date">' + esc(svDayLabel(game.kickoff)) + '</span>' +
      '<span class="pk-time">' + esc(svTimeLabel(game.kickoff)) + '</span>' +
      global.pkViewLink(game) +
    '</span>';
  }

  /* ---------- results ----------
   * Straight up, off the score. The client re-derives what
   * api/_survivor/rules.py derives rather than being told, for the same reason
   * the Pick 'Em recomputes its confidences locally: a board that can only
   * describe itself after a round trip flickers.
   *
   * `null` is "no verdict yet" and 'tie' is a real outcome. Keeping them apart
   * is the whole point — one of them ends a season and the other does not. */
  function svWinner(game) {
    if (game.away_score === null || game.away_score === undefined) return null;
    if (game.home_score === null || game.home_score === undefined) return null;
    if (game.status !== 'final') return null;
    if (game.home_score > game.away_score) return game.home;
    if (game.away_score > game.home_score) return game.away;
    return 'tie';
  }

  // 'win' | 'loss' | 'tie' | 'pending' — what this game did to a pick on it.
  function svOutcome(game, team) {
    var winner = svWinner(game);
    if (winner === null) return 'pending';
    if (winner === 'tie') return 'tie';
    return winner === team ? 'win' : 'loss';
  }

  var OUTCOME_WORD = {
    win: 'Survived', loss: 'Eliminated', tie: 'Eliminated — tie',
    pending: 'In progress', void: 'After elimination', none: 'No pick'
  };

  /* ---------- the state line ----------
   * The result, then what it did to you, then everyone else who was on this
   * game. Its own line under the matchup rather than a trailing cell, the same
   * shape the Pick 'Em settled on: there can be one chip per player. */
  function stateCell(game, ctx) {
    var bits = [];
    var winner = svWinner(game);
    var mine = ctx.pick && ctx.pick.game_id === game.game_id ? ctx.pick.team : null;

    if (winner) {
      bits.push('<span class="sv-verdict">' +
        (winner === 'tie' ? 'Tie'
          : esc(winner) + ' won') +
        ' <span class="pk-score">' + esc(game.away_score) + '–' +
          esc(game.home_score) + '</span></span>');
      if (mine) {
        var outcome = svOutcome(game, mine);
        bits.push('<span class="sv-badge is-' + outcome + '">' +
          esc(OUTCOME_WORD[outcome]) + '</span>');
      }
    } else if (game.locked) {
      bits.push('<span class="pk-lock">' +
        (game.status === 'live' ? 'In progress' : 'Locked') + '</span>');
    }

    var pool = chips(game, ctx);
    if (pool) bits.push(pool);
    if (!bits.length) return '';
    return '<span class="pk-state' + (winner ? ' is-final' : '') + '">' +
      bits.join('') + '</span>';
  }

  /* Everyone else riding this game, once it has kicked off and the server has
   * therefore sent it. Before kickoff `others` simply carries no team for the
   * week — the filter is a WHERE clause in api/_survivor/store.py, not
   * something this function is trusted to apply. */
  function chips(game, ctx) {
    if (!ctx.others || !ctx.others.length) return '';
    var winner = svWinner(game);
    return ctx.others.map(function (row) {
      if (!row.team || row.game_id !== game.game_id) return '';
      var cls = !winner ? ''
        : (winner === 'tie' ? ' is-miss'
          : (row.team === winner ? ' is-hit' : ' is-miss'));
      return '<span class="pk-chip' + cls + '" title="' + esc(row.username) +
        ' is riding ' + esc(row.team) + '">' +
        '<span class="pk-chip-who">' + esc(row.username) + '</span>' +
        '<span class="pk-chip-pick">' + esc(row.team) + '</span></span>';
    }).join('');
  }

  function svGameRow(game, ctx) {
    var winner = svWinner(game);
    return '<div class="pk-game sv-game' +
      (game.locked ? ' is-locked' : '') + (winner ? ' is-final' : '') +
      '" data-game="' + esc(game.game_id) + '">' +
      '<span class="pk-matchup">' +
        sideButton(game, 'away', ctx) +
        centreCell(game) +
        sideButton(game, 'home', ctx) +
      '</span>' +
      stateCell(game, ctx) +
      '</div>';
  }

  /* ---------- the board ----------
   *
   * Grouped by day and in kickoff order, which is where this parts company with
   * the Pick 'Em. There the list is the reader's own ranking, so no day header
   * could sit over it honestly; here there is nothing to rank — one pick out of
   * sixteen games — and the question the reader is actually asking is "what is
   * on this week", which is a schedule. So the schedule is what it renders.
   *
   * ctx = { pick, used, others }
   */
  function svRenderWeek(games, ctx) {
    if (!games || !games.length) {
      return '<p class="pk-empty">This week is not on the board yet. Weeks open ' +
        'when their lines are captured, at 3:00 AM ET on Tuesday.</p>';
    }
    var out = '', day = null;
    games.forEach(function (game) {
      var key = svDayKey(game.kickoff);
      if (key !== day) {
        if (day !== null) out += '</div>';
        out += '<div class="pk-day"><h3>' + esc(svDayHeading(game.kickoff)) +
          '</h3></div><div class="pk-rows">';
        day = key;
      }
      out += svGameRow(game, ctx);
    });
    return out + (day === null ? '' : '</div>');
  }

  /* ---------- time ----------
   * Eastern, always, for the reason pickem.js gives: it is the zone the league
   * schedules in. The formatters are built once. */

  var TZ = 'America/New_York';
  var fmt = null;

  function formats() {
    if (!fmt) {
      fmt = {
        dayLong: new Intl.DateTimeFormat('en-US', { weekday: 'long', month: 'long', day: 'numeric', timeZone: TZ }),
        dayKey: new Intl.DateTimeFormat('en-CA', { year: 'numeric', month: '2-digit', day: '2-digit', timeZone: TZ }),
        dayRow: new Intl.DateTimeFormat('en-US', { weekday: 'short', month: 'short', day: 'numeric', timeZone: TZ }),
        time: new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit', timeZone: TZ })
      };
    }
    return fmt;
  }

  function toDate(iso) {
    return iso ? new Date(String(iso).replace(' ', 'T')) : null;
  }

  function svDayKey(iso) {
    var d = toDate(iso);
    return d ? formats().dayKey.format(d) : 'tbd';
  }

  function svDayHeading(iso) {
    var d = toDate(iso);
    return d ? formats().dayLong.format(d) : 'Date to be confirmed';
  }

  function svDayLabel(iso) {
    var d = toDate(iso);
    return d ? formats().dayRow.format(d) : 'TBD';
  }

  // "1:00" — the meridiem is dropped for the reason pickem.js drops it: no NFL
  // game starts in the morning except the international window, which the date
  // beside it names.
  function svTimeLabel(iso) {
    var d = toDate(iso);
    if (!d) return '';
    return formats().time.formatToParts(d).filter(function (p) {
      return p.type !== 'dayPeriod' && !(p.type === 'literal' && p.value !== ':');
    }).map(function (p) { return p.value; }).join('');
  }

  /* ---------- entry state ----------
   * The one sentence the whole pool is about. Rendered from the walk the server
   * did (api/_survivor/rules.walk_entry), never re-derived here: elimination is
   * a chain over the season and this file only ever sees one week of it. */

  function svEntryWord(entry) {
    if (!entry || !entry.entered) return 'Not entered';
    return entry.status === 'out' ? 'Eliminated' : 'Alive';
  }

  var OUT_REASON = {
    loss: 'your team lost',
    tie: 'your team tied, which counts as a loss',
    nopick: 'no pick was made'
  };

  function svEntryLine(entry) {
    if (!entry || !entry.entered) {
      return 'Pick a team to enter. Whichever week you start in is the week ' +
        'your entry begins.';
    }
    if (entry.status === 'out') {
      return 'Out in week ' + entry.out_week + ' — ' +
        (OUT_REASON[entry.out_reason] || 'eliminated') + '. ' +
        entry.survived + (entry.survived === 1 ? ' week' : ' weeks') + ' survived.';
    }
    return entry.survived + (entry.survived === 1 ? ' week' : ' weeks') +
      ' survived · ' + entry.teams.length +
      (entry.teams.length === 1 ? ' team' : ' teams') + ' spent · ' +
      (32 - entry.teams.length) + ' left to choose from';
  }

  function svEntryBadge(entry) {
    var word = svEntryWord(entry);
    var kind = !entry || !entry.entered ? 'idle'
      : (entry.status === 'out' ? 'out' : 'alive');
    return '<span class="sv-status is-' + kind + '">' + esc(word) + '</span>';
  }

  /* ---------- the teams you have spent ----------
   * A crest strip rather than a list of abbreviations: the board greys the same
   * crests, so the two read as the same fact. Ordered by the week they went in,
   * which is the order they will be asked about. */
  function svSpentStrip(entry) {
    if (!entry || !entry.teams || !entry.teams.length) {
      return '<p class="pk-empty">No teams spent yet — all 32 are available.</p>';
    }
    var weekOf = {};
    Object.keys(entry.weeks || {}).forEach(function (wk) {
      var cell = entry.weeks[wk];
      if (cell && cell.team) weekOf[cell.team] = wk;
    });
    return '<div class="sv-spent-strip">' + entry.teams.map(function (abbr) {
      var wk = weekOf[abbr];
      var cell = wk ? entry.weeks[wk] : null;
      return '<span class="sv-spent-item is-' + esc((cell && cell.outcome) || 'pending') +
        '" title="Week ' + esc(wk) + ' — ' + esc(abbr) + '">' +
        '<img src="' + LOGO_DIR + esc(abbr) + '.svg" alt="" aria-hidden="true" ' +
          'loading="lazy">' +
        '<span class="sv-spent-wk">' + esc(wk) + '</span></span>';
    }).join('') + '</div>';
  }

  /* ---------- standings ----------
   *
   * Rank, player, status, then one column per week holding the crest of the
   * team that entry rode -- the crest alone, at a size worth reading. The
   * abbreviation is carried by the img `alt` and the cell `title` instead of a
   * span, which is where it was needed anyway: a screen reader and a hover.
   * A week whose game has not kicked off carries no team
   * in the payload, so there is nothing here to hide, and the cell says which
   * kind of nothing it is: a lock where a pick is in and unreadable (`masked`),
   * a neutral dot where no pick was made.
   *
   * The reader's own row is the exception: their own live pick IS sent, flagged
   * `hidden`, and is rendered with a dashed edge. Without it a player looking at
   * their own row on Saturday would see a blank and wonder whether the save
   * took.
   */
  function svStandingsTable(data, options) {
    var opts = options || {};
    var rows = data.rows || [];
    if (!rows.length) {
      return '<p class="pk-empty">Nobody has entered yet. The first pick of the ' +
        'season opens the pool.</p>';
    }
    var weeks = (data.weeks || []).slice();
    var games = data.games || {};

    var head = '<tr><th class="pk-rank">#</th><th class="pk-who">Player</th>' +
      '<th class="sv-st">Status</th>' +
      weeks.map(function (wk) {
        return '<th class="pk-wk">' + esc(wk) + '</th>';
      }).join('') +
      '<th class="pk-total">Won</th></tr>';

    var body = rows.map(function (r) {
      var cells = weeks.map(function (wk) {
        return svCell(r.weeks[String(wk)], games, wk);
      }).join('');
      // One class attribute, not two: a row can be both mine and eliminated,
      // and a second attr would be dropped by the parser rather than merged.
      var rowCls = [];
      if (opts.me && opts.me === r.user_id) rowCls.push('is-me');
      if (r.status === 'out') rowCls.push('sv-dead');
      return '<tr' + (rowCls.length ? ' class="' + rowCls.join(' ') + '"' : '') + '>' +
        '<td class="pk-rank">' + esc(r.rank) + '</td>' +
        global.pkWhoCell(r.username) +
        '<td class="sv-st">' + svStatusCell(r) + '</td>' + cells +
        '<td class="pk-total">' + esc(r.survived) + '</td>' +
        '</tr>';
    }).join('');

    return '<div class="pk-table-wrap"><table class="pk-table sv-table">' +
      '<thead>' + head + '</thead><tbody>' + body + '</tbody></table></div>';
  }

  function svStatusCell(row) {
    if (row.status === 'out') {
      return '<span class="sv-status is-out">Out</span>' +
        '<span class="sv-out-wk">wk ' + esc(row.out_week) + '</span>';
    }
    return '<span class="sv-status is-alive">Alive</span>';
  }

  /* One week for one player. The crest is the content — an abbreviation column
   * eighteen wide is unreadable at a glance and the whole table is a glance. */
  function svCell(cell, games, week) {
    if (!cell || !cell.team) {
      // A week that ended the entry with nothing down: the absence IS the
      // content, so it is marked rather than left as the same dash a week
      // before the entry started uses.
      if (cell && cell.outcome === 'none') {
        return '<td class="pk-wk sv-cell is-none" title="Week ' + esc(week) +
          ' — no pick, eliminated">✕</td>';
      }
      // A pick that is in but not readable yet — the server sends the cell with
      // no team on purpose. The distinction this draws is the point: a lock is
      // "they have picked", the neutral dot below is "they have not", and before
      // the mask existed both looked like the dot.
      if (cell && cell.masked) {
        // `is-void` rides along when the walk never reached the week — an entry
        // that is already out may still pick, and its hidden pick should read as
        // drained rather than as something the season still turns on.
        return '<td class="pk-wk sv-cell is-masked' +
          (cell.outcome === 'void' ? ' is-void' : '') +
          '" title="Week ' + esc(week) +
          ' — pick is in, hidden until kickoff">🔒</td>';
      }
      return '<td class="pk-wk sv-cell is-empty">·</td>';
    }
    var game = games[cell.game_id];
    var detail = 'Week ' + week + ' — ' + cell.team;
    if (game) {
      detail += ' (' + game.away + ' at ' + game.home +
        (game.away_score === null || game.away_score === undefined ? ''
          : ' ' + game.away_score + '–' + game.home_score) + ')';
    }
    if (cell.hidden) detail += ' — only you can see this until kickoff';
    return '<td class="pk-wk sv-cell is-' + esc(cell.outcome) +
      (cell.hidden ? ' is-hidden' : '') + '" title="' + esc(detail) + '">' +
      '<img src="' + LOGO_DIR + esc(cell.team) + '.svg" alt="' + esc(cell.team) +
      '" loading="lazy"></td>';
  }

  // The survivors, for the hub. Names only — the point of the card is how many
  // are left and who they are, and a week grid does not fit beside it.
  function svMiniStandings(data, limit) {
    var rows = (data.rows || []).slice(0, limit || 8);
    if (!rows.length) {
      return '<p class="pk-empty">Nobody has entered yet.</p>';
    }
    return '<ol class="pk-mini sv-mini">' + rows.map(function (r) {
      return '<li class="' + (r.status === 'out' ? 'sv-dead' : '') + '">' +
        '<span class="pk-mini-rank">' + esc(r.rank) + '</span>' +
        '<span class="pk-mini-who" title="' + esc(r.username) + '">' +
          esc(global.pkDisplayName(r.username)) + '</span>' +
        '<span class="sv-mini-state">' +
          (r.status === 'out' ? 'out wk ' + esc(r.out_week)
            : esc(r.survived) + '-0') + '</span></li>';
    }).join('') + '</ol>';
  }

  global.SURVIVOR_TZ = TZ;
  global.svWinner = svWinner;
  global.svOutcome = svOutcome;
  global.svDayLabel = svDayLabel;
  global.svTimeLabel = svTimeLabel;
  global.svGameRow = svGameRow;
  global.svRenderWeek = svRenderWeek;
  global.svEntryWord = svEntryWord;
  global.svEntryLine = svEntryLine;
  global.svEntryBadge = svEntryBadge;
  global.svSpentStrip = svSpentStrip;
  global.svStandingsTable = svStandingsTable;
  global.svMiniStandings = svMiniStandings;
})(window);
