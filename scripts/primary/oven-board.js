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

  /* The board once had five grades (love/like/fade/avoid); it has three. Every
   * row that reaches the board passes through here, which is the whole migration
   * — a saved board is normalized as it is read, not rewritten in storage, so a
   * board synced from a device still running the old code lands correctly rather
   * than fighting over the same key. The next save persists the merged value.
   *
   * Unknown strings become null. A grade is a class name on the row and a lookup
   * into GRADE_MARK; letting a stray one through paints an unstyled row and a
   * blank control. */
  function normGrade(grade) {
    if (!grade) return null;
    var g = String(grade).toLowerCase();
    // GRADE_LABEL (built from GRADE_MENU, further down) is the list of grades
    // that still exist — the menu is what you can set, so it is also what a row
    // is allowed to hold. Declared later in the file, populated at load; this
    // only ever runs from buildBoard(), long after.
    if (GRADE_LABEL[g]) return g;
    return C.GRADE_LEGACY[g] || null;
  }

  /* ---------- positions this league actually starts ----------
   *
   * The board is a list of draft decisions, and a league that rosters no K and
   * no DEF slot can never make one about a kicker. Both sources hand us all six
   * positions regardless — FantasyPros ships 32 defenses and 32 kickers, and a
   * rankings CSV is usually a general-purpose sheet reused across leagues — so
   * the league itself has to be the filter. `roster_positions` is the only thing
   * that knows, which is why the hosts set this before building.
   *
   * Null (the default, and what an unloaded league gives) means no opinion: show
   * everything. See OVEN.startablePositions for why that is not an empty list. */
  function setPositions(rosterPositions) {
    var list = C.startablePositions(rosterPositions);
    if (!list) { state.positions = null; return null; }
    var set = {};
    list.forEach(function (p) { set[p] = true; });
    state.positions = set;
    return list;
  }

  /* A row belongs on the board unless the league has said otherwise. A row with
   * no position at all is kept: "unknown" is not the same claim as "kicker", and
   * dropping a player because his sheet had a blank cell is the one failure mode
   * that would be invisible. */
  function startable(pos) {
    if (!state.positions) return true;
    var p = normPos(pos);
    return !p || !!state.positions[p];
  }

  /* Merge CSV rows with the FantasyPros snapshot.
   * FP wins for ECR/tier metadata; the CSV owns rank, tier override, and grade.
   * With no CSV at all the board seeds entirely from FP, so the page is useful
   * before anything has been uploaded.
   *
   * Rows at a position the league doesn't start are split off here, at the one
   * gate everything downstream reads: the rendered list, the undrafted pool the
   * horizons count against, and the rows the Targets drawer projects from all
   * come off `state.rows`, so filtering once here is filtering everywhere.
   *
   * They are set aside rather than discarded (see exportRows) — the stored board
   * is the user's CSV, and re-grading one player is not consent to delete the
   * kickers out of a sheet they may also use in a league that starts them. */
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
          grade: normGrade(r.grade),
          note: r.note,
          extra: r.extra || {},
          // No fpPosRank: the badge shows my positional rank, and FP's would be
          // a second, contradictory "RB7" sitting on the row waiting to be read.
          // ECR (fpRank) stays — the Δ column and the wash are about the market
          // by design.
          fpRank: fp ? fp.rank : null,
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
          fpRank: p.rank,
          onMyBoard: false,
        };
      });
    }

    state.offBoard = rows.filter(function (r) { return !startable(r.pos); });
    rows = rows.filter(function (r) { return startable(r.pos); });

    rows.sort(function (a, b) {
      var ar = a.myRank == null ? Infinity : a.myRank;
      var br = b.myRank == null ? Infinity : b.myRank;
      return ar - br;
    });
    rows.forEach(function (r, i) { r.boardIndex = i; });
    computePosRanks(rows);
    return rows;
  }

  /* "RB7" means the seventh running back on MY board, not FantasyPros' seventh.
   * FP's pos_rank seeds the initial order and then stops being true the moment
   * you drag anything — a row promoted forty spots that still wears RB19 is
   * stating the market's opinion in the one column you'd read as your own.
   *
   * Derived, never stored: it falls straight out of the order rows are already
   * in, so anything that changes the order recomputes it (buildBoard on
   * boot/import, renumber() on every drop) and exportRows() doesn't persist it.
   *
   * Counted over ALL rows, drafted included. Positional rank is a statement
   * about the player, not about what's left — decrementing "RB7" to "RB5"
   * because two backs came off the board would make the badge move for reasons
   * that have nothing to do with him. */
  function computePosRanks(rows) {
    var n = {};
    rows.forEach(function (r) {
      var pos = r.pos || '';
      if (!pos) { r.myPosRank = null; return; }
      n[pos] = (n[pos] || 0) + 1;
      r.myPosRank = pos + n[pos];
    });
    return rows;
  }

  /* THERE IS NO HEAT MODEL ANY MORE. A `computeHeat()` used to run here and turn
   * two things — an explicit grade, or `fpRank - myRank` — into one blended
   * number per row, which then painted a saturated left rail and a smoothed
   * background wash. Both are gone, and the model went with them rather than
   * being left computing values nothing reads.
   *
   * What replaced it says the same things, separately, because they were never
   * one fact: the **Δ column** states rank-vs-consensus as a number (rowHTML),
   * and the **grade control** states what you think of him (gradeButton). The
   * blend was the problem — a Like on a player the market also likes and a
   * genuine 24-spot disagreement produced identical color, and the board could
   * not tell you which one you were looking at.
   *
   * `OVEN.GRADE_HEAT` survives, but only as the Targets projection's scoring
   * weight (adjRank in oven-targets.js). It is no longer a display scale. */

  /* ---------- rendering ---------- */

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
    // The grade control. Same opt-in shape as reordering — the host owns
    // persistence — plus the key of the row whose menu is open, which is how a
    // poll knows to re-anchor a menu the markers just shifted out from under.
    onGrade: null, gradeWired: false, gradeOpenKey: null,
    // Last season's top-12/24/36 counts, keyed the same way rows are. Held on
    // state rather than threaded through buildBoard() because the board is
    // rebuilt on CSV import and on every reorder — a parameter would have to be
    // re-passed at each of those call sites, and the one that got missed would
    // blank the column with no error.
    weekly: null,         // key -> {t12, t24, t36, games, pos}
    // The league's startable positions as a lookup, and the rows the last
    // buildBoard() set aside because they aren't at one. Null positions means
    // the league hasn't said (or starts nothing), and nothing is filtered.
    positions: null,      // {QB: true, ...} | null
    offBoard: [],         // rows held back only so exportRows can hand them back
  };

  /* Set once at boot, after the league's scoring settings are known. */
  function setWeekly(counts) {
    state.weekly = counts || null;
  }

  function visibleRows() {
    var f = state.filters;
    var out = state.rows.filter(function (r) {
      if (f.pos && r.pos !== f.pos) return false;
      if (f.hideDrafted && state.drafted[r.key]) return false;
      if (f.hideFade && r.grade === 'fade') return false;
      return true;
    });
    // No re-sort: `state.rows` is already in personal-rank order from
    // buildBoard(), and filtering only removes rows from it.
    return out;
  }

  /* ---------- grade badge (read-only surfaces: the Targets drawer) ---------- */

  /* Both grades wear an emoji: a heart for `like`, a red X for `fade`. An emoji
   * is an image to a screen reader with no accessible name of its own, so the
   * word it replaced moves to aria-label — and to title, so a hover still says
   * which one it is.
   *
   * A faded row also recedes (see .oven-row.faded), which is the older half of
   * the same statement and stays: the badge names the grade, the opacity is what
   * lets you skip the row without reading it at all.
   *
   * THE BIG BOARD NO LONGER CALLS THIS. Its rows carry an editable grade control
   * (see the next section), and that control already shows the current grade —
   * a badge beside it would state the same fact twice on the one screen where
   * vertical space is the whole game. The Targets drawer has no such control: it
   * is a read-only view of the board in three places (targets, projections,
   * team), and there this badge is the only thing carrying the grade at all. So
   * it stays, and stays exported, for those three.
   *
   * That is the line, and the two surfaces differing is not an accident:
   * anything that EDITS a grade uses the control, anything that only DISPLAYS a
   * row uses this. */
  function gradeChip(r) {
    var icon = r && r.grade && C.GRADE_ICON[r.grade];
    if (!icon) return '';
    return '<span class="oven-grade ' + esc(r.grade) + '" role="img" aria-label="' +
      esc(r.grade) + '" title="' + esc(r.grade) + '">' + icon + '</span>';
  }

  /* ---------- grade control (the board row) ----------
   *
   * Setting a grade used to mean leaving the board, editing the CSV and
   * re-importing it — the one opinion the board holds about a player, and the
   * only one you couldn't change while looking at him. Now it's a button in the
   * row, next to the pin, showing the current grade and opening a three-item
   * menu: like, none, fade.
   *
   * A menu, not three inline buttons: 860 rows x 3 controls is a board you can
   * no longer scan, which is the board's only job. It stays a menu rather than a
   * click-to-cycle button now that there are only three states, because cycling
   * makes "fade him" a two-click gesture whose intermediate state is a wrong
   * grade briefly written to a synced board.
   */

  var GRADE_LABEL = {};
  C.GRADE_MENU.forEach(function (g) { if (g.value) GRADE_LABEL[g.value] = g.label; });

  /* The menu item reads "No grade" — it's a thing you choose. The button reads
   * "none", because it's the tail of a sentence: "Grade for Bijan Robinson:
   * none". Same state, two readings, and neither one is right in both places. */
  function gradeLabel(grade) { return grade ? (GRADE_LABEL[grade] || grade) : 'none'; }

  /* The collapsed control. The glyph is aria-hidden and the accessible name is
   * the label alone — same rule the heart badge follows, for the same reason: an
   * emoji is an image with no name of its own. The player's name is in there
   * because 860 buttons all called "Grade" is a screen reader reading a wall. */
  function gradeButton(r) {
    var label = gradeLabel(r.grade);
    return '<button class="oven-grade-btn' + (r.grade ? ' ' + esc(r.grade) : '') +
      '" type="button" aria-haspopup="menu" aria-expanded="false" aria-controls="oven-grade-menu"' +
      ' aria-label="Grade for ' + esc(r.name) + ': ' + esc(label) + '"' +
      ' title="Grade: ' + esc(label) + '">' +
      '<span aria-hidden="true">' + (C.GRADE_MARK[r.grade || 'none'] || C.GRADE_MARK.none) +
      '</span></button>';
  }

  var menuEl = null;

  /* ONE menu for the whole board, built on first use and moved from row to row.
   * Per-row menus would be 860 x 5 more nodes to rebuild on every render and
   * every filter click, on the page whose whole render strategy exists to avoid
   * exactly that.
   *
   * It lives on document.body, not in the row. Three independent reasons, any
   * one of them fatal: .oven-row sets content-visibility: auto, which applies
   * paint containment and would CLIP the menu to the 32px row; .faded and .gone
   * set opacity < 1, which would dim the menu and trap its z-index in the row's
   * stacking context; and .oven-list is no better, because render() replaces its
   * innerHTML wholesale. */
  function ensureGradeMenu() {
    if (menuEl) return menuEl;
    menuEl = document.createElement('div');
    menuEl.className = 'oven-grade-menu';
    menuEl.id = 'oven-grade-menu';
    menuEl.setAttribute('role', 'menu');
    menuEl.setAttribute('aria-label', 'Set grade');
    menuEl.hidden = true;
    menuEl.innerHTML = C.GRADE_MENU.map(function (g) {
      return '<button type="button" role="menuitemradio" data-grade="' +
        esc(g.value == null ? '' : g.value) + '" aria-checked="false" tabindex="-1">' +
        '<span class="gm-mark" aria-hidden="true">' +
        (C.GRADE_MARK[g.value || 'none'] || '') + '</span>' + esc(g.label) + '</button>';
    }).join('');
    document.body.appendChild(menuEl);
    return menuEl;
  }

  /* Absolute in DOCUMENT coordinates, not fixed in viewport ones: the page is
   * what scrolls here (render() restores global.scrollY), so anchoring in
   * document space means scrolling needs no listener at all — the menu simply
   * travels with the row it belongs to. Right-aligned to the button, which sits
   * at the row's right edge, so it can't run off the side. */
  function positionGradeMenu() {
    if (!menuEl || menuEl.hidden || !state.gradeOpenKey) return;
    var row = state.rowEls && state.rowEls.get(state.gradeOpenKey);
    var btn = row && row.querySelector('.oven-grade-btn');
    if (!btn) { closeGradeMenu(false); return; }

    var b = btn.getBoundingClientRect();
    var h = menuEl.offsetHeight, w = menuEl.offsetWidth;
    var below = b.bottom + 4 + h <= global.innerHeight;
    menuEl.style.top = ((below ? b.bottom + 4 : b.top - h - 4) + global.scrollY) + 'px';
    menuEl.style.left = (Math.max(4, b.right - w) + global.scrollX) + 'px';
  }

  function openGradeMenu(btn, key) {
    var row = rowByKey(key);
    if (!row) return;
    var menu = ensureGradeMenu();
    var cur = row.grade || '';
    var items = menu.querySelectorAll('[data-grade]');
    var focusEl = null;
    for (var i = 0; i < items.length; i++) {
      var on = items[i].getAttribute('data-grade') === cur;
      items[i].setAttribute('aria-checked', on ? 'true' : 'false');
      items[i].tabIndex = on ? 0 : -1;
      if (on) focusEl = items[i];
    }
    state.gradeOpenKey = key;
    btn.setAttribute('aria-expanded', 'true');
    menu.hidden = false;
    positionGradeMenu();
    // preventScroll: positionGradeMenu() has already placed the menu inside the
    // viewport, so there is nothing to reveal, and the menu is absolute in
    // DOCUMENT coordinates — a browser scroll to "reach" it would slide the menu
    // along with the page and leave the button it belongs to behind.
    (focusEl || items[0]).focus({ preventScroll: true });
  }

  function closeGradeMenu(refocus) {
    if (!menuEl || menuEl.hidden) { state.gradeOpenKey = null; return; }
    var key = state.gradeOpenKey;
    menuEl.hidden = true;
    state.gradeOpenKey = null;
    var row = key && state.rowEls && state.rowEls.get(key);
    var btn = row && row.querySelector('.oven-grade-btn');
    if (!btn) return;
    btn.setAttribute('aria-expanded', 'false');
    if (refocus) btn.focus();
  }

  function rowByKey(key) {
    for (var i = 0; i < state.rows.length; i++) {
      if (state.rows[i].key === key) return state.rows[i];
    }
    return null;
  }

  /* The row-local half of a grade change: the exact inverse of what gradeButton()
   * and rowHTML() write for the same state. Anything either of them starts saying
   * about a grade has to be said here too, or a patched row will disagree with
   * the same row after the next full render. Returns the button, which setGrade
   * needs to put focus back on. */
  function paintGrade(key, r) {
    var el = state.rowEls && state.rowEls.get(key);
    if (!el) return null;
    el.classList.toggle('faded', r.grade === 'fade');
    var btn = el.querySelector('.oven-grade-btn');
    if (!btn) return null;
    var label = gradeLabel(r.grade);
    btn.className = 'oven-grade-btn' + (r.grade ? ' ' + r.grade : '');
    btn.setAttribute('aria-label', 'Grade for ' + r.name + ': ' + label);
    btn.title = 'Grade: ' + label;
    var mark = btn.firstElementChild;
    if (mark) mark.textContent = C.GRADE_MARK[r.grade || 'none'] || C.GRADE_MARK.none;
    return btn;
  }

  /* Two paths, chosen on one question: does this grade change WHICH rows are on
   * the board? Almost never. A grade doesn't reorder (state.rows is already in
   * personal-rank order and filtering only removes from it), doesn't move the Δ
   * column (that reads the two ranks directly), doesn't touch tier counts (those
   * read `drafted`), and says nothing about any other row — the heat wash that
   * once made a grade re-tint its neighbours is gone.
   *
   * The one exception is Hide: Fade, where grading someone `fade` is
   * precisely the instruction to take him off the board, and can orphan the tier
   * header he was the only visible member of. That case still rebuilds.
   *
   * Everything else patches the one row in place, because the rebuild was a
   * visible jump: innerHTML drops all ~860 rows at once, every off-screen row
   * falls back to its contain-intrinsic-size estimate, and for that beat the
   * document is shorter than the scrollY we are about to restore — so scrollTo()
   * clamps and the board lands somewhere other than where you were looking.
   * Grading a run of players is the most repetitive thing you do live, which
   * makes it the last place that can afford to move the page under you. */
  function setGrade(key, grade) {
    var row = rowByKey(key);
    var next = grade || null;
    if (!row || (row.grade || null) === next) return false;
    var wasHidden = !!(state.filters.hideFade && row.grade === 'fade');
    var nowHidden = !!(state.filters.hideFade && next === 'fade');
    row.grade = next;

    var btn;
    if (wasHidden !== nowHidden) {
      render();
      // render() rebuilt the button we were standing on. Below, focus goes back
      // to it — unless the row just filtered itself away, in which case there is
      // no button and body is the honest place for focus. Landing a keyboard
      // user on an unrelated player's grade control would be worse than a reset.
      var el = state.rowEls.get(key);
      btn = el && el.querySelector('.oven-grade-btn');
    } else {
      // Nothing here closes the menu the way render() does, and a menu left open
      // over a row whose grade just moved is showing a stale aria-checked. Harmless
      // when it is already hidden, which is the case on the click path.
      closeGradeMenu(false);
      btn = paintGrade(key, row);
    }

    if (state.onGrade) state.onGrade(exportRows());
    // Grade weights the drawer's round projection (see adjRank in oven-targets),
    // so a graded player has to move in an open Projections view now, not at
    // whatever poll happens to come next.
    if (global.OvenTargets) global.OvenTargets.refresh();

    // preventScroll: the button is already where it belongs on both paths — the
    // patch never moved it and render() restored scrollY — so any scrolling the
    // browser does to "reveal" it is the jump we just spent this function avoiding.
    if (btn) btn.focus({ preventScroll: true });
    return true;
  }

  function wireGrading(listEl) {
    /* One delegated listener for all three concerns, in order: open, choose,
     * dismiss. Splitting them — "open" on the list, "close on outside click" on
     * the document — would open the menu and then immediately close it again as
     * the same click bubbled up.
     *
     * OvenTargets' pin handler is on this same node and cannot interfere: it
     * early-returns when the click isn't on a .oven-pin, and its
     * stopPropagation() only holds back ANCESTORS, never a sibling listener
     * registered on document itself. */
    document.addEventListener('click', function (e) {
      var t = e.target;
      if (!t || !t.closest) return;

      var btn = t.closest('.oven-grade-btn');
      if (btn && listEl.contains(btn)) {
        var row = btn.closest('.oven-row[data-key]');
        if (!row) return;
        e.preventDefault();
        e.stopPropagation();
        var key = row.getAttribute('data-key');
        // Clicking the open row's own control closes it, so the button is a
        // toggle rather than a thing you can only escape from.
        if (state.gradeOpenKey === key) { closeGradeMenu(true); return; }
        closeGradeMenu(false);
        openGradeMenu(btn, key);
        return;
      }

      var item = t.closest('#oven-grade-menu [data-grade]');
      if (item) {
        e.preventDefault();
        e.stopPropagation();
        var openKey = state.gradeOpenKey;
        closeGradeMenu(false);
        // Re-picking the grade he already has is a no-op, and setGrade says so
        // by returning false — but focus still has to come back off the menu
        // element we just hid.
        if (openKey && !setGrade(openKey, item.getAttribute('data-grade'))) {
          var el = state.rowEls && state.rowEls.get(openKey);
          var b = el && el.querySelector('.oven-grade-btn');
          if (b) b.focus({ preventScroll: true });
        }
        return;
      }

      if (state.gradeOpenKey) closeGradeMenu(false);
    });

    /* Escape IS order-sensitive, unlike the click path above: OvenTargets closes
     * the drawer on Escape from this same node, and stopPropagation can't hold
     * back a sibling listener. Hence stopImmediatePropagation, plus the host
     * calling enableGrading() before OvenTargets.mount() so this one runs first.
     * One Escape closes the menu; a second closes the drawer. */
    document.addEventListener('keydown', function (e) {
      if (!state.gradeOpenKey) return;

      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopImmediatePropagation();
        closeGradeMenu(true);
        return;
      }
      // Not prevented: focus moves to the button here, and the browser's own Tab
      // then carries on from there to the pin — which is where you were headed.
      if (e.key === 'Tab') { closeGradeMenu(true); return; }

      if (!menuEl || !menuEl.contains(e.target)) return;
      var nav = { ArrowDown: 1, ArrowUp: -1, Home: 0, End: 0 };
      if (!(e.key in nav)) return;
      e.preventDefault();

      var items = menuEl.querySelectorAll('[data-grade]');
      var cur = -1, i;
      for (i = 0; i < items.length; i++) if (items[i] === e.target) cur = i;
      var next = e.key === 'Home' ? 0
        : e.key === 'End' ? items.length - 1
        : (cur + nav[e.key] + items.length) % items.length;
      for (i = 0; i < items.length; i++) items[i].tabIndex = i === next ? 0 : -1;
      items[next].focus();
    });
  }

  /* Opt-in for the same reason enableReorder is: the host owns persistence, and
   * a board that silently forgets a grade on reload is worse than one that can't
   * be graded at all. Kept as its own switch rather than folded into
   * enableReorder because the two are genuinely independent — grading works on
   * iOS Safari, where HTML5 drag events never fire. `onGrade` receives the same
   * full row list `onReorder` does, so a host can hand both the same writer. */
  function enableGrading(opts) {
    state.onGrade = (opts && opts.onGrade) || null;
    if (state.gradeWired || !state.listEl) return;
    wireGrading(state.listEl);
    state.gradeWired = true;
  }

  /* Last season's finishes: top 12 / 24 / 36 at his position, under this
   * league's scoring. Emitted on every row and hidden by CSS unless the list
   * carries .show-weekly — toggling a class beats re-rendering 860 rows, which
   * would reset the scroll position mid-board.
   *
   * It sits UNDER the name rather than in a right-hand column. Three numbers in
   * their own column were reading as a fourth ranking to scan down; on their own
   * line they read as an annotation on the player they describe, and each one
   * can carry its own `T12` label instead of relying on column position to say
   * which cutoff it is.
   *
   * A dash, never a zero, when he has no data: a 2026 rookie and a healthy
   * veteran who never once cracked the top 36 are opposite facts, and "0" would
   * state the second about the first. */
  function weeklyTiers(pos) {
    return C.WEEKLY_SINGLE_TIER_POS.indexOf(pos) === -1
      ? C.WEEKLY_TIERS
      : C.WEEKLY_TIERS.slice(0, 1);
  }

  function weeklyCell(r) {
    var w = state.weekly && state.weekly[r.key];
    if (!w) return '<div class="oven-weekly is-empty">—</div>';

    var tiers = weeklyTiers(r.pos);

    // Heading over value, one pair per column — a small table under the name.
    // Emitted heading-then-value per tier rather than all headings then all
    // values: the grid flows by column, so the pairing is structural and the
    // markup survives a position showing one cutoff instead of three without
    // needing a column count passed to CSS.
    //
    // No cutoff is emphasized. Which one is "startable" varies by position and
    // by league, and picking one of the three to bold made the other two read
    // as background — but the whole point of showing three is that the shape
    // across them is the signal, and a shape can't be read if one column shouts.
    var cells = [], label = [];
    for (var i = 0; i < tiers.length; i++) {
      var t = tiers[i];
      cells.push('<i class="ow-t">T' + t + '</i><span class="ow-n">' + w['t' + t] + '</span>');
      label.push('top ' + t + ': ' + w['t' + t]);
    }
    var title = C.WEEKLY_SEASON + ' weeks 1–17 · ' + label.join(' · ') +
      ' — in ' + w.games + ' game' + (w.games === 1 ? '' : 's') + ', your league\'s scoring';
    return '<div class="oven-weekly" title="' + esc(title) + '">' + cells.join('') + '</div>';
  }

  /* Every row is the same flat markup — no inline styles at all now that the heat
   * wash is gone, which is why applyDraftState() can patch a row by touching
   * classes and never has to reason about what color it was. */
  function rowHTML(r) {
    // Rank vs consensus, printed — the whole of the board's market signal, in one
    // column. Straight from the two ranks: a grade is what *I* think of him and
    // has no business moving a number that reports what the market thinks.
    var d = r.fpRank != null && r.myRank != null ? r.fpRank - r.myRank : null;
    var dCls = d == null ? 'zero' : (d > 0 ? 'pos' : (d < 0 ? 'neg' : 'zero'));
    var dTxt = d == null ? '—' : (d > 0 ? '+' + d : String(d));
    // The position column carries the positional rank — same badge, same color,
    // one more fact. "RB7" states the position too, so nothing is lost by
    // spending the cell on it, and the row keeps a single line. It's MY pos rank
    // (see computePosRanks), so it moves with every drag.
    var posLabel = r.myPosRank || r.pos || '—';

    // No per-row tier chip: the full-width tier band already states it, and
    // repeating it 250 times competes with the Δ column for the same glance.
    //
    // Three affordances on the row, and they do not overlap: the row is
    // draggable to RE-RANK him (enableReorder), the grade control records what I
    // think of him (enableGrading), and the pin queues him as a target. The
    // first two are the board's own — grade is a field on the row — and the pin
    // is OvenTargets' handler, inert on a page that doesn't mount the drawer.
    //
    // The grade is stated once, by its control, and no longer by a badge on the
    // name line: the control is right there showing it. See gradeChip() above
    // for why the Targets drawer still wears the badge.
    return '<div class="oven-row' + (r.grade === 'fade' ? ' faded' : '') +
      '" draggable="true" data-key="' + esc(r.key) + '">' +
      '<div class="oven-rk">' + (r.myRank == null ? '' : r.myRank) + '</div>' +
      '<span class="player-pos pos-' + esc(r.pos || 'OTHER') + '">' + esc(posLabel) + '</span>' +
      '<div class="oven-name">' +
        // The name is its own element so the crossed-off treatment lands on it
        // alone — text-decoration propagates to descendants and a child can't
        // opt out, so the team and note have to sit outside the struck span
        // rather than be un-struck inside it.
        '<div class="oven-name-main"><span class="oven-name-text">' + esc(r.name) + '</span>' +
          (r.team ? '<span class="oven-name-team">' + esc(r.team) + '</span>' : '') +
          (r.note ? ' <span class="oven-name-note">· ' + esc(r.note) + '</span>' : '') + '</div>' +
        // Second line of the name column, not a column of its own — so it grows
        // the row downward when it's on and costs nothing when it's off.
        weeklyCell(r) +
      '</div>' +
      '<div class="oven-delta ' + dCls + '" title="' +
        (d == null ? 'no consensus rank' : 'ECR ' + r.fpRank + ' · you have him ' +
          (d === 0 ? 'there too' : Math.abs(d) + ' spot' + (Math.abs(d) === 1 ? '' : 's') +
            (d > 0 ? ' higher' : ' lower'))) + '">' + dTxt + '</div>' +
      '<div class="oven-taken" hidden></div>' +
      gradeButton(r) +
      '<button class="oven-pin" type="button" aria-pressed="false" aria-label="Add to targets">+</button>' +
    '</div>';
  }

  function render(listEl) {
    // A rebuild destroys the row the grade menu is anchored to. Closing here
    // covers every route into a render at once — the filter chips, a CSV import,
    // the drop handler, and setGrade itself.
    closeGradeMenu(false);
    state.listEl = listEl || state.listEl;
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
      html.push(rowHTML(r));
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
    // A poll is otherwise surgical, but placeMarkers() inserts and removes
    // marker rows, which shifts every row below the horizon — and with it the
    // button an open menu is pinned to. Re-anchor rather than leave it floating
    // over the wrong player.
    if (state.gradeOpenKey) positionGradeMenu();
  }

  /* ---------- rescued rows (a pick is never empty) ----------
   *
   * The horizons cut the board into windows: everything between my pick's marker
   * and the next one is what that pick can realistically reach. A Hide toggle can
   * empty a window outright — a run of players you all faded, say — and then two
   * markers stack with nothing between them, which reads as "you have no pick
   * there" when what is true is "everything there is hidden". That is the one
   * case where a filter stops subtracting rows and starts deleting a pick.
   *
   * So a window with no visible row gets its best available back, hidden or not,
   * marked as the exception it is. This does NOT move anybody: the row is
   * reinserted at its real depth in the pool, so every survivor keeps the
   * position it had — the same promise placeMarkers() makes about the horizons,
   * for the same reason. One row per empty window, never more; the toggle still
   * means what it says everywhere it isn't erasing a pick.
   *
   * The POSITION filter is not overridden, and that asymmetry is deliberate.
   * `Hide: Fade` says "take these off my board", so showing one back is a
   * correction. Filtering to RB says "this screen is running backs" — answering
   * "no RB in that window" with a receiver would be answering a question nobody
   * asked. An empty window under a position filter is a real finding, so it is
   * left to stack. `Hide: Drafted` never empties a window at all: drafted players
   * are out of the pool on both paths. */

  function rescuable(r) {
    return !state.filters.pos || r.pos === state.filters.pos;
  }

  function makeRowEl(r) {
    var wrap = document.createElement('div');
    wrap.innerHTML = rowHTML(r);
    var el = wrap.firstElementChild;
    el.classList.add('rescued');
    // Says why a row you filtered away is on screen, in the row itself — a
    // treatment alone would just look like the toggle had failed. It sits before
    // the grade control because the fastest fix is usually to re-grade him.
    var tag = document.createElement('span');
    tag.className = 'oven-rescued';
    tag.textContent = 'best available';
    tag.title = 'Hidden by your filters, shown because nothing else is left at this pick';
    el.insertBefore(tag, el.querySelector('.oven-grade-btn'));
    return el;
  }

  /* Rebuilt from scratch on every poll, exactly like the markers they answer to —
   * one pick landing changes every depth below it, so which windows are empty is
   * never stable enough to patch. Dropping them here also keeps `rowEls` honest:
   * a rescued row lives in that map while it is on screen (so a grade patch, an
   * open menu and OvenTargets.markBoard all find it) and leaves with the element. */
  function dropRescued() {
    var old = state.listEl.querySelectorAll('.oven-row.rescued');
    for (var i = 0; i < old.length; i++) {
      var key = old[i].getAttribute('data-key');
      if (state.rowEls && state.rowEls.get(key) === old[i]) state.rowEls.delete(key);
      old[i].remove();
    }
  }

  /* Mutates `pool` in place so the marker pass that follows anchors to the row it
   * just put back rather than skipping past it to the next visible name. */
  function rescueEmptyWindows(pool, poolRows, depths) {
    if (!state.rowEls) return;
    for (var m = 0; m < depths.length; m++) {
      var start = depths[m];
      if (start >= pool.length) break;
      var end = m + 1 < depths.length ? Math.min(depths[m + 1], pool.length) : pool.length;

      var p, occupied = false;
      for (p = start; p < end; p++) if (pool[p]) { occupied = true; break; }
      if (occupied) continue;

      var idx = -1;
      for (p = start; p < end; p++) if (rescuable(poolRows[p])) { idx = p; break; }
      if (idx === -1) continue;   // a position filter emptied it; that answer stands

      // Anchor to the next row still on screen, so he lands where he belongs
      // rather than at the end of whatever window he came from. Nothing after him
      // means the window runs off the bottom of the board — append.
      var el = makeRowEl(poolRows[idx]);
      var after = -1;
      for (p = idx + 1; p < pool.length; p++) if (pool[p]) { after = p; break; }
      if (after === -1) {
        state.listEl.appendChild(el);
      } else {
        /* Step back over any tier header sitting between him and that anchor.
         * Inserting straight before the anchor would drop him under a band whose
         * boundary he is above — the header would then be claiming a tier for the
         * first row beneath it that is not the row's own. */
        var anchor = pool[after], prev = anchor.previousElementSibling;
        while (prev && prev.classList.contains('oven-tiersep') &&
               String(poolRows[idx].tier) !== prev.getAttribute('data-tier')) {
          anchor = prev;
          prev = anchor.previousElementSibling;
        }
        anchor.parentNode.insertBefore(el, anchor);
      }

      pool[idx] = el;
      state.rowEls.set(poolRows[idx].key, el);
    }
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
    dropRescued();
    state.listEl.querySelectorAll('.oven-row.atrisk').forEach(function (e) {
      e.classList.remove('atrisk');
    });

    var clock = state.clock;
    if (!clock || !clock.myUpcoming.length || clock.onTheClock == null) return;

    /* The pool is every undrafted player on the board — NOT every undrafted row
     * on screen. A filter hides rows; it does not remove anyone from the draft.
     * Counting only what's visible is what made `Hide: Fade` push the horizon
     * DOWN the board: the faded players between you and your pick stopped being
     * counted as gone-before-you, so the marker had to eat that many extra
     * visible names to reach `ahead`. Same for a position filter.
     *
     * So walk `state.rows` (the one true order, which the visible list only
     * samples) and record, per available player, the row element if he happens
     * to be on screen and `null` if he's filtered out. Positions are then indices
     * into the FULL pool, and a marker anchors to the first player at or after
     * that depth who is actually rendered. Drafted players stay out of the pool
     * on both paths — they really are gone — which is why `Hide: Drafted` never
     * moved the horizon and `Hide: Fade` did. */
    var pool = [];
    var poolRows = [];
    var els = state.rowEls;
    state.rows.forEach(function (r) {
      if (state.drafted[r.key]) return;
      poolRows.push(r);
      pool.push((els && els.get(r.key)) || null);
    });

    function anchorFrom(idx) {
      for (var p = idx; p < pool.length; p++) if (pool[p]) return p;
      return -1;
    }

    // Depth into the pool at which each of my remaining picks lands: the number
    // of still-unfilled picks between the clock and mine. Computed up front
    // because a pick's WINDOW is [its own depth, the next pick's depth) — the
    // players it can realistically reach — and the rescue pass below needs both
    // ends of that span before any marker is placed.
    var filled = clock.filled;
    var depths = [];
    for (var d = 0; d < clock.myUpcoming.length; d++) {
      var ah = 0;
      for (var q = clock.onTheClock; q < clock.myUpcoming[d]; q++) if (!filled[q]) ah++;
      depths.push(ah);
    }

    rescueEmptyWindows(pool, poolRows, depths);

    // Every remaining pick of mine gets a horizon, not just the next few — the
    // loop runs out on its own once a marker would land past the bottom of the
    // board. The first is the signature; the rest are quiet rules that say the
    // same thing, so a scroll down the board reads as "mine, mine, mine".
    for (var m = 0; m < clock.myUpcoming.length; m++) {
      var pickNo = clock.myUpcoming[m];
      var ahead = depths[m];
      if (ahead >= pool.length) break;

      // Past the last rendered row: the horizon is off the bottom of the board
      // as filtered, and every later pick is further down still.
      var targetIdx = anchorFrom(ahead);
      if (targetIdx === -1) break;
      var target = pool[targetIdx];
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
        // The hatch paints the visible members of the chalk; the count states the
        // real one. A filter subtracts rows from the band, never from the number
        // — "10 gone before you're up" is a fact about the draft, not about what
        // this screen is currently showing.
        for (var a = 0; a < ahead && a < pool.length; a++) {
          if (pool[a]) pool[a].classList.add('atrisk');
        }
        // No visible chalk row means no band to name — and the header would land
        // between the horizon and the row it points at, reading as if the chalk
        // came after your pick.
        var firstIdx = ahead > 0 ? anchorFrom(0) : -1;
        if (firstIdx !== -1 && firstIdx < ahead) {
          var first = pool[firstIdx];
          var zone = document.createElement('div');
          zone.className = 'oven-zone';
          zone.innerHTML = '<span>The chalk</span>' +
            '<span class="oven-zone-line"></span>' +
            '<span>' + ahead + ' gone before you’re up</span>';
          first.parentNode.insertBefore(zone, first);
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
   * `myRank` from the top, re-renders — which is what refreshes his Δ against
   * consensus and his positional rank — and hands the new rows to the host to persist — into the same per-league blob a
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
    // Positional rank is a reading of that same order, so it is renumbered with
    // it — a drop that moved a WR past four other WRs has changed five badges,
    // not one, and the next render is where they all have to be right.
    computePosRanks(state.rows);
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
   * order you dragged.
   *
   * The rows buildBoard set aside for being at a position this league doesn't
   * start ride along at the end, verbatim. This is a WRITE path: every save the
   * board makes (a drag, a grade) goes through here, so dropping them would make
   * the first click on any row quietly delete the kickers out of the stored
   * sheet. They keep their own myRank — nothing on screen was ordered against
   * them, so there is no order here to restate, and rewriting a number the user
   * typed to paper over a gap in the visible ranks would be the bigger lie.
   * buildBoard splits them straight back out on the next load. */
  function exportRows() {
    function shape(r) {
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
    }
    return state.rows.map(shape).concat((state.offBoard || []).map(shape));
  }

  function wireReorder(listEl) {
    listEl.addEventListener('dragstart', function (e) {
      var row = rowUnder(e);
      if (!row) return;
      // A menu left open would float over a board that is about to reorder
      // under it.
      closeGradeMenu(false);
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

      render();
      if (state.onReorder) state.onReorder(exportRows());
      // The projection reads myRank, so a move that doesn't refresh leaves an
      // open drawer describing the board as it was until the next poll.
      if (global.OvenTargets) global.OvenTargets.refresh();
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
    setPositions: setPositions,
    buildBoard: buildBoard,
    setWeekly: setWeekly,
    indexPicks: indexPicks,
    render: render,
    applyDraftState: applyDraftState,
    enableReorder: enableReorder,
    enableGrading: enableGrading,
    setGrade: setGrade,
    exportRows: exportRows,
    state: state,
  };
})(window);
