/* Baker's Oven — saved leagues and storage keys (window.OvenLeagues).
 *
 * The Oven used to be one hardcoded league. It is now a per-account list:
 * paste a Sleeper league id, we fetch its metadata, you say which team is
 * yours, and it persists to the same user_data blob store everything else uses
 * (sport 'football', data_key 'oven_leagues'). No new table, no new endpoint.
 *
 * This module also owns every Oven storage key, because the key SHAPE is a
 * correctness concern rather than a naming one. localStorage keys carry the
 * signed-in user id: loadWithSync auto-migrates whatever it finds locally into
 * the server row of whoever is signed in, so a fixed global key silently hands
 * one account's big board to the next person to log in on a shared browser.
 * League-scoped slices carry the league id too — a CSV board and a target
 * queue only mean anything against the draft they were built for.
 */
(function (global) {
  'use strict';

  var C = global.OVEN;

  // Sleeper ids are 18-19 digit snowflakes. Kept as strings everywhere: 19
  // digits is past 2^53, so Number() would round and quietly point at nothing.
  var ID_RE = /^\d{6,25}$/;

  var cache = null;   // [record] once load() resolves

  /* ---------- keys ---------- */

  function userId() {
    var u = (typeof getUser === 'function' && getUser()) || null;
    // Every Oven page gates on requireLogin, so ':anon' is defensive only — but
    // it still keeps a signed-out browse from writing a key that loadWithSync
    // would later migrate into the next account.
    return u ? u.user_id : 'anon';
  }

  function localKey(base, leagueId) {
    return base + ':' + userId() + (leagueId ? ':' + leagueId : '');
  }

  function boardKeys(leagueId) {
    return {
      sport: C.SYNC_SPORT,
      syncKey: C.BOARD_SYNC_KEY + ':' + leagueId,
      storageKey: localKey(C.BOARD_STORAGE_BASE, leagueId),
    };
  }

  function targetKeys(leagueId) {
    return {
      sport: C.SYNC_SPORT,
      syncKey: C.TARGETS_SYNC_KEY + ':' + leagueId,
      storageKey: localKey(C.TARGETS_STORAGE_BASE, leagueId),
    };
  }

  /* ---------- the list ---------- */

  function persist() {
    saveWithSync(C.SYNC_SPORT, C.LEAGUES_SYNC_KEY, localKey(C.LEAGUES_STORAGE_BASE),
      { leagues: cache, updatedAt: Date.now() });
  }

  function load() {
    return loadWithSync(C.SYNC_SPORT, C.LEAGUES_SYNC_KEY, localKey(C.LEAGUES_STORAGE_BASE), null)
      .then(function (blob) {
        cache = (blob && Array.isArray(blob.leagues)) ? blob.leagues : [];
        return cache;
      });
  }

  function list() { return cache || []; }

  function get(leagueId) {
    var id = String(leagueId);
    var found = list().filter(function (l) { return l.league_id === id; });
    return found.length ? found[0] : null;
  }

  /* ---------- adding ---------- */

  // Accepts a bare id or a pasted Sleeper URL (sleeper.com/leagues/{id}/team).
  function parseId(input) {
    var s = String(input || '').trim();
    var m = s.match(/\d{6,25}/);
    var id = m ? m[0] : s;
    return ID_RE.test(id) ? id : null;
  }

  /* Fetch a league and its rosters, enough to render the team picker.
   *
   * Deliberately NOT /drafts: that call is what makes OvenDraft.loadLeague
   * throw "This league has no draft yet", and a league whose draft isn't
   * scheduled must still be addable. draft_id comes off the league object when
   * it exists and is re-derived on view anyway. */
  function fetchMeta(leagueId) {
    var id = parseId(leagueId);
    if (!id) return Promise.reject(new Error("That doesn't look like a Sleeper league ID."));

    return Promise.all([
      OvenDraft.api('/league/' + id),
      OvenDraft.api('/league/' + id + '/rosters'),
      OvenDraft.api('/league/' + id + '/users'),
    ]).then(function (res) {
      var league = res[0];
      // Sleeper answers an unknown-but-well-formed id with 404 and a `null`
      // body, so api() throws before we get here — but a null body on a 200 is
      // cheap to guard and would otherwise blow up on league.name.
      if (!league || !league.league_id) throw new Error('No Sleeper league with that ID.');
      if (league.sport && league.sport !== 'nfl') {
        throw new Error("The Oven is NFL-only — that's a " + league.sport + ' league.');
      }
      return { league: league, teams: OvenDraft.shapeTeams(res[1], res[2]) };
    }, function (err) {
      var m = String(err && err.message || '');
      if (m.indexOf('404') !== -1) throw new Error('No Sleeper league with that ID.');
      if (m.indexOf('Sleeper ') === 0) throw err;
      throw new Error("Couldn't reach Sleeper. Try again.");
    });
  }

  function recordFrom(league, team) {
    var now = Date.now();
    return {
      league_id: String(league.league_id),
      name: league.name || 'Untitled league',
      season: String(league.season || ''),
      sport: league.sport || 'nfl',
      avatar: league.avatar ? 'https://sleepercdn.com/avatars/thumbs/' + league.avatar : null,
      total_rosters: league.total_rosters || 0,
      status: league.status || 'pre_draft',
      draft_id: league.draft_id || null,
      my_roster_id: team ? team.roster_id : null,
      my_owner_id: team ? team.owner_id : null,
      my_username: team ? team.username : null,
      my_team_name: team ? team.teamName : null,
      added_at: now,
      refreshed_at: now,
    };
  }

  function add(league, team) {
    var rec = recordFrom(league, team);
    if (get(rec.league_id)) return get(rec.league_id);
    cache = list().concat([rec]);
    persist();
    return rec;
  }

  function remove(leagueId) {
    var id = String(leagueId);
    // The league's board and target blobs are intentionally left alone — if you
    // re-add the league mid-draft you want your board back, not a blank one.
    cache = list().filter(function (l) { return l.league_id !== id; });
    persist();
  }

  function setMyTeam(leagueId, team) {
    var rec = get(leagueId);
    if (!rec || !team) return null;
    rec.my_roster_id = team.roster_id;
    rec.my_owner_id = team.owner_id;
    rec.my_username = team.username;
    rec.my_team_name = team.teamName;
    persist();
    return rec;
  }

  /* Refresh the stored snapshot from a league page's already-loaded context.
   *
   * The leagues page paints from these fields with no Sleeper call at all, so
   * they go stale on their own; this is the only thing that updates them.
   * Writes only when something actually changed, so opening a board every 8
   * seconds during a draft doesn't turn into a write storm. */
  function refreshFromCtx(leagueId, ctx) {
    var rec = get(leagueId);
    if (!rec || !ctx || !ctx.league) return null;
    var L = ctx.league;

    var next = {
      name: L.name || rec.name,
      season: String(L.season || rec.season),
      avatar: L.avatar ? 'https://sleepercdn.com/avatars/thumbs/' + L.avatar : rec.avatar,
      total_rosters: L.total_rosters || rec.total_rosters,
      status: L.status || rec.status,
      draft_id: ctx.draftId || L.draft_id || rec.draft_id,
    };

    // my_roster_id is the authoritative field — the rest of the my_* block is a
    // snapshot of whatever that roster is called today.
    var mine = (ctx.teams || []).filter(function (t) { return t.roster_id === rec.my_roster_id; })[0];
    if (mine) {
      next.my_owner_id = mine.owner_id;
      next.my_username = mine.username;
      next.my_team_name = mine.teamName;
    }

    var changed = Object.keys(next).some(function (k) { return rec[k] !== next[k]; });
    if (!changed) return rec;

    Object.keys(next).forEach(function (k) { rec[k] = next[k]; });
    rec.refreshed_at = Date.now();
    persist();
    return rec;
  }

  /* ---------- last-viewed ---------- */

  function lastLeagueId() {
    try { return localStorage.getItem(localKey(C.LAST_LEAGUE_BASE)) || null; } catch (e) { return null; }
  }

  function setLastLeagueId(id) {
    try { localStorage.setItem(localKey(C.LAST_LEAGUE_BASE), String(id)); } catch (e) { /* private mode */ }
  }

  global.OvenLeagues = {
    localKey: localKey,
    boardKeys: boardKeys,
    targetKeys: targetKeys,
    load: load,
    list: list,
    get: get,
    parseId: parseId,
    fetchMeta: fetchMeta,
    add: add,
    remove: remove,
    setMyTeam: setMyTeam,
    refreshFromCtx: refreshFromCtx,
    lastLeagueId: lastLeagueId,
    setLastLeagueId: setLastLeagueId,
  };
})(window);
