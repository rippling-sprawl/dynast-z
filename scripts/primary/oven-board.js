/* Baker's Oven — board model and rendering (window.OvenBoard).
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

  /* The NFL abbreviations actually present on the board, sorted, for the team
   * filter's options. Read off the rows rather than from a hardcoded list of 32
   * for the same reason the position chips get pruned: an option with no rows
   * behind it isn't a filter, it's a button that empties the board. A relocated
   * or renamed franchise also needs no edit here — whatever the sheet and the
   * FantasyPros snapshot spell the team, that is what you can filter to.
   *
   * Rows with no team (free agents, a sheet with the column blank) contribute
   * nothing: there is no abbreviation to offer, and they stay visible under
   * "All" like every other unfiltered row. */
  function boardTeams() {
    var seen = {};
    state.rows.forEach(function (r) {
      var t = (r.team || '').toUpperCase();
      if (t) seen[t] = true;
    });
    return Object.keys(seen).sort();
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
          myRank: i + 1, tier: p.tier, grade: null, extra: {},
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

  /* ---------- the import merge ---------- */

  /* The board blob's row shape, in one place: a CSV import and a drag on the
   * board both write it, and the two have to agree byte for byte or a merge
   * would silently invent or drop a field. */
  function shapeRow(r) {
    return {
      name: r.name,
      pos: r.pos || '',
      team: r.team || '',
      tier: r.tier == null ? null : r.tier,
      myRank: r.myRank == null ? null : r.myRank,
      grade: r.grade || null,
      extra: r.extra || {},
      player_id: r.player_id || null,
    };
  }

  /* Same shape, but `extra` is copied rather than shared. The merge mutates it,
   * and the league page runs a throwaway merge to count what a file would do
   * before you've agreed to anything — a dry run that edited the live board
   * would be the worst possible way to find that out. */
  function cloneRow(r) {
    var row = shapeRow(r);
    row.extra = {};
    Object.keys(r.extra || {}).forEach(function (k) { row.extra[k] = r.extra[k]; });
    return row;
  }

  // The canonical CSV fields, so a selection key that is none of them is an
  // extra column's own label. mapColumns only files a header under `extras`
  // when nothing in HEADER_ALIASES matched, so the two namespaces can't collide
  // and one flat map can carry both.
  var CANON_FIELDS = {
    player: 1, pos: 1, team: 1, tier: 1, myRank: 1, grade: 1, target: 1,
  };

  function findExisting(inc, byKey, byName, claimed, warnings) {
    var probes = [playerKey(inc.name, inc.pos, inc.team)];

    /* A defense whose Pos cell is blank: "Denver Broncos" keys as
     * `|denver broncos`, while the row already on the board is `DEF|DEN`.
     * playerKey only consults DEF_TEAMS once it already believes the row is a
     * defense, so the nickname has to be probed explicitly. */
    if (!normPos(inc.pos)) {
      var t = teamFromDefenseName(inc.name);
      if (t) probes.push('DEF|' + t);
    }

    var taken = false;
    for (var i = 0; i < probes.length; i++) {
      var j = byKey[probes[i]];
      if (j === undefined) continue;
      if (!claimed[j]) return j;
      taken = true;
    }

    /* Pos or team disagree — the sheet moved him to WR, or still carries last
     * season's team code. The name is the identity of last resort, and only
     * when it points at exactly one row: merging onto a guess would overwrite
     * the wrong player, which is the one failure here nobody would notice. */
    var free = (byName[normName(inc.name)] || []).filter(function (j) { return !claimed[j]; });
    if (free.length === 1) return free[0];

    /* Two lines in one file for the same player. parseBoard only catches the
     * exact-name case, so "A.J. Brown" and "AJ Brown" both reach here and the
     * second one has nothing left to land on. It becomes its own row — silently
     * folding it into the first would pick a winner between two cells the user
     * wrote, and neither answer is discoverable from the board afterwards. */
    if (taken || free.length > 1) {
      warnings.push('"' + inc.name + '" matches a player this file already updated — added as a separate row.');
    }
    return -1;
  }

  function applyRow(row, inc, sel) {
    // Identity always imports, but a blank cell is not an instruction: a sheet
    // that left Pos empty isn't claiming the player has no position.
    var p = normPos(inc.pos);
    if (p) row.pos = p;
    if (inc.team) row.team = String(inc.team).toUpperCase();

    /* A selected column is the file's answer for every row in it, blanks
     * included. That is what lets export -> edit -> re-import CLEAR a grade
     * rather than only ever set one, and it's the rule the Target column has
     * always followed. An unselected column is never read at all. */
    if (sel.tier) row.tier = inc.tier;
    if (sel.myRank) row.myRank = inc.myRank;
    if (sel.grade) row.grade = inc.grade || null;

    Object.keys(sel).forEach(function (k) {
      if (!sel[k] || CANON_FIELDS[k]) return;
      var v = (inc.extra || {})[k];
      // parseBoard only writes non-empty extras onto the row, so without the
      // delete a selected extra column could add and update but never clear.
      if (v != null && v !== '') row.extra[k] = v;
      else delete row.extra[k];
    });

    // player_id is deliberately not written here. The Sleeper resolver should
    // see the MERGED pos and team — a row whose sheet left Pos blank resolves
    // better against the board row that already knows he's an RB — so
    // resolution runs after this, not before it.
  }

  /* Apply an imported CSV to the board a league already has.
   *
   * Additive by design: a row in the file updates the row it matches, a row
   * that matches nothing is appended, and a player on the board the file never
   * mentions is left exactly as he was. An import can add and it can overwrite;
   * it can never remove. That is what makes dropping a hand-built sheet of
   * twelve sleepers onto a 300-player board a safe thing to do.
   *
   * `selected` is the column picker's answer — { tier: true, myRank: false,
   * 'ADP': true, … } — keyed by canonical field name or by an extra column's
   * own label. `target` may appear in it and is deliberately NOT applied here:
   * the queue is a separate synced slice that only the host page has bound.
   *
   * Returns { rows, resolved, updated, added, warnings }. `resolved` carries one
   * entry per incoming row — { row, isNew } — so the host can write the Targets
   * queue against the row a CSV line ENDED UP on. It holds the row rather than a
   * key because Sleeper resolution runs after this and can still fill in a blank
   * position, which would change the key out from under a stored one. */
  function mergeImport(existingRows, incomingRows, selected) {
    var sel = selected || {};
    var out = (existingRows || []).map(cloneRow);
    var byKey = {}, byName = {}, claimed = {}, warnings = [];
    var maxRank = 0;

    out.forEach(function (r, i) {
      var k = playerKey(r.name, r.pos, r.team);
      if (byKey[k] === undefined) byKey[k] = i;   // first wins, as everywhere else
      var n = normName(r.name);
      (byName[n] = byName[n] || []).push(i);
      if (r.myRank != null && r.myRank > maxRank) maxRank = r.myRank;
    });

    var resolved = [], updated = 0, added = 0;

    (incomingRows || []).forEach(function (inc) {
      var i = findExisting(inc, byKey, byName, claimed, warnings);
      var isNew = i === -1;
      var row;
      if (isNew) {
        row = shapeRow({ name: inc.name, extra: {} });
        out.push(row);
        i = out.length - 1;
        added++;
      } else {
        row = out[i];
        updated++;
      }
      /* One board row per incoming row. parseBoard dedupes on the exact
       * lowercased name, so "AJ Brown" and "A.J. Brown" both survive it and
       * both normName the same way; without this the second would land on top
       * of the first instead of surfacing as the duplicate it is. */
      claimed[i] = true;
      applyRow(row, inc, sel);
      /* A new player with no rank — MyRank unselected, or absent from the file
       * — goes to the bottom in file order. Nothing already on the board moves,
       * and buildBoard's sort still has a number to work with. */
      if (isNew && row.myRank == null) row.myRank = ++maxRank;
      resolved.push({ row: row, isNew: isNew });
    });

    return { rows: out, resolved: resolved, updated: updated, added: added, warnings: warnings };
  }

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
    // History and Odds are two chips because they are two claims — where he
    // finished, and what he is priced to do — and wanting one is no reason to
    // carry the other. Both start OFF: the board's default state is the order
    // and nothing else, and a row that annotates itself before you ask is a row
    // you have to read past 860 times.
    // `team` is an NFL abbreviation (uppercase, as the rows carry it) or null
    // for all — the same shape as `pos`, and for the same reason: both say
    // "this screen is about X" rather than taking rows away.
    filters: { pos: null, team: null, hideDrafted: false, hideFade: false, showHistory: false, showOdds: false },
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
    // Where he actually finished, half-PPR, for the last two seasons — the
    // payload of /data/nfl_pos_ranks.json verbatim: {seasons: [Y-1, Y-2],
    // ranks: {key: [rank|null, rank|null]}}. Held whole rather than flattened
    // because the seasons ride WITH the ranks: the file decides which two years
    // it is about, and a renderer that took the years from anywhere else would
    // label 2024's number 2025 the first summer nobody re-ran the fetch.
    posRanks: null,
    // What the market has him doing this season: the `lines` map of
    // /data/nfl_prop_lines.json, keyed by normalized NAME with no position
    // prefix — {name: {yards, tds, parts, books}}. Name-only because the books'
    // feeds carry no position at all (see build_prop_lines.py), so this is the
    // one lookup on the row that doesn't go through playerKey().
    props: null,
    // Whether ANY priced player has a receptions line — see setPropLines.
    hasRecs: false,
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

  /* Set once at boot from the fetched file, whole. Rejects a payload without
   * both halves rather than half-storing it: a `ranks` map with no `seasons`
   * would render two unlabeled numbers, which is worse than rendering none. */
  function setPosRanks(payload) {
    state.posRanks = payload && payload.seasons && payload.ranks ? payload : null;
  }

  /* Set once at boot from the fetched file. Only the `lines` map is kept — the
   * file's own bookkeeping (build time, per-book market counts) lives in the
   * meta file beside it, and nothing on the row reads it. */
  function setPropLines(payload) {
    state.props = payload && payload.lines ? payload.lines : null;
    /* Whether the REC slot exists on the row at all, decided once here rather
     * than per row. Within a group that exists, a missing slot keeps its box so
     * the numbers line up down the board (see propCell) — but that rule assumes
     * SOMEBODY is priced for it. No book currently posts a season-long
     * receptions market, and holding an empty third slot on every priced row for
     * a number that is never there would be a column of reserved nothing.
     *
     * One pass over ~100 entries at boot, so the row renderer stays a lookup. */
    state.hasRecs = false;
    for (var k in (state.props || {})) {
      if (state.props[k].recs != null) { state.hasRecs = true; break; }
    }
  }

  function visibleRows() {
    var f = state.filters;
    var out = state.rows.filter(function (r) {
      if (f.pos && r.pos !== f.pos) return false;
      if (f.team && (r.team || '').toUpperCase() !== f.team) return false;
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
   * PARKED: oven-board.html no longer fetches the weekly file or calls
   * setWeekly(), and the chip that set .show-weekly is gone from the controls.
   * With state.weekly null this returns '' and the feature costs nothing.
   * Everything here still works the moment a host calls setWeekly() again.
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
    // No weekly file scored means no chip to reveal this, so the markup would be
    // 860 divs nothing can ever show. Emitted only when the counts exist.
    if (!state.weekly) return '';
    var w = state.weekly[r.key];
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

  /* How good a finish IS, graded against his own position — because RB4 and WR4
   * are not the same achievement and a scale that treated them alike would be
   * worse than no scale at all. The whole point of a positional rank is that it
   * is already normalized; the formatting has to stay normalized with it.
   *
   * The yardstick is how many of that position get STARTED league-wide
   * (OVEN.POSRANK_STARTERS), not a percentile of everyone who took a snap. There
   * were 253 ranked WRs last season and a percentile over them would put WR40 —
   * a man nobody started — comfortably in the top fifth. Against 30 starting
   * WRs, WR40 is what it actually was: off the board.
   *
   * Four steps, and four is the ceiling on purpose: the same reason .oven-delta
   * buckets its opacity rather than computing one. Nobody resolves more than
   * about four levels in a 10px number, and this is a sub-line under a name, not
   * a chart.
   *
   *   t1  top half of the starters   an every-week guy — the finish you draft for
   *   t2  the rest of the starters   a starter, unremarkably
   *   t3  out to twice the starters  bench, bye-week filler
   *   t4  beyond that                he was not a fantasy player that year
   */
  function posRankTier(pos, rank) {
    var starters = C.POSRANK_STARTERS[pos] || C.POSRANK_STARTERS_DEFAULT;
    if (rank <= starters / 2) return 't1';
    if (rank <= starters) return 't2';
    if (rank <= starters * 2) return 't3';
    return 't4';
  }

  /* Where he finished: half-PPR positional rank for the last three seasons, the
   * number off Sleeper's own player card.
   *
   * Not the same claim as anything else on the row, which is why it earns its
   * line. The Δ column is where the market has him THIS year; the weekly chip is
   * how many weeks he was startable last year, under this league's rules. This
   * is the flat historical fact — RB4, RB19, RB8 — and it's the one people
   * already carry in their heads, because it's how finishes get quoted.
   *
   * Three seasons, not two, and the third is what makes the group a shape rather
   * than a comparison: two numbers say "better or worse than last year", three
   * say whether the good year was the pattern or the exception. Off by default
   * behind the History chip, which is what buys the room for the third — the
   * board's resting state is your order and nothing else.
   *
   * Season count comes from the FILE, never from here: the loop below walks
   * pr.seasons, so re-running fetch_pos_ranks.py with a different window changes
   * the line and nothing in this renderer.
   *
   * A season he didn't play renders as EMPTY SPACE, not as a dash and not as
   * nothing: the slot keeps its box (`visibility: hidden` on a slot that still
   * holds its year and a placeholder), so the second year sits at the same x on
   * every row and the line is the same height whether a player has two finishes,
   * one, or none. A dash was a mark to read on 200 rookie rows; blank says the
   * same thing by saying nothing. The title still spells out "did not play" for
   * the row you stop on. */
  function posRankCell(r) {
    var pr = state.posRanks;
    if (!pr) return '';        // file never loaded — no line at all, not a row of dashes

    var ranks = pr.ranks[r.key] || [];
    var cells = [], label = [];
    for (var i = 0; i < pr.seasons.length; i++) {
      var yr = pr.seasons[i], n = ranks[i];
      // The position rides on the number ("RB4"), the way a finish is spoken,
      // rather than being implied by the badge four columns to the left. The
      // badge holds MY rank for this year — two bare numbers under it, meaning
      // something else entirely, would read as more of the same.
      //
      // The placeholder on a missing season is a real rank's worth of glyphs,
      // never a dash: it's invisible, and its only job is to hold a box the
      // same size the number would have taken.
      var txt = n == null ? '—' : (r.pos || '#') + n;
      cells.push('<span class="opr' + (n == null ? ' is-none' : ' ' + posRankTier(r.pos, n)) + '">' +
        '<i class="opr-y">' + esc(String(yr)) + '</i>' +
        '<span class="opr-n">' + esc(txt) + '</span></span>');
      label.push(yr + ': ' + (n == null ? 'did not play' : txt));
    }
    return '<div class="oven-posrank" title="' +
      esc('Half-PPR positional finish · ' + label.join(' · ') + ' — Sleeper') +
      '">' + cells.join('') + '</div>';
  }

  /* What the market has him doing this season: consensus yardage, touchdowns
   * and — where a book posts the market — receptions, sitting to the right of
   * the finishes on the same sub-line.
   *
   * They share a line with the finishes because they answer the same question —
   * how good is he — and reading "RB4 RB19 RB8 1150 9.5" left to right IS the
   * argument: what he did, then what he's priced to do. Put on their own line
   * they'd be a third thing under the name and the comparison would cost a
   * saccade. The two chips are what decide whether either group is there; this
   * function only decides what a group SAYS when it is.
   *
   * They are drawn as a separate GROUP because they are a separate claim, and
   * the difference matters more than the adjacency: a finish is a settled fact
   * off Sleeper, a line is three sportsbooks' current price on a season nobody
   * has played. Same line, one rule between them, different labels — the seasons
   * over the finishes, YDS/TD/REC over the odds. Nothing about the two groups is
   * meant to look averageable.
   *
   * Blank is the normal state. About a hundred players are priced at all, so
   * seven rows in eight have no odds here — which is why the group vanishes
   * entirely rather than holding an empty box the way a missing SEASON does.
   * A missing season is a hole in a two-slot line that has to stay aligned; a
   * player with no market has no group at all, and 750 rows of reserved empty
   * space would be a column of nothing down the whole board. */
  function propNum(n, decimals) {
    return n == null || isNaN(n) ? null : Number(n).toFixed(decimals || 0);
  }

  function propCell(r) {
    if (!state.props) return '';        // file never loaded — no group, not an empty one
    var p = state.props[normName(r.name)];
    if (!p) return '';                  // not priced — the common case

    // Yards to the whole yard, TDs and receptions to a tenth. The file already
    // rounds to exactly this (see build_prop_lines.py) — the toFixed here is
    // about PRINTING, so a consensus of 8 TDs reads "8.0" beside a 9.5 instead
    // of shrinking to a single glyph and breaking the column.
    // Receptions last, after the two summed totals: it is the one number here
    // that is a single market rather than a sum, and it is the one that decides
    // a PPR draft — read at the end of the line it lands as the punchline of
    // "what is he priced to do", not as a third kind of yardage.
    var pairs = [
      { k: 'YDS', v: propNum(p.yards, 0) },
      { k: 'TD', v: propNum(p.tds, 1) },
    ];
    if (state.hasRecs) pairs.push({ k: 'REC', v: propNum(p.recs, 1) });
    var cells = [], label = [];
    for (var i = 0; i < pairs.length; i++) {
      // A priced player missing one of the two (a rusher with a yardage line and
      // no touchdown market) keeps the slot, hidden, exactly as a missing season
      // does — within a group that exists, the two slots still have to line up.
      var has = pairs[i].v != null;
      cells.push('<span class="opl' + (has ? '' : ' is-none') + '">' +
        '<i class="opl-k">' + pairs[i].k + '</i>' +
        '<span class="opl-n">' + esc(has ? pairs[i].v : '0') + '</span></span>');
      if (has) {
        label.push(pairs[i].v + (pairs[i].k === 'TD' ? ' TDs'
          : pairs[i].k === 'REC' ? ' receptions' : ' yards'));
      }
    }

    // The title carries what the two numbers can't: which markets were summed to
    // make them, and which books priced it. A 4025 next to a 3250 is two
    // different sentences depending on whether the first one includes 480
    // rushing yards, and the row can't say that in the space it has.
    var parts = [];
    // One decimal on every component, whatever the file stored: these are the
    // unrounded per-market consensus figures, and "rushing tds 11" beside
    // "passing tds 24.2" reads as a different kind of number rather than as the
    // same one that happened to land on a whole.
    for (var k in p.parts) {
      parts.push(k.replace('tds', 'TDs') + ' ' + Number(p.parts[k]).toFixed(1));
    }
    var books = (p.books || []).map(function (b) { return C.PROPS_BOOKS[b] || b; });
    return '<div class="oven-props" title="' +
      esc('Market consensus · ' + label.join(' · ') +
        (parts.length ? ' — ' + parts.join(', ') : '') +
        (books.length ? ' · ' + books.join(', ') : '')) +
      '">' + cells.join('') + '</div>';
  }

  /* The sub-line the two of them share: finishes, a rule, odds.
   *
   * Both groups are emitted on every row whatever the chips say, and CSS decides
   * which are visible — same trick the weekly table uses, and for the same
   * reason: flipping a class on the list beats re-rendering 860 rows, which
   * would throw your scroll position back to the top mid-run.
   *
   * The rule is emitted only when both sides EXIST, which is the whole reason
   * this isn't a border on .oven-props. A border would draw a stray leading
   * hairline on every unpriced row (and on every row at all, the summer the
   * pos-ranks file is missing) — a separator with nothing on one side of it is a
   * mark that means nothing. Existing isn't enough now that the two are toggled
   * apart, though: with History on and Odds off the rule would dangle off the
   * end of the finishes. So CSS shows it only when BOTH chips are on, and this
   * function's job is just to make sure there is one to show. */
  function subLine(r) {
    var hist = posRankCell(r);
    var odds = propCell(r);
    if (!hist && !odds) return '';
    return '<div class="oven-subline">' + hist +
      (hist && odds ? '<span class="oven-subsep" aria-hidden="true"></span>' : '') +
      odds + '</div>';
  }

  /* Every row is the same flat markup — no inline styles at all now that the heat
   * wash is gone, which is why applyDraftState() can patch a row by touching
   * classes and never has to reason about what color it was. */
  function rowHTML(r) {
    // Rank vs consensus, printed — the whole of the board's market signal, in one
    // column. Straight from the two ranks: a grade is what *I* think of him and
    // has no business moving a number that reports what the market thinks.
    var d = r.fpRank != null && r.myRank != null ? r.fpRank - r.myRank : null;
    // Printed as a percentage of where I have him, not as spots, because a spot
    // is not a fixed unit down the board. Four spots at pick 8 moves a player
    // across half a round of value; four spots at pick 120 is inside the noise
    // of who happens to be listed next. Dividing by myRank is what makes the
    // column comparable top to bottom — +50% reads the same at 8 as at 200.
    var pct = d == null ? null : Math.round((d / r.myRank) * 100);
    // The gate is still spots, deliberately: percent alone would make the top of
    // the board scream (rank 2 vs ECR 3 is +50% off one spot of nothing). Four
    // spots is the floor for "we actually disagree", and the percent then says
    // how much that gap is worth where he sits. Under it the cell goes empty,
    // same as a player with no consensus rank, so the eye only ever lands on the
    // column when it means something — the title still has the numbers.
    var dShown = d != null && Math.abs(d) >= 4;
    var mag = pct == null ? 0 : Math.abs(pct);
    // Hue is direction, opacity is size — the two facts the column carries, on
    // two channels that don't fight. Buckets, not a computed alpha, because rows
    // are styled by class alone (see the note above rowHTML) and four steps is
    // all the eye resolves in an 11px number anyway.
    var dCls = !dShown ? 'zero' : (d > 0 ? 'pos' : 'neg') + ' ' +
      (mag >= 60 ? 'd4' : mag >= 30 ? 'd3' : mag >= 12 ? 'd2' : 'd1');
    // Clamped, not because 2400% is wrong — a WR I have at 3 and the market has
    // at 75 really is that far apart — but because the column is 48px and the
    // exact figure past a point isn't the message. The title keeps the truth.
    var dTxt = !dShown ? '' : (d > 0 ? '+' : '-') + Math.min(mag, 999) + '%';
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
        // opt out, so the team has to sit outside the struck span rather than
        // be un-struck inside it.
        '<div class="oven-name-main"><span class="oven-name-text">' + esc(r.name) + '</span>' +
          (r.team ? '<span class="oven-name-team">' + esc(r.team) + '</span>' : '') + '</div>' +
        // Both sub-lines belong to the name column, not to columns of their own:
        // they annotate the player, and they grow the row downward instead of
        // widening it. History and odds first, the weekly table under them, so
        // the order on the row matches the order of the chips that reveal them.
        // Everything is emitted on every row regardless of the chips; they flip
        // classes on the list, so no toggle costs a re-render.
        subLine(r) +
        weeklyCell(r) +
      '</div>' +
      // The title carries what the cell can't: the spots, since the printed
      // percent is a ratio and a ratio doesn't say how far anyone moves, and the
      // uncapped percent for the handful of rows the 999 clamp bites.
      '<div class="oven-delta ' + dCls + '" title="' +
        (d == null ? 'no consensus rank' : 'ECR ' + r.fpRank + ' · you have him ' +
          (d === 0 ? 'there too' : Math.abs(d) + ' spot' + (Math.abs(d) === 1 ? '' : 's') +
            (d > 0 ? ' higher' : ' lower') + ' (' + (d > 0 ? '+' : '-') + Math.abs(pct) +
            '%)')) + '">' + dTxt + '</div>' +
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

    // Tiers are carried on the row and round-trip through the CSV, but the board
    // no longer draws them: the horizons already cut it into the only windows
    // that decide anything, and a second set of bands competed with them.
    var html = [];
    for (var i = 0; i < rows.length; i++) html.push(rowHTML(rows[i]));

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
   * The POSITION and TEAM filters are not overridden, and that asymmetry is
   * deliberate. `Hide: Fade` says "take these off my board", so showing one back
   * is a correction. Filtering to RB — or to BUF — says "this screen is running
   * backs"; answering "no RB in that window" with a receiver would be answering a
   * question nobody asked. An empty window under either of those is a real
   * finding, so it is left to stack. `Hide: Drafted` never empties a window at
   * all: drafted players are out of the pool on both paths. */

  function rescuable(r) {
    if (state.filters.pos && r.pos !== state.filters.pos) return false;
    if (state.filters.team && (r.team || '').toUpperCase() !== state.filters.team) return false;
    return true;
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
      if (after === -1) state.listEl.appendChild(el);
      else pool[after].parentNode.insertBefore(el, pool[after]);

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

      // The territory above the first horizon is a named zone, not a texture:
      // these are the players who go before you choose. It names the band and
      // stops there — a count of how many go first is a number you can't act on,
      // and the horizon below already says where you land.
      if (m === 0) {
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
            '<span class="oven-zone-line"></span>';
          first.parentNode.insertBefore(zone, first);
        }
      }
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

    /* His tier rides along untouched. It used to be rewritten to the neighbor's
     * on every drop, because the board drew tier bands and a stray "Tier 6"
     * header mid-tier-2 was worse than losing the sheet's value. Nothing draws
     * them now, so the only thing that reassignment could do is quietly edit a
     * column the user authored and will export again. */
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
    // shapeRow, shared with mergeImport — the drag and the import write the
    // same blob, so they cannot be allowed to disagree about its shape.
    return state.rows.map(shapeRow).concat((state.offBoard || []).map(shapeRow));
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
      // Horizon markers and the chalk header are not seams — drop them and
      // nothing happens, so drop the hint too rather than promising a landing
      // spot.
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
    boardTeams: boardTeams,
    buildBoard: buildBoard,
    mergeImport: mergeImport,
    setWeekly: setWeekly,
    setPosRanks: setPosRanks,
    setPropLines: setPropLines,
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
