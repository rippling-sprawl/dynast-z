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
 * CONFIDENCE IS POSITION, NOT AN INPUT
 *
 * The board is one ordered list of the week's games, best at the top, and a
 * game's confidence is simply where it sits: the top row is N, the bottom is 1.
 * Nothing is typed and nothing is chosen from a menu, so a duplicate or an
 * out-of-range value is not rejected — it cannot be expressed. Ranking is what
 * the reader is actually doing, and a list they drag is a truer instrument for
 * it than sixteen selects that each have to be reconciled against the others.
 *
 * Because the order no longer follows the schedule, the day headers are gone
 * and every row carries its own date. A row can sit above a game three days
 * earlier, so a header saying "Sunday" over it would be a lie.
 *
 * LOCKED ROWS ARE ANCHORS
 *
 * A game that has kicked off keeps the confidence it was saved with — that is
 * the whole point of the lock — so it cannot be renumbered by somebody else
 * being dragged past it. It stays in the list at its own value, is not
 * draggable, and the free values flow around it. See pkAssign.
 *
 * The server validates all of this again (api/_pickem/scoring.py) — it has to,
 * since the client is not trusted — but a page that can only ever submit a
 * legal week never has to explain a rejection.
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
        // "Sun Sep 13" — the row's own date, now that the list is ordered by
        // rank and no day header sits above it to say which day it is.
        dayRow: new Intl.DateTimeFormat('en-US', { weekday: 'short', month: 'short', day: 'numeric', timeZone: TZ }),
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

  /* "Saved as of 3:31 PM", or with the date when it was not today. Eastern,
   * like every other time on these pages — a save stamp in one zone beside
   * kickoffs in another is the kind of small inconsistency that makes a reader
   * doubt the deadline copy. */
  function pkSavedLabel(iso) {
    var d = toDate(iso);
    if (!d) return '';
    var f = formats();
    var today = f.dayKey.format(d) === f.dayKey.format(new Date());
    return 'Saved as of ' + (today ? '' : f.dayRow.format(d) + ', ') + f.time.format(d);
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

  /* ---------- the confidence model ----------
   *
   * Two pieces of state, deliberately separate:
   *
   *   order   an array of game ids, best first. This is what the reader drags.
   *   sides   { game_id: 'GB' } — which team, for the games they have taken a
   *           side on. A game can sit in the order without a side; it simply
   *           scores nothing.
   *
   * Confidence is never stored, only derived from `order` by pkAssign. That is
   * what makes a duplicate impossible rather than merely invalid.
   */

  function pkPickCount(sides) {
    return Object.keys(sides).length;
  }

  /* Confidence for every game in `order`. Locked games keep the value they were
   * saved with; everything else takes the remaining values, highest first.
   *
   * -> { game_id: confidence }
   */
  function pkAssign(order, locked, n) {
    var used = {}, key;
    for (key in locked) if (locked.hasOwnProperty(key)) used[locked[key]] = true;

    var free = [];
    for (var v = n; v >= 1; v--) if (!used[v]) free.push(v);

    var out = {}, i = 0;
    order.forEach(function (gameId) {
      if (locked.hasOwnProperty(gameId)) out[gameId] = locked[gameId];
      else if (i < free.length) out[gameId] = free[i++];
    });
    return out;
  }

  /* The order to open on.
   *
   * A saved week has to come back exactly as it was left, so a game with a
   * stored confidence claims that slot outright. The games with no stored pick
   * then fill whatever is left, in kickoff order, which is the only sensible
   * default for a row nobody has ranked yet.
   */
  function pkInitialOrder(games, mine) {
    var pickable = games.filter(function (g) {
      return g.spread_home !== null && g.spread_home !== undefined;
    });
    var n = pickable.length;
    var slots = {};                       // confidence -> game_id
    var rest = [];

    pickable.forEach(function (g) {
      var saved = mine[g.game_id];
      var c = saved && saved.confidence;
      if (c && c >= 1 && c <= n && !slots[c]) slots[c] = g.game_id;
      else rest.push(g.game_id);
    });

    var order = [];
    for (var v = n; v >= 1; v--) {
      order.push(slots[v] || rest.shift());
    }
    return order.filter(Boolean);
  }

  /* The order a drop produced, made presentable. The DOM order after a live
   * reorder is exactly where the reader put the row; this is that order with
   * the locked rows settled back onto their own numbers. */
  function pkAfterDrop(domOrder, locked, n) {
    return pkNormalise(domOrder, locked, n);
  }

  /* Sort an order so the confidence column reads straight down.
   *
   * This is not cosmetic. A locked row holds its own value while the free
   * values flow around it, so the raw drop order can assign 6, 5, 3, 4, 2, 1
   * top to bottom — a ranked list whose ranks are out of order, which is
   * nonsense on a board whose entire premise is "best at the top". Re-sorting
   * by the assigned value puts the locked row back where its number says it
   * belongs and everything else either side of it.
   *
   * One pass is enough: re-assigning over the sorted order yields the same map,
   * because the free values were already handed out in descending order and
   * sorting only moves the locked rows among them. */
  function pkNormalise(order, locked, n) {
    var conf = pkAssign(order, locked, n);
    return order.slice().sort(function (a, b) {
      return (conf[b] || 0) - (conf[a] || 0);
    });
  }

  /* Move one game to a new index. Returns a new array; the old one is left
   * alone so a refused save can put it back. */
  function pkMove(order, gameId, toIndex, locked, n) {
    var next = order.slice();
    var from = next.indexOf(gameId);
    if (from < 0) return order;
    next.splice(from, 1);
    next.splice(Math.max(0, Math.min(next.length, toIndex)), 0, gameId);
    return locked ? pkNormalise(next, locked, n) : next;
  }

  /* Take or drop a side. A second tap on the side already taken clears it, and
   * clearing a side does NOT remove the game from the order — its rank is
   * still meaningful the moment a side is taken again. */
  function pkToggleSide(sides, gameId, side) {
    var next = {}, key;
    for (key in sides) if (sides.hasOwnProperty(key)) next[key] = sides[key];
    if (next[gameId] === side) delete next[gameId];
    else next[gameId] = side;
    return next;
  }

  // The wire shape: only the games a side has been taken on, each carrying the
  // confidence its position gives it.
  function pkToPayload(order, sides, locked, n) {
    var conf = pkAssign(order, locked, n);
    return order.filter(function (gameId) {
      return sides[gameId] && conf[gameId];
    }).map(function (gameId) {
      return { game_id: gameId, pick: sides[gameId], confidence: conf[gameId] };
    });
  }

  // The server's `mine` map, split into the two pieces of state above.
  function pkSidesFromServer(mine) {
    var sides = {}, key;
    for (key in mine) {
      if (mine.hasOwnProperty(key) && mine[key] && mine[key].pick) {
        sides[key] = mine[key].pick;
      }
    }
    return sides;
  }

  // Locked games keep whatever they were saved with. A locked game with no
  // saved pick has no value to protect and is left out, so its slot stays free.
  function pkLockedFromServer(games, mine) {
    var locked = {};
    games.forEach(function (g) {
      var saved = mine[g.game_id];
      if (g.locked && saved && saved.confidence) locked[g.game_id] = saved.confidence;
    });
    return locked;
  }

  /* ---------- rows ---------- */

  function teamCell(abbr, line) {
    return '<img class="pk-logo" src="' + LOGO_DIR + esc(abbr) + '.svg" alt="" ' +
      'aria-hidden="true" loading="lazy">' +
      '<span class="pk-meta">' +
        '<span class="pk-abbr">' + esc(abbr) + '</span>' +
        (line ? '<span class="pk-line">' + esc(line) + '</span>' : '') +
      '</span>';
  }

  function sideButton(game, side, sides) {
    var abbr = side === 'home' ? game.home : game.away;
    var chosen = sides[game.game_id] === abbr;
    var covered = game.result === side;
    return '<button type="button" class="pk-side' +
      (chosen ? ' is-picked' : '') + (covered ? ' is-covered' : '') +
      '" data-game="' + esc(game.game_id) + '" data-side="' + esc(abbr) + '"' +
      (game.locked ? ' disabled' : '') +
      ' aria-pressed="' + (chosen ? 'true' : 'false') + '">' +
      teamCell(abbr, pkSpreadLabel(spreadFor(game, side))) + '</button>';
  }

  /* The centre of the matchup: the separator, then when the game is, stacked
   * under it. It sits between the two crests because that is the one place in
   * the row that is about the fixture rather than about either side of it —
   * and with the list ordered by rank rather than by day, the date has to be on
   * the row or it is nowhere. */
  function centreCell(game) {
    var d = toDate(game.kickoff);
    return '<span class="pk-centre">' +
      '<span class="pk-at">@</span>' +
      '<span class="pk-date">' + esc(d ? formats().dayRow.format(d) : 'TBD') + '</span>' +
      '<span class="pk-time">' + esc(d ? timeLabel(d) : '') + '</span>' +
    '</span>';
  }

  /* The confidence, on the left. A read-only field, not a control: it is the
   * row's position expressed as a number, and the way to change it is to move
   * the row. Rendering it as a <select> invited the reader to edit the one
   * thing that is now derived.
   *
   * Muted when no side has been taken — the number still says what the row
   * would be worth, which is exactly the thing worth knowing before picking.
   *
   * The tooltip names both directions because the number is a stake, not a
   * prize: a miss deducts exactly what a hit pays (a push costs nothing), and a
   * player who only ever reads "worth 16" will rank the coin-flips wrong. */
  function confidenceCell(game, sides, confidence) {
    var live = !!sides[game.game_id];
    var stake = '+' + esc(confidence) + ' if it lands, −' + esc(confidence) +
      ' if it does not';
    return '<span class="pk-conf' + (live ? '' : ' is-idle') +
      (game.locked ? ' is-locked' : '') + '"' +
      ' title="' + (live ? stake : stake + ' — once you take a side') + '">' +
      esc(confidence || '–') + '</span>';
  }

  /* The drag anchor, to the right of the matchup. A button rather than a bare
   * span so it is reachable by keyboard and announced as something operable;
   * the arrow keys move the row, which is the whole interaction for anyone not
   * using a pointer.
   *
   * A locked row shows a lock in the same cell instead: the column stays put,
   * and the reason the row will not move is where the handle would have been. */
  function dragCell(game) {
    if (game.locked) {
      return '<span class="pk-drag is-locked" title="This game has kicked off — ' +
        'its rank is fixed" aria-hidden="true">🔒</span>';
    }
    return '<button type="button" class="pk-drag" data-drag ' +
      'data-game="' + esc(game.game_id) + '" ' +
      'aria-label="Reorder ' + esc(game.away + ' at ' + game.home) +
      '. Drag, or use the arrow keys." title="Drag to reorder">' +
      '<span class="pk-grip" aria-hidden="true"></span></button>';
  }

  function stateCell(game, sides, others, confidence) {
    var mine = sides[game.game_id];
    if (game.result) {
      var verdict = game.result === 'push' ? 'Push'
        : esc(game.result === 'home' ? game.home : game.away) + ' covered';
      var score = (game.away_score === null || game.away_score === undefined) ? ''
        : ' <span class="pk-score">' + esc(game.away_score) + '–' +
          esc(game.home_score) + '</span>';
      // Three outcomes, not two: a push scores 0 and is neither a hit nor a
      // miss, so it gets its own neutral chip rather than borrowing the red
      // one and reading as a loss it is not.
      var push = game.result === 'push';
      var won = mine && !push &&
        mine === (game.result === 'home' ? game.home : game.away);
      var points = mine
        ? '<span class="pk-points ' +
            (push ? 'is-push' : (won ? 'is-hit' : 'is-miss')) + '">' +
            (push ? '0' : (won ? '+' : '−') + esc(confidence)) + '</span>'
        : '';
      return '<span class="pk-state is-final">' + verdict + score + points +
        chips(game, others) + '</span>';
    }
    if (game.locked) {
      return '<span class="pk-state is-locked">' +
        (chips(game, others) || '<span class="pk-lock">Locked</span>') + '</span>';
    }
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

  function pkGameRow(game, sides, others, confidence) {
    return '<div class="pk-game' + (game.locked ? ' is-locked' : '') +
      (game.result ? ' is-final' : '') + '" data-game="' + esc(game.game_id) + '">' +
      confidenceCell(game, sides, confidence) +
      '<span class="pk-matchup">' +
        sideButton(game, 'away', sides) +
        centreCell(game) +
        sideButton(game, 'home', sides) +
      '</span>' +
      dragCell(game) +
      stateCell(game, sides, others, confidence) +
      '</div>';
  }

  /* The board: one ranked list, best first. No day headers — the order is the
   * reader's ranking, not the schedule, so a row can sit above a game played
   * three days earlier and any header over it would be wrong.
   *
   * Games with no line are not part of the ranking at all and are listed after
   * it, so the count in the header and the length of the list agree. */
  function pkRenderWeek(games, order, sides, others, locked, n) {
    if (!games || !games.length) {
      return '<p class="pk-empty">This week has not been opened yet. Lines are ' +
        'frozen at 3:00 AM ET on Tuesday.</p>';
    }
    var byId = {};
    games.forEach(function (g) { byId[g.game_id] = g; });
    var conf = pkAssign(order, locked, n);

    var rows = order.map(function (gameId) {
      var g = byId[gameId];
      return g ? pkGameRow(g, sides, others, conf[gameId]) : '';
    }).join('');

    var off = games.filter(function (g) {
      return g.spread_home === null || g.spread_home === undefined;
    });
    var offHtml = off.length ? '<div class="pk-off-list">' + off.map(function (g) {
      return '<div class="pk-game is-off">' +
        '<span class="pk-off">' + esc(g.away) + ' at ' + esc(g.home) +
        ' — no line was available at the deadline, so this game is not part ' +
        'of the week.</span></div>';
    }).join('') + '</div>' : '';

    return '<div class="pk-rows" data-sortable>' + rows + '</div>' + offHtml;
  }

  /* ---------- dragging ----------
   * Pointer Events, not HTML5 drag-and-drop: the latter does not exist on
   * touch, and the requirement is one interaction that works with a finger and
   * a mouse alike.
   *
   * WHY THE DRAGGED ROW IS NEVER MOVED IN THE DOM
   *
   * The first version reordered the list live — insertBefore on the row under
   * the pointer, every move. On a mouse that works. On a phone it dies after
   * one frame, and the reason is worth writing down: a touch pointer is
   * *implicitly captured* to the element that received pointerdown, and moving
   * that element in the DOM tears the capture down. insertBefore on a node that
   * is already in the tree is a remove-then-insert, so the very first reorder
   * detached the row containing the handle the finger was holding, capture was
   * lost, and no further pointermove was ever delivered. Nothing threw; the row
   * simply stopped following.
   *
   * So the dragged row stays exactly where it is in the DOM for the whole
   * gesture. It is lifted out of flow with position:fixed and follows the
   * pointer, a placeholder of the same height holds its gap, and it is the
   * *placeholder* that moves between the other rows. The row is put back in the
   * placeholder's slot once, on release, when losing capture no longer matters.
   *
   * The move and release listeners go on `document` rather than the container
   * for the same family of reasons: a fixed-position row can end up over
   * another element, and a listener scoped to the list would miss the release
   * if the finger left it.
   */
  function pkDragList(container, onDrop) {
    var row = null;           // the .pk-game being moved
    var holder = null;        // the placeholder standing in its gap
    var pointerId = null;
    var grabDy = 0;           // where in the row the pointer took hold
    var scroller = null;
    var edgeDy = 0;

    function others() {
      return Array.prototype.filter.call(
        container.querySelectorAll('.pk-game'),
        function (el) { return el !== row; });
    }

    function orderNow() {
      return Array.prototype.map.call(
        container.querySelectorAll('.pk-game'),
        function (el) { return el.getAttribute('data-game'); });
    }

    /* Auto-scroll when the pointer is held near the top or bottom of the
     * viewport. Without it a sixteen-row board cannot be reordered on a phone:
     * the row you want is off-screen and the page will not scroll, because the
     * gesture belongs to the drag. The row is positioned against the viewport,
     * so it stays under the finger while the page moves beneath it. */
    function tick() {
      if (!row) { scroller = null; return; }
      if (edgeDy) {
        window.scrollBy(0, edgeDy);
        place(lastY);
      }
      scroller = window.requestAnimationFrame(tick);
    }

    var lastY = 0;

    function place(clientY) {
      lastY = clientY;
      row.style.top = (clientY - grabDy) + 'px';

      // The placeholder goes before the first remaining row whose midpoint is
      // below the pointer. A locked row is a legitimate landing site — it is
      // only undraggable itself — so nothing is skipped here.
      var target = null;
      others().some(function (el) {
        var box = el.getBoundingClientRect();
        if (clientY < box.top + box.height / 2) { target = el; return true; }
        return false;
      });
      if (target) container.insertBefore(holder, target);
      else container.appendChild(holder);
    }

    function start(e) {
      if (row) return;                                   // one drag at a time
      var handle = e.target.closest ? e.target.closest('[data-drag]') : null;
      if (!handle || !container.contains(handle)) return;
      if (handle.classList.contains('is-locked')) return;
      var target = handle.closest('.pk-game');
      if (!target || target.classList.contains('is-locked')) return;

      var box = target.getBoundingClientRect();
      row = target;
      pointerId = e.pointerId;
      grabDy = e.clientY - box.top;

      holder = document.createElement('div');
      holder.className = 'pk-placeholder';
      holder.style.height = box.height + 'px';
      container.insertBefore(holder, row.nextSibling);

      // Lifted out of flow, pinned to the viewport. Width is frozen because a
      // fixed element no longer inherits the grid track it was sitting in.
      row.style.position = 'fixed';
      row.style.left = box.left + 'px';
      row.style.width = box.width + 'px';
      row.style.top = box.top + 'px';
      row.classList.add('is-dragging');
      container.classList.add('is-reordering');

      document.addEventListener('pointermove', move, { passive: false });
      document.addEventListener('pointerup', end);
      document.addEventListener('pointercancel', end);

      place(e.clientY);
      if (!scroller) scroller = window.requestAnimationFrame(tick);
      e.preventDefault();
    }

    function move(e) {
      if (!row || e.pointerId !== pointerId) return;
      // Non-passive so this actually suppresses the scroll on a browser that
      // has not honoured touch-action for some reason.
      e.preventDefault();
      var EDGE = 72, SPEED = 12;
      if (e.clientY < EDGE) edgeDy = -SPEED;
      else if (e.clientY > window.innerHeight - EDGE) edgeDy = SPEED;
      else edgeDy = 0;
      place(e.clientY);
    }

    function end(e) {
      if (!row || (e && e.pointerId !== pointerId)) return;
      document.removeEventListener('pointermove', move);
      document.removeEventListener('pointerup', end);
      document.removeEventListener('pointercancel', end);
      if (scroller) { window.cancelAnimationFrame(scroller); scroller = null; }
      edgeDy = 0;

      // The one DOM move of the whole gesture, now that capture is spent.
      container.insertBefore(row, holder);
      holder.parentNode.removeChild(holder);
      row.removeAttribute('style');
      row.classList.remove('is-dragging');
      container.classList.remove('is-reordering');

      var settled = orderNow();
      row = null; holder = null; pointerId = null;
      onDrop(settled);
    }

    container.addEventListener('pointerdown', start);

    /* Keyboard equivalent. A ranking that can only be made by dragging is a
     * ranking some people cannot make at all, and the arrow keys are a few
     * lines on top of the model already here. */
    container.addEventListener('keydown', function (e) {
      if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
      var handle = e.target.closest ? e.target.closest('[data-drag]') : null;
      if (!handle || handle.classList.contains('is-locked')) return;
      e.preventDefault();
      var order = orderNow();
      var gameId = handle.getAttribute('data-game');
      var i = order.indexOf(gameId);
      var to = e.key === 'ArrowUp' ? i - 1 : i + 1;
      if (i < 0 || to < 0 || to >= order.length) return;
      // The caller normalises; see pkAfterDrop.
      onDrop(pkMove(order, gameId, to), gameId);
    });
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

    // Clamped at 0 on both ends: week totals can be negative now that a wrong
    // pick deducts, and a negative ratio would either invert the scale or paint
    // a losing week as the hottest cell in the column.
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
        var heat = best[wk] > 0
          ? (Math.max(cell.points, 0) / best[wk]).toFixed(3) : '0';
        return '<td class="pk-wk' + (cell.points < 0 ? ' is-down' : '') +
          '" style="--heat:' + heat + '" ' +
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
  global.pkSavedLabel = pkSavedLabel;
  global.pkPickCount = pkPickCount;
  global.pkAssign = pkAssign;
  global.pkInitialOrder = pkInitialOrder;
  global.pkMove = pkMove;
  global.pkNormalise = pkNormalise;
  global.pkAfterDrop = pkAfterDrop;
  global.pkToggleSide = pkToggleSide;
  global.pkToPayload = pkToPayload;
  global.pkSidesFromServer = pkSidesFromServer;
  global.pkLockedFromServer = pkLockedFromServer;
  global.pkGameRow = pkGameRow;
  global.pkRenderWeek = pkRenderWeek;
  global.pkDragList = pkDragList;
  global.pkStandingsTable = pkStandingsTable;
  global.pkMiniStandings = pkMiniStandings;
})(window);
