/* The Baker's Oven — board model and rendering (window.OvenBoard).
 *
 * Rendering is two-phase on purpose:
 *   render()          full innerHTML build (boot, CSV import, sort/filter change)
 *   applyDraftState() surgical class/text patches (every poll)
 * A full rebuild on every poll would reset scroll position and kill the
 * cross-off animation while you're reading the board mid-draft.
 */
(function (global) {
  'use strict';

  var C = global.OVEN;

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  /* ---------- name keys (fallback when a row has no player_id) ---------- */

  var DEF_TEAMS = {
    cardinals: 'ARI', falcons: 'ATL', ravens: 'BAL', bills: 'BUF', panthers: 'CAR',
    bears: 'CHI', bengals: 'CIN', browns: 'CLE', cowboys: 'DAL', broncos: 'DEN',
    lions: 'DET', packers: 'GB', texans: 'HOU', colts: 'IND', jaguars: 'JAX',
    chiefs: 'KC', raiders: 'LV', chargers: 'LAC', rams: 'LAR', dolphins: 'MIA',
    vikings: 'MIN', patriots: 'NE', saints: 'NO', giants: 'NYG', jets: 'NYJ',
    eagles: 'PHI', steelers: 'PIT', '49ers': 'SF', seahawks: 'SEA',
    buccaneers: 'TB', titans: 'TEN', commanders: 'WAS',
  };

  function normName(s) {
    return String(s || '')
      .normalize('NFD').replace(/[̀-ͯ]/g, '')
      .toLowerCase()
      .replace(/\./g, '')
      .replace(/['‘’`]/g, '')
      .replace(/[-–—]/g, ' ')
      .replace(/\b(jr|sr|ii|iii|iv|v)\b/g, '')
      .replace(/[^a-z0-9 ]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }

  function normPos(p) {
    var v = String(p || '').toUpperCase().replace(/[^A-Z/]/g, '');
    if (v === 'DST' || v === 'D/ST' || v === 'DEF' || v === 'DS') return 'DEF';
    if (v === 'PK') return 'K';
    return v;
  }

  function teamFromDefenseName(name) {
    var n = normName(name);
    for (var nick in DEF_TEAMS) if (n.indexOf(nick) !== -1) return DEF_TEAMS[nick];
    return null;
  }

  // Defenses key on team code, never name — the three sources spell them three
  // different ways ("Denver Broncos" / "Broncos D/ST" / first+last name).
  function playerKey(name, pos, team) {
    var P = normPos(pos);
    if (P === 'DEF') {
      var t = (team || '').toUpperCase() || teamFromDefenseName(name);
      return 'DEF|' + (t || normName(name));
    }
    return P + '|' + normName(name);
  }

  /* ---------- board construction ---------- */

  /* Merge CSV rows with the FantasyPros snapshot.
   * FP wins for ECR/tier metadata; the CSV owns rank, tier override, and grade.
   * With no CSV at all the board seeds entirely from FP, so the page is useful
   * before anything has been uploaded. */
  function buildBoard(csvRows, fpPlayers) {
    var fpByKey = {};
    (fpPlayers || []).forEach(function (p) {
      fpByKey[playerKey(p.name, p.position, p.team)] = p;
    });

    var rows;
    if (csvRows && csvRows.length) {
      rows = csvRows.map(function (r) {
        var key = playerKey(r.name, r.pos, r.team);
        var fp = fpByKey[key];
        return {
          key: key,
          player_id: r.player_id || null,
          name: r.name,
          pos: normPos(r.pos) || (fp ? fp.position : ''),
          team: r.team || (fp ? fp.team : ''),
          myRank: r.myRank,
          tier: r.tier != null ? r.tier : (fp ? fp.tier : null),
          grade: r.grade,
          note: r.note,
          extra: r.extra || {},
          fpRank: fp ? fp.rank : null,
          fpPosRank: fp ? fp.pos_rank : null,
          onMyBoard: true,
        };
      });
    } else {
      rows = (fpPlayers || []).map(function (p, i) {
        return {
          key: playerKey(p.name, p.position, p.team),
          player_id: null,
          name: p.name, pos: p.position, team: p.team,
          myRank: i + 1, tier: p.tier, grade: null, note: '', extra: {},
          fpRank: p.rank, fpPosRank: p.pos_rank,
          onMyBoard: false,
        };
      });
    }

    rows.sort(function (a, b) {
      var ar = a.myRank == null ? Infinity : a.myRank;
      var br = b.myRank == null ? Infinity : b.myRank;
      return ar - br;
    });
    rows.forEach(function (r, i) { r.boardIndex = i; });
    return rows;
  }

  /* Heat: an explicit CSV grade wins; otherwise how far my rank sits from
   * FantasyPros consensus. Positive = I'm higher on him than the market. */
  function computeHeat(rows) {
    rows.forEach(function (r) {
      if (r.grade && C.GRADE_HEAT[r.grade] != null) {
        r.heat = C.GRADE_HEAT[r.grade];
        r.heatSource = 'grade';
      } else if (r.fpRank != null && r.myRank != null) {
        r.heat = r.fpRank - r.myRank;
        r.heatSource = 'delta';
      } else {
        r.heat = null;
        r.heatSource = null;
      }
    });

    // Smooth into visible *regions* — a run of liked players should read as one
    // continuous bar, not a scatter of individually tinted rows.
    var w = C.HEAT_WINDOW;
    rows.forEach(function (r, i) {
      var sum = 0, n = 0;
      for (var j = Math.max(0, i - (w >> 1)); j <= Math.min(rows.length - 1, i + (w >> 1)); j++) {
        if (rows[j].heat != null) { sum += rows[j].heat; n++; }
      }
      r.heatRegion = n ? sum / n : null;
    });
    return rows;
  }

  /* ---------- rendering ---------- */

  // What the "Hide: Fade" chip removes. `avoid` is the stronger of the two —
  // the CSV also accepts "hate" for it — so it goes wherever `fade` goes.
  var FADED_GRADES = { fade: true, avoid: true };

  /* The board has exactly one order: yours, ascending. There is no column
   * sorting and no sort state. Re-SORTING the board mid-draft is the one
   * interaction that can lose you a pick — the horizon markers, the tier bands
   * and your own muscle memory for where a player sits are all anchored to
   * personal-rank order, and every one of them is meaningless under a different
   * sort. Filtering subtracts rows without moving the survivors, which is why
   * that stayed.
   *
   * Dragging a row is not a sort: it EDITS that one order, in place and
   * permanently, and everything anchored to it stays true afterward because
   * personal rank is still what the board is showing. See the re-ranking
   * section below. */
  var state = {
    rows: [], rowEls: null, listEl: null, teams: {},
    drafted: {},          // key -> pick
    filters: { pos: null, hideDrafted: false, hideFade: false },
    clock: null, teamsCount: 12, myRosterId: null,
    onReorder: null, reorderWired: false,
  };

  function railFn() {
    return global.Heatmap.diverging({
      posMax: C.HEAT_MAX, negMax: C.HEAT_MAX,
      posColor: C.HEAT_POS_RGB, negColor: C.HEAT_NEG_RGB, nullColor: '',
    });
  }
  function washFn() {
    // Same ramp, scaled so alpha tops out around 0.26 — signal without hurting
    // text contrast on a dark background.
    return global.Heatmap.diverging({
      posMax: C.HEAT_MAX / 0.26, negMax: C.HEAT_MAX / 0.26,
      posColor: C.HEAT_POS_RGB, negColor: C.HEAT_NEG_RGB, nullColor: '',
    });
  }

  function visibleRows() {
    var f = state.filters;
    var out = state.rows.filter(function (r) {
      if (f.pos && r.pos !== f.pos) return false;
      if (f.hideDrafted && state.drafted[r.key]) return false;
      // Both negative grades, not just the one named on the chip: `fade` and
      // `avoid` are the two ways of saying "not for me", and hiding one while
      // leaving the other on the board is never what you meant.
      if (f.hideFade && FADED_GRADES[r.grade]) return false;
      return true;
    });
    // No re-sort: `state.rows` is already in personal-rank order from
    // buildBoard(), and filtering only removes rows from it.
    return out;
  }

  /* A graded row is colored by the grade, not by the rank delta, so name the
   * grade — otherwise a saturated rail on an unremarkable row reads as a bug.
   * Except `fade`: a fade isn't a fact about the player worth a badge, it's my
   * disinterest, so the row itself recedes instead (see .oven-row.faded).
   *
   * love/like wear a heart. An emoji is an image to a screen reader with no
   * accessible name of its own, so the word it replaced moves to aria-label —
   * and to title, so a hover still says which one it is. Shared with the
   * Targets drawer so both surfaces can never drift apart. */
  function gradeChip(r) {
    if (!r || !r.grade || r.grade === 'fade') return '';
    var icon = C.GRADE_ICON[r.grade];
    if (!icon) return '<span class="oven-grade ' + esc(r.grade) + '">' + esc(r.grade) + '</span>';
    return '<span class="oven-grade ' + esc(r.grade) + '" role="img" aria-label="' +
      esc(r.grade) + '" title="' + esc(r.grade) + '">' + icon + '</span>';
  }

  function rowHTML(r, rail, wash) {
    var heat = r.heat;
    var railC = heat == null ? '' : rail(heat);
    var washC = r.heatRegion == null ? '' : wash(r.heatRegion);
    // The position column carries the positional rank — same badge, same color,
    // one more fact. "RB7" states the position too, so nothing is lost by
    // spending the cell on it, and the row keeps a single line.
    var posLabel = r.fpPosRank || r.pos || '—';

    // No per-row tier chip: the full-width tier band already states it, and
    // repeating it 250 times competes with the heat rail for the same glance.
    //
    // Two separate affordances on the row, and they do not overlap: the row is
    // draggable to RE-RANK him (see enableReorder below), and the pin queues him
    // as a target. The pin is OvenTargets' handler and is inert on a page that
    // doesn't mount the drawer.
    return '<div class="oven-row' + (r.grade === 'fade' ? ' faded' : '') +
      '" draggable="true" data-key="' + esc(r.key) + '"' +
      (washC ? ' style="background:' + washC + '"' : '') + '>' +
      '<div class="oven-rail" style="background:' + railC + '"></div>' +
      '<div class="oven-rk">' + (r.myRank == null ? '' : r.myRank) + '</div>' +
      '<span class="player-pos pos-' + esc(r.pos || 'OTHER') + '">' + esc(posLabel) + '</span>' +
      '<div class="oven-name">' +
        // The name is its own element so the crossed-off treatment lands on it
        // alone — text-decoration propagates to descendants and a child can't
        // opt out, so the team, grade and note have to sit outside the struck
        // span rather than be un-struck inside it.
        '<div class="oven-name-main"><span class="oven-name-text">' + esc(r.name) + '</span>' +
          (r.team ? '<span class="oven-name-team">' + esc(r.team) + '</span>' : '') + gradeChip(r) +
          (r.note ? ' <span class="oven-name-note">· ' + esc(r.note) + '</span>' : '') + '</div>' +
      '</div>' +
      '<div class="oven-taken" hidden></div>' +
      '<button class="oven-pin" type="button" aria-pressed="false" aria-label="Add to targets">+</button>' +
    '</div>';
  }

  function render(listEl) {
    state.listEl = listEl || state.listEl;
    var rail = railFn(), wash = washFn();
    var rows = visibleRows();
    var scrollY = global.scrollY;

    if (!rows.length) {
      state.listEl.innerHTML = '<div class="oven-empty">No players match these filters.</div>';
      state.rowEls = new Map();
      return;
    }

    var html = [];
    // Emit each tier header once, on first appearance. Tiers are only roughly
    // contiguous in personal-rank order — promoting a player past a tier
    // boundary would otherwise ping-pong the headers (Tier 4, Tier 2, Tier 4…).
    // The board is always in that order now, so the bands always apply.
    var tierSeen = {};

    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      if (r.tier != null && !tierSeen[r.tier]) {
        tierSeen[r.tier] = true;
        html.push('<div class="oven-tiersep" data-tier="' + esc(r.tier) + '">' +
          'Tier ' + esc(r.tier) + ' <span class="tier-count"></span></div>');
      }
      html.push(rowHTML(r, rail, wash));
    }

    state.listEl.innerHTML = html.join('');
    state.rowEls = new Map();
    var els = state.listEl.querySelectorAll('.oven-row[data-key]');
    for (var k = 0; k < els.length; k++) state.rowEls.set(els[k].getAttribute('data-key'), els[k]);

    global.scrollTo(0, scrollY);
    applyDraftState(null, true);
    // A rebuild drops the targeted state off every row; the panel repaints it.
    if (global.OvenTargets) global.OvenTargets.markBoard();
  }

  /* Surgical patch — the only thing that runs on a poll. */
  function applyDraftState(newlyDrafted, skipFlash) {
    if (!state.rowEls) return;

    state.rowEls.forEach(function (el, key) {
      var pick = state.drafted[key];
      var tag = el.querySelector('.oven-taken');
      if (pick) {
        if (!el.classList.contains('gone')) {
          el.classList.add('gone');
          if (!skipFlash && newlyDrafted && newlyDrafted[key]) {
            el.classList.add('just-gone');
            (function (node) {
              setTimeout(function () { node.classList.remove('just-gone'); }, 2400);
            })(el);
          }
        }
        var mine = pick.roster_id === state.myRosterId;
        tag.hidden = false;
        tag.className = 'oven-taken' + (pick.is_keeper ? ' keeper' : (mine ? ' mine' : ''));
        var who = state.teams[pick.roster_id];
        tag.textContent = pick.is_keeper
          ? 'KEPT · ' + (who ? who.username : 'R' + pick.roster_id)
          : global.OvenDraft.roundPickLabel(pick.pick_no, state.teamsCount) +
            ' · ' + (who ? who.username : 'R' + pick.roster_id);
      } else if (el.classList.contains('gone')) {
        el.classList.remove('gone', 'just-gone');
        tag.hidden = true;
        tag.textContent = '';
      }
    });

    placeMarkers();
    updateTierCounts();
  }

  /* The spreadsheet's pick-marker column, recomputed live.
   *
   * For my k-th upcoming pick, the marker sits after (pickNo - onTheClock)
   * still-available players: "if the board goes chalk, you're choosing here."
   * Unlike the static sheet column, this honors keepers, traded picks, and
   * every pick actually made, and it rises up the board as players come off. */
  function placeMarkers() {
    if (!state.listEl) return;
    var old = state.listEl.querySelectorAll('.oven-marker, .oven-zone');
    for (var i = 0; i < old.length; i++) old[i].remove();
    state.listEl.querySelectorAll('.oven-row.atrisk').forEach(function (e) {
      e.classList.remove('atrisk');
    });

    var clock = state.clock;
    if (!clock || !clock.myUpcoming.length || clock.onTheClock == null) return;

    // Query the DOM rather than the rowEls map so this is in on-screen order,
    // which is what the marker positions are relative to.
    var avail = Array.prototype.filter.call(
      state.listEl.querySelectorAll('.oven-row[data-key]'),
      function (el) { return !state.drafted[el.getAttribute('data-key')]; }
    );

    // Every remaining pick of mine gets a horizon, not just the next few — the
    // loop runs out on its own once a marker would land past the bottom of the
    // board. The first is the signature; the rest are quiet rules that say the
    // same thing, so a scroll down the board reads as "mine, mine, mine".
    var filled = clock.filled;
    for (var m = 0; m < clock.myUpcoming.length; m++) {
      var pickNo = clock.myUpcoming[m];
      var ahead = 0;
      for (var n = clock.onTheClock; n < pickNo; n++) if (!filled[n]) ahead++;
      if (ahead >= avail.length) break;

      var target = avail[ahead];
      var label = global.OvenDraft.roundPickLabel(pickNo, state.teamsCount);
      var div = document.createElement('div');
      div.className = 'oven-marker' + (m === 0 ? ' next' : '');
      // The horizon's job is position, not count — the console carries "N away"
      // and is pinned, so both are on screen at once. Stating it twice is noise.
      div.innerHTML = m === 0
        ? '<span class="oven-marker-label">You choose from here</span>' +
          '<span class="oven-marker-pick">' + esc(label) + '</span>' +
          '<span class="oven-marker-line"></span>'
        : '<span class="oven-marker-label">Then you choose</span>' +
          '<span class="oven-marker-pick">' + esc(label) + '</span>' +
          '<span class="oven-marker-line"></span>';
      target.parentNode.insertBefore(div, target);

      // The territory above the first horizon is a named zone, not a texture.
      // These are the players who go before you choose — saying how many is the
      // whole point of computing the marker in the first place.
      if (m === 0) {
        for (var a = 0; a < ahead && a < avail.length; a++) avail[a].classList.add('atrisk');
        if (ahead > 0) {
          var zone = document.createElement('div');
          zone.className = 'oven-zone';
          zone.innerHTML = '<span>The chalk</span>' +
            '<span class="oven-zone-line"></span>' +
            '<span>' + ahead + ' gone before you’re up</span>';
          avail[0].parentNode.insertBefore(zone, avail[0]);
        }
      }
    }
  }

  function updateTierCounts() {
    if (!state.listEl) return;
    var seps = state.listEl.querySelectorAll('.oven-tiersep');
    for (var i = 0; i < seps.length; i++) {
      var tier = seps[i].getAttribute('data-tier');
      var left = 0;
      state.rows.forEach(function (r) {
        if (String(r.tier) !== tier) return;
        if (!state.drafted[r.key]) left++;
      });
      // Only the cliff is worth saying — a running count next to every tier
      // header is arithmetic you never act on.
      var cliff = left <= 2 && left > 0;
      seps[i].querySelector('.tier-count').innerHTML =
        cliff ? '<span class="cliff">· tier cliff</span>' : '';
    }
  }

  /* ---------- re-ranking (drag a row to move him) ----------
   *
   * The board has exactly one order and it is mine, so the only thing a drag on
   * a row can mean is "he belongs here instead". Dropping renumbers every
   * `myRank` from the top, recomputes heat against consensus, re-renders, and
   * hands the new rows to the host to persist — into the same per-league blob a
   * CSV import writes, so exporting after a drag session gives you the board
   * you are actually looking at.
   *
   * HTML5 DnD never fires on iOS Safari, which is the same bargain the rest of
   * the page makes: dragging is the fast path on a laptop, and the CSV is how
   * you author a board anywhere else. Nothing here is the only route to
   * anything — the ranks still come from the sheet.
   */

  var drag = { key: null, overEl: null, after: false };

  function rowUnder(e) {
    var el = e.target && e.target.closest && e.target.closest('.oven-row[data-key]');
    return el && state.listEl && state.listEl.contains(el) ? el : null;
  }

  function clearHint() {
    if (drag.overEl) drag.overEl.classList.remove('drop-before', 'drop-after');
    drag.overEl = null;
    drag.after = false;
  }

  function endDrag() {
    clearHint();
    if (state.listEl) {
      var src = state.listEl.querySelector('.oven-row.is-dragging');
      if (src) src.classList.remove('is-dragging');
    }
    document.body.classList.remove('oven-reordering');
    drag.key = null;
  }

  /* One order means one numbering. Rows that arrived without a MyRank get a
   * number here too — once you have hand-ordered the board there is no longer an
   * "unranked, sorts to the bottom" tail to preserve. */
  function renumber() {
    state.rows.forEach(function (r, i) { r.myRank = i + 1; r.boardIndex = i; });
  }

  /* Move by KEY, not by on-screen index: a filter can be active, so the row
   * you dropped onto is a position in `state.rows` that the visible list only
   * samples. Landing between two visible rows leaves everything hidden between
   * them exactly where it was. */
  function moveRow(key, refKey, after) {
    var i, from = -1, to = -1;
    for (i = 0; i < state.rows.length; i++) if (state.rows[i].key === key) { from = i; break; }
    if (from === -1 || key === refKey) return false;

    var row = state.rows.splice(from, 1)[0];
    for (i = 0; i < state.rows.length; i++) if (state.rows[i].key === refKey) { to = i; break; }
    if (to === -1) { state.rows.splice(from, 0, row); return false; }

    var at = after ? to + 1 : to;
    state.rows.splice(at, 0, row);

    /* Tier belongs to the band, not to the player. Carrying his old tier into
     * his new home would emit a stray "Tier 6" header in the middle of tier 2 —
     * tier headers fire on first appearance — and would claim something the move
     * just contradicted. So he adopts the tier of whoever he now sits behind
     * (or, dropped at the very top, of whoever he now sits in front of). */
    var neighbor = at > 0 ? state.rows[at - 1] : state.rows[at + 1];
    if (neighbor) row.tier = neighbor.tier;

    renumber();
    return true;
  }

  /* The board blob's rows, in the shape a CSV import writes — same object
   * either way, so `Export My Rankings` and the next page load both see the
   * order you dragged. */
  function exportRows() {
    return state.rows.map(function (r) {
      return {
        name: r.name,
        pos: r.pos || '',
        team: r.team || '',
        tier: r.tier == null ? null : r.tier,
        myRank: r.myRank,
        grade: r.grade || null,
        note: r.note || '',
        extra: r.extra || {},
        player_id: r.player_id || null,
      };
    });
  }

  function wireReorder(listEl) {
    listEl.addEventListener('dragstart', function (e) {
      var row = rowUnder(e);
      if (!row) return;
      drag.key = row.getAttribute('data-key');
      try {
        // Firefox refuses to start a drag with an empty dataTransfer.
        e.dataTransfer.setData('text/plain', drag.key);
      } catch (err) { /* older Edge rejects setData mid-dragstart */ }
      e.dataTransfer.effectAllowed = 'move';
      row.classList.add('is-dragging');
      document.body.classList.add('oven-reordering');
    });

    listEl.addEventListener('dragover', function (e) {
      if (!drag.key) return;
      // Tier bands and horizon markers are not seams — drop them and nothing
      // happens, so drop the hint too rather than promising a landing spot.
      var row = rowUnder(e);
      if (!row) { clearHint(); return; }
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';

      // Above the midpoint means "before him", below means "after him" — the
      // seam under the cursor, not the row, is what you are aiming at.
      var box = row.getBoundingClientRect();
      var after = e.clientY > box.top + box.height / 2;
      if (row === drag.overEl && after === drag.after) return;
      clearHint();
      drag.overEl = row;
      drag.after = after;
      row.classList.add(after ? 'drop-after' : 'drop-before');
    });

    listEl.addEventListener('drop', function (e) {
      if (!drag.key) return;
      e.preventDefault();
      var key = drag.key;
      var refKey = drag.overEl ? drag.overEl.getAttribute('data-key') : null;
      var after = drag.after;
      endDrag();
      if (!refKey || !moveRow(key, refKey, after)) return;

      computeHeat(state.rows);
      render();
      if (state.onReorder) state.onReorder(exportRows());
    });

    // Fires on the source row wherever the drag ended, including a cancel.
    listEl.addEventListener('dragend', endDrag);
  }

  /* Opt-in, because the host owns persistence: a board nobody can save is a
   * board that silently forgets the order on reload. `onReorder` receives the
   * full row list, already renumbered. */
  function enableReorder(opts) {
    state.onReorder = (opts && opts.onReorder) || null;
    if (state.reorderWired || !state.listEl) return;
    wireReorder(state.listEl);
    state.reorderWired = true;
  }

  /* Index drafted picks by board key. Sleeper pick metadata carries the name,
   * so this works without the 5 MB player database. player_id is preferred
   * when the CSV was resolved. */
  function indexPicks(picks, rows) {
    var byId = {}, byKey = {};
    rows.forEach(function (r) {
      if (r.player_id) byId[String(r.player_id)] = r;
      byKey[r.key] = r;
    });

    var drafted = {};
    (picks || []).forEach(function (p) {
      var row = p.player_id != null ? byId[String(p.player_id)] : null;
      if (!row) {
        var m = p.metadata || {};
        var nm = ((m.first_name || '') + ' ' + (m.last_name || '')).trim();
        row = byKey[playerKey(nm, m.position, m.team)];
      }
      if (row) drafted[row.key] = p;
    });
    return drafted;
  }

  global.OvenBoard = {
    esc: esc,
    gradeChip: gradeChip,
    normName: normName,
    normPos: normPos,
    playerKey: playerKey,
    buildBoard: buildBoard,
    computeHeat: computeHeat,
    indexPicks: indexPicks,
    render: render,
    applyDraftState: applyDraftState,
    enableReorder: enableReorder,
    exportRows: exportRows,
    state: state,
  };
})(window);
