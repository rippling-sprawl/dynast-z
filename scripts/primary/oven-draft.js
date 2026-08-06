/* The Baker's Oven — Sleeper draft state and polling (window.OvenDraft).
 *
 * Pure logic + network. No DOM. The browser talks to Sleeper directly:
 * api.sleeper.app sends `access-control-allow-origin: *`, so there is no CORS
 * reason to proxy, and going direct keeps server.py's hour-long league cache
 * (LEAGUE_DATA_TTL = 3600) well away from live draft data.
 *
 * Polling strategy — why a heartbeat instead of conditional requests:
 * Sleeper's preflight advertises `access-control-allow-headers` WITHOUT
 * `if-none-match`, so a hand-set conditional header fails CORS. Instead we poll
 * the draft object (~1.2 KB), which carries `last_picked` and `status`, and
 * only refetch the picks array (~80 KB for a full draft) when one of them
 * changes. That is ~66x less data than polling picks directly, and it makes
 * "did anything change" an explicit check rather than a bet on cache behavior.
 */
(function (global) {
  'use strict';

  var C = global.OVEN;

  function api(path, params) {
    var url = C.SLEEPER_API + path;
    if (params) {
      var q = Object.keys(params).map(function (k) {
        return encodeURIComponent(k) + '=' + encodeURIComponent(params[k]);
      });
      if (q.length) url += '?' + q.join('&');
    }
    return fetch(url, { cache: 'no-store' }).then(function (r) {
      if (!r.ok) throw new Error('Sleeper ' + r.status + ' for ' + path);
      return r.json();
    });
  }

  /* ---------- pick math ---------- */

  // Overall pick number for a (round, slot). Snake reverses on even rounds;
  // reversal_round (third-round reversal) flips the parity from that round on.
  // This league has reversal_round 0, but don't hardcode that.
  function pickNoFor(round, slot, teams, type, reversalRound) {
    if (type === 'linear') return (round - 1) * teams + slot;
    var forward = (round % 2 === 1);
    if (reversalRound && round >= reversalRound) forward = !forward;
    return (round - 1) * teams + (forward ? slot : teams - slot + 1);
  }

  /* Build every pick in the draft with its current owner.
   *
   * Ownership comes from slot_to_roster_id, then traded_picks overrides it.
   * In a traded_picks entry, `roster_id` is the ORIGINAL owner and `owner_id`
   * is the CURRENT owner — both are roster ids, not user ids, and `season` is
   * a string. Getting this backwards silently puts "your next pick" on the
   * wrong rows, so it is covered by a fixture test. */
  function buildPickPlan(draft, tradedPicks) {
    var teams = draft.settings.teams;
    var rounds = draft.settings.rounds;
    var type = draft.type;
    var reversal = draft.settings.reversal_round || 0;

    var slotToRoster = {};
    Object.keys(draft.slot_to_roster_id || {}).forEach(function (slot) {
      slotToRoster[Number(slot)] = draft.slot_to_roster_id[slot];
    });

    var traded = {};
    (tradedPicks || []).forEach(function (tp) {
      if (String(tp.season) !== String(draft.season)) return;
      traded[tp.round + '|' + tp.roster_id] = tp.owner_id;
    });

    var plan = [];
    for (var r = 1; r <= rounds; r++) {
      for (var s = 1; s <= teams; s++) {
        var original = slotToRoster[s];
        var key = r + '|' + original;
        plan.push({
          pick_no: pickNoFor(r, s, teams, type, reversal),
          round: r,
          slot: s,
          originalRoster: original,
          owner: traded[key] != null ? traded[key] : original,
        });
      }
    }
    plan.sort(function (a, b) { return a.pick_no - b.pick_no; });
    return plan;
  }

  /* Derive the clock from the picks array.
   *
   * Keepers occupy real pick_no slots before the draft even opens, so the
   * current pick is the first UNFILLED number — never picks.length + 1. */
  function computeClock(plan, picks, myRosterId, totalPicks) {
    var filled = {};
    (picks || []).forEach(function (p) { filled[p.pick_no] = p; });

    var onTheClock = null;
    for (var n = 1; n <= totalPicks; n++) {
      if (!filled[n]) { onTheClock = n; break; }
    }

    var myPicks = plan.filter(function (p) { return p.owner === myRosterId; })
      .map(function (p) { return p.pick_no; });
    var myUpcoming = myPicks.filter(function (n) { return !filled[n]; });
    var myNext = myUpcoming.length ? myUpcoming[0] : null;

    // Unfilled slots between now and my turn — the number that drives the
    // "you're up in N" badge and where the expected-pick markers land.
    var untilMyTurn = null;
    if (myNext != null && onTheClock != null) {
      untilMyTurn = 0;
      for (var i = onTheClock; i < myNext; i++) if (!filled[i]) untilMyTurn++;
    }

    return {
      filled: filled,
      onTheClock: onTheClock,
      myPicks: myPicks,
      myUpcoming: myUpcoming,
      myNext: myNext,
      untilMyTurn: untilMyTurn,
      madeCount: Object.keys(filled).length,
    };
  }

  function roundPickLabel(pickNo, teams) {
    var round = Math.floor((pickNo - 1) / teams) + 1;
    var inRound = pickNo - (round - 1) * teams;
    return round + '.' + (inRound < 10 ? '0' : '') + inRound;
  }

  /* ---------- league bootstrap ---------- */

  /* Join /rosters with /users into the team shape every Oven surface renders.
   *
   * Shared with OvenLeagues.fetchMeta so the "which team is yours?" picker on
   * the leagues page and the team grid on the league page cannot drift. */
  function shapeTeams(rosters, users) {
    var userById = {};
    (users || []).forEach(function (u) { userById[u.user_id] = u; });

    return (rosters || []).map(function (r) {
      var u = userById[r.owner_id] || {};
      return {
        roster_id: r.roster_id,
        owner_id: r.owner_id,
        username: u.display_name || ('Roster ' + r.roster_id),
        teamName: (u.metadata && u.metadata.team_name) || u.display_name || ('Roster ' + r.roster_id),
        avatar: u.avatar ? 'https://sleepercdn.com/avatars/thumbs/' + u.avatar : null,
        keepers: r.keepers || [],
      };
    }).sort(function (a, b) { return a.roster_id - b.roster_id; });
  }

  function loadLeague(leagueId) {
    return Promise.all([
      api('/league/' + leagueId),
      api('/league/' + leagueId + '/rosters'),
      api('/league/' + leagueId + '/users'),
      api('/league/' + leagueId + '/traded_picks'),
    ]).then(function (res) {
      var league = res[0], traded = res[3];
      var teams = shapeTeams(res[1], res[2]);

      // draft_id is on the league object; fall back to the drafts list.
      var draftId = league.draft_id;
      var draftP = draftId
        ? Promise.resolve(draftId)
        : api('/league/' + leagueId + '/drafts').then(function (d) {
            return d && d.length ? d[0].draft_id : null;
          });

      return draftP.then(function (id) {
        if (!id) throw new Error('This league has no draft yet.');
        return { league: league, teams: teams, tradedPicks: traded, draftId: id };
      });
    });
  }

  function loadDraft(draftId) {
    return api('/draft/' + draftId);
  }

  // The `_` param is ignored by Sleeper (verified) but keys the URL to the
  // current draft state, so caches only serve it while nothing has changed.
  function loadPicks(draftId, version) {
    return api('/draft/' + draftId + '/picks', version ? { _: version } : null);
  }

  /* ---------- poller ---------- */

  /* Self-rescheduling setTimeout, never setInterval: at a 15s cadence a slow
   * request would let setInterval stack overlapping fetches. */
  function createPoller(opts) {
    var draftId = opts.draftId;
    var onDraft = opts.onDraft || function () {};
    var onPicks = opts.onPicks || function () {};
    var onStatusChange = opts.onStatusChange || function () {};
    var onError = opts.onError || function () {};

    var timer = null;
    var stopped = true;
    var inFlight = false;
    var failures = 0;
    var lastPicked = null;
    var lastStatus = null;
    var lastPickCount = -1;

    function cadence(status) {
      var ms = C.POLL_MS[status];
      return ms == null ? C.POLL_MS.pre_draft : ms;
    }

    function schedule(ms) {
      if (stopped || !ms) return;
      clearTimeout(timer);
      timer = setTimeout(tick, ms);
    }

    function backoff() {
      failures++;
      var ms = Math.min(C.BACKOFF_START_MS * Math.pow(2, failures - 1), C.BACKOFF_MAX_MS);
      return Math.round(ms * (0.8 + Math.random() * 0.4)); // jitter
    }

    /* `force` is the manual path (a button, a tab coming back): it skips the
     * hidden-document guard, since the click IS the proof someone is looking.
     * Returns the round-trip so a caller can show a spinner for its lifetime;
     * errors are handled here, so the promise always resolves. */
    function tick(force) {
      if (stopped || inFlight) return Promise.resolve();
      if (!force && typeof document !== 'undefined' && document.hidden) return Promise.resolve();
      inFlight = true;

      return loadDraft(draftId).then(function (draft) {
        failures = 0;
        onDraft(draft);

        if (draft.status !== lastStatus) {
          var prev = lastStatus;
          lastStatus = draft.status;
          onStatusChange(prev, draft.status, draft);
        }

        // Only pay for the picks array when the heartbeat says something moved.
        var changed = draft.last_picked !== lastPicked || lastPickCount < 0;
        if (!changed) {
          inFlight = false;
          schedule(cadence(draft.status));
          return;
        }
        lastPicked = draft.last_picked;

        return loadPicks(draftId, draft.last_picked || draft.status).then(function (picks) {
          lastPickCount = picks.length;
          onPicks(picks, draft);
          inFlight = false;
          schedule(cadence(draft.status));
        });
      }).catch(function (err) {
        inFlight = false;
        onError(err, failures + 1);
        schedule(backoff());
      });
    }

    function start() {
      stopped = false;
      tick();
    }

    function stop() {
      stopped = true;
      clearTimeout(timer);
    }

    /* Clearing lastPicked is what makes this a *force*: the heartbeat's
     * "nothing moved, skip the 80 KB" shortcut can't fire, so the picks array
     * is always refetched and onPicks always runs. */
    function refreshNow() {
      lastPicked = null;
      clearTimeout(timer);
      inFlight = false;
      return tick(true);
    }

    function onVisible() {
      if (document.hidden) { clearTimeout(timer); }
      else if (!stopped) { refreshNow(); }
    }

    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', onVisible);
      global.addEventListener('online', function () { if (!stopped) refreshNow(); });
      // iOS Safari restores from bfcache without firing visibilitychange.
      global.addEventListener('pageshow', function (e) {
        if (e.persisted && !stopped) refreshNow();
      });
    }

    return { start: start, stop: stop, refreshNow: refreshNow };
  }

  global.OvenDraft = {
    api: api,
    pickNoFor: pickNoFor,
    buildPickPlan: buildPickPlan,
    computeClock: computeClock,
    roundPickLabel: roundPickLabel,
    shapeTeams: shapeTeams,
    loadLeague: loadLeague,
    loadDraft: loadDraft,
    loadPicks: loadPicks,
    createPoller: createPoller,
  };
})(window);
