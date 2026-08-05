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
          bye: fp ? fp.bye : null,
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
          fpRank: p.rank, fpPosRank: p.pos_rank, bye: p.bye,
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

  var state = {
    rows: [], rowEls: null, listEl: null, teams: {},
    drafted: {},          // key -> pick
    sort: { key: 'myRank', dir: 'asc' },
    filters: { pos: null, q: '', hideDrafted: false },
    clock: null, teamsCount: 12, myRosterId: null,
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
    var q = f.q.trim().toLowerCase();
    var out = state.rows.filter(function (r) {
      if (f.pos && r.pos !== f.pos) return false;
      if (f.hideDrafted && state.drafted[r.key]) return false;
      if (q && r.name.toLowerCase().indexOf(q) === -1) return false;
      return true;
    });
    var s = state.sort;
    if (s.key !== 'myRank' || s.dir !== 'asc') {
      out = global.Sort.sortBy(out, s.dir, {
        accessor: function (r) { return r[s.key]; },
        numeric: s.key !== 'name' && s.key !== 'pos',
        nullsLast: true,
      });
    }
    return out;
  }

  function rowHTML(r, rail, wash) {
    var heat = r.heat;
    var railC = heat == null ? '' : rail(heat);
    var washC = r.heatRegion == null ? '' : wash(r.heatRegion);
    var d = r.fpRank != null && r.myRank != null ? r.fpRank - r.myRank : null;
    var dCls = d == null ? 'zero' : (d > 0 ? 'pos' : (d < 0 ? 'neg' : 'zero'));
    var dTxt = d == null ? '—' : (d > 0 ? '+' + d : String(d));
    var sub = [r.team, r.fpPosRank, r.bye ? 'BYE ' + r.bye : ''].filter(Boolean).join(' · ');
    // A graded row is colored by the grade, not by the rank delta, so name the
    // grade — otherwise a strong green rail next to "Δ 0" reads as a bug.
    var gradeChip = r.grade
      ? ' <span class="oven-grade ' + esc(r.grade) + '">' + esc(r.grade) + '</span>'
      : '';

    return '<div class="oven-row" data-key="' + esc(r.key) + '"' +
      (washC ? ' style="background:' + washC + '"' : '') + '>' +
      '<div class="oven-rail" style="background:' + railC + '"></div>' +
      '<div class="oven-rk">' + (r.myRank == null ? '' : r.myRank) + '</div>' +
      '<div class="oven-mark"></div>' +
      '<span class="player-pos pos-' + esc(r.pos || 'OTHER') + '">' + esc(r.pos || '—') + '</span>' +
      '<div class="oven-name">' +
        '<div class="oven-name-main">' + esc(r.name) + gradeChip +
          (r.note ? ' <span style="color:#6e7681">· ' + esc(r.note) + '</span>' : '') + '</div>' +
        (sub ? '<div class="oven-name-sub">' + esc(sub) + '</div>' : '') +
      '</div>' +
      '<div class="oven-tier">' + (r.tier == null ? '—' : 'T' + r.tier) + '</div>' +
      '<div class="oven-ecr">' + (r.fpRank == null ? '—' : r.fpRank) + '</div>' +
      '<div class="oven-delta ' + dCls + '">' + dTxt + '</div>' +
      '<div class="oven-taken" hidden></div>' +
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
    var byTier = state.sort.key === 'myRank' && state.sort.dir === 'asc';
    // Emit each tier header once, on first appearance. Tiers are only roughly
    // contiguous in personal-rank order — promoting a player past a tier
    // boundary would otherwise ping-pong the headers (Tier 4, Tier 2, Tier 4…).
    var tierSeen = {};

    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      if (byTier && r.tier != null && !tierSeen[r.tier]) {
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
    var old = state.listEl.querySelectorAll('.oven-marker');
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

    var filled = clock.filled;
    for (var m = 0; m < Math.min(clock.myUpcoming.length, 4); m++) {
      var pickNo = clock.myUpcoming[m];
      var ahead = 0;
      for (var n = clock.onTheClock; n < pickNo; n++) if (!filled[n]) ahead++;
      if (ahead >= avail.length) break;

      var target = avail[ahead];
      var label = global.OvenDraft.roundPickLabel(pickNo, state.teamsCount);
      var div = document.createElement('div');
      div.className = 'oven-marker' + (m === 0 ? ' next' : '');
      div.innerHTML = (m === 0 ? 'Your pick · ' : 'Pick ' + (m + 1) + ' · ') + esc(label) +
        (m === 0 ? ' · ' + ahead + ' away' : '') +
        '<span class="oven-marker-line"></span>';
      target.parentNode.insertBefore(div, target);

      if (m === 0) {
        for (var a = 0; a < ahead && a < avail.length; a++) avail[a].classList.add('atrisk');
      }
    }
  }

  function updateTierCounts() {
    if (!state.listEl) return;
    var seps = state.listEl.querySelectorAll('.oven-tiersep');
    for (var i = 0; i < seps.length; i++) {
      var tier = seps[i].getAttribute('data-tier');
      var total = 0, left = 0;
      state.rows.forEach(function (r) {
        if (String(r.tier) !== tier) return;
        total++;
        if (!state.drafted[r.key]) left++;
      });
      var cliff = left <= 2 && left > 0;
      seps[i].querySelector('.tier-count').innerHTML =
        '· ' + left + ' of ' + total + ' left' +
        (cliff ? ' <span class="cliff">· tier cliff</span>' : '');
    }
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
    normName: normName,
    normPos: normPos,
    playerKey: playerKey,
    buildBoard: buildBoard,
    computeHeat: computeHeat,
    indexPicks: indexPicks,
    render: render,
    applyDraftState: applyDraftState,
    state: state,
  };
})(window);
