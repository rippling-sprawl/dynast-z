/* Shared NFL schedule — the data, the row, and the three lists made of it.
 *
 * Extracted from /football/schedule, where it started, so that the team card on
 * /football/bakers-buns can show a team's season in place instead of linking
 * away to it. Styles live in styles/components/nfl-schedule.css; the week menu
 * and team grid the schedule page filters with are a separate component,
 * scripts/components/nfl-pickers.js.
 *
 * A consumer loads a season, then asks for one of the three lists:
 *
 *   schedLoad(2026).then(function (doc) {
 *     el.innerHTML = schedRenderSeason(doc, { team: 'CHI' });
 *   });
 *
 * The file in data/ is the fixture list and nothing else — it is committed, so
 * it cannot know a score or a line. A consumer that wants either asks for them
 * separately and hands them in as `opts.lines`:
 *
 *   schedLoadLines(2026).then(function (lines) {
 *     el.innerHTML = schedRenderWeek(doc, 2, { lines: lines });
 *   });
 *
 * Without it every row renders exactly as it did before lines existed, which
 * is what the team card on /football/bakers-buns still wants.
 *
 * Every render function returns an HTML string and touches no DOM and no state
 * of its own — the schedule page keeps its filters, the card keeps its tabs, and
 * neither has to know what the other does with a pick.
 *
 * Everything is ES5 globals, like the rest of scripts/ — no modules.
 */
(function (global) {
  'use strict';

  /* The seasons with a file in data/. Newest first: this is the order the
   * pickers render in, and the first entry is what a page opens on.
   *
   * The one place that knows. Adding a season means running
   * scripts/fetch_nfl_schedule.py --season N and adding N here. */
  var SEASONS = [2026, 2025];

  /* Served from this app, not hotlinked — the same 32 files the team picker and
   * the projected-standings table already use. */
  var LOGO_DIR = '/assets/icons/nfl/';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  /* ---------- loading ----------
   * One file per season, fetched at most once. Both consumers can ask for the
   * same season repeatedly — the card asks again every time a tab is clicked —
   * and the promise is what is cached, so two asks that overlap share a request
   * rather than racing.
   *
   * A failure is not cached: the entry is dropped so the next ask retries,
   * which is what a reader clicking the tab a second time means by it.
   */

  var docs = {};

  /* `reload`, not `no-cache` — the difference is load-bearing here.
   *
   * The ids in this file are what every game link on the page is built from,
   * and they have already changed identity once: the season moved from ESPN's
   * ids to balldontlie's, so a client holding the previous file links every
   * row to a game that no longer resolves.
   *
   * `no-cache` revalidates, and revalidation against Vercel is broken for our
   * purposes: it stamps EVERY static file with the same fixed
   * `Last-Modified: Sat, 20 Oct 2018 01:46:40 GMT` and sends no ETag. So the
   * conditional request asks "changed since 2018?", the origin compares that
   * to its own constant, answers 304, and the browser keeps the ESPN-era file
   * — with its freshness timer reset, forever. `reload` skips the conditional
   * request entirely and always takes the body. */
  function schedLoad(season) {
    if (docs[season]) return docs[season];
    docs[season] = fetch('/data/nfl_schedule_' + season + '.json',
                         { cache: 'reload' })
      .then(function (r) {
        if (!r.ok) throw new Error('schedule data unavailable (' + r.status + ')');
        return r.json();
      })
      .catch(function (e) {
        delete docs[season];
        throw e;
      });
    return docs[season];
  }

  /* ---------- the live half ----------
   * Everything the committed file cannot carry: which games have kicked off,
   * which have finished, what the score is, and what the spread and total are
   * right now. It comes from /api/game-odds, the same listing the live-stats
   * board and the schedule archive read, with `lines=1` for the two fields
   * only this page renders.
   *
   * One request per season, not per week: the page already has the whole season
   * in hand and switches weeks without touching the network, so a week-scoped
   * fetch would trade ~14 KB once for a request on every pick.
   *
   * A failure is an empty map, not an error. The schedule is the page; the
   * lines are what the page says about it, and a row with no line renders as
   * the fixture it always was rather than as a broken one.
   */

  var lines = {};

  function schedLoadLines(season) {
    if (lines[season]) return lines[season];
    lines[season] = fetch('/api/game-odds?season=' + encodeURIComponent(season) +
                          '&lines=1')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { return (d && d.games) || {}; })
      .catch(function () { return {}; });
    return lines[season];
  }

  /* pregame | live | final, for a game the caller may or may not have lines for.
   *
   * The API's phase is read off the game's own status_state and is the only
   * thing that knows a game is under way. Without it a score still settles the
   * question — data/nfl_schedule_2025.json ships all 272 of them — and a game
   * with neither has not been captured, which for a fixture list means it has
   * not happened yet. */
  function schedPhase(g, byId) {
    var info = byId && byId[g.id];
    if (info && info.phase) return info.phase;
    return g.score || (info && info.score) ? 'final' : 'pregame';
  }

  // Cached on the doc itself rather than in a map here: the doc is the identity,
  // and a consumer that hands over a doc from somewhere else still gets one.
  function schedTeamsByAbbr(doc) {
    if (!doc._byAbbr) {
      var by = {};
      (doc.teams || []).forEach(function (t) { by[t.abbr] = t; });
      doc._byAbbr = by;
    }
    return doc._byAbbr;
  }

  /* ---------- time ----------
   * Every kickoff in a file is a UTC instant; every label rendered here is US
   * Eastern, because that is the timezone the league schedules in and the one
   * the odd/regular split is defined against (see the fetch script). Rendering
   * in the viewer's own zone would put a "1:00 PM slate" game at 10:00 AM for a
   * west-coast reader and make the badges look wrong.
   *
   * The zone is read off the file rather than hardcoded, and the formatters
   * built for it are cached: constructing seven Intl.DateTimeFormats per row
   * would be the most expensive thing on a 272-row page.
   */

  var fmtCache = {};

  function formats(doc) {
    var tz = doc.timezone || 'America/New_York';
    if (fmtCache[tz]) return fmtCache[tz];

    function fmt(locale, opts) {
      opts.timeZone = tz;
      return new Intl.DateTimeFormat(locale, opts);
    }

    fmtCache[tz] = {
      time: fmt('en-US', { hour: 'numeric', minute: '2-digit' }),
      dayLong: fmt('en-US', { weekday: 'long', month: 'long', day: 'numeric' }),
      // The badge label for an odd game: "THU", "MON", "SUN".
      dayAbbr: fmt('en-US', { weekday: 'short' }),
      // The per-row date in any all-weeks list: "Sep 14".
      dayRow: fmt('en-US', { month: 'short', day: 'numeric' }),
      // en-CA yields YYYY-MM-DD, which is the calendar-day grouping key.
      dayKey: fmt('en-CA', { year: 'numeric', month: '2-digit', day: '2-digit' }),
      // 24-hour, for the slate boundary below. en-GB so the hour is plain "16"
      // rather than en-US's "16" plus a meridiem to strip.
      hour24: fmt('en-GB', { hour: '2-digit', hour12: false })
    };
    return fmtCache[tz];
  }

  function toDate(iso) {
    // "2026-09-10T00:20Z" — Safari parses this, but be explicit about the zone
    // rather than relying on it.
    return new Date(iso.replace(' ', 'T'));
  }

  // Morning in the file's zone, read off the same formatter that renders the
  // time cell so the badge and the time it sits next to can never disagree.
  function isMorning(f, d) {
    return f.time.formatToParts(d).some(function (p) {
      return p.type === 'dayPeriod' && /^a/i.test(p.value);
    });
  }

  // The time cell, without the meridiem: every kickoff that renders here is
  // "1:00" through "9:30" and every one of them is a 4-character string, so the
  // column is exactly as wide as its content and the AM/PM that used to follow
  // it said nothing — no NFL game kicks at 1:00 in the morning. The one genuine
  // morning slot, the 9:30 international, is the case the SUN A.M. badge exists
  // to mark.
  function timeLabel(f, d) {
    return f.time.formatToParts(d).filter(function (p) {
      return p.type !== 'dayPeriod' && !(p.type === 'literal' && p.value !== ':');
    }).map(function (p) { return p.value; }).join('');
  }

  function hour(f, d) { return Number(f.hour24.format(d)); }

  /* The Sunday slate break. The early games all kick at 1:00 and the late ones
   * at 4:05/4:25, and they are two separate blocks of the afternoon rather than
   * one continuous run of rows — the rule is drawn at 4:00, between the last of
   * the early games and the first of the late ones. Same calendar day only, so
   * it never fires across a day or week boundary in the all-weeks lists. */
  function isSlateBreak(f, prev, cur) {
    return !!prev && f.dayKey.format(prev) === f.dayKey.format(cur) &&
      hour(f, prev) < 16 && hour(f, cur) >= 16;
  }

  /* ---------- which week is it right now? ----------
   * The file ships each week's window as [start, end) in UTC: midnight local on
   * the day of that week's first game, to midnight after its last. The windows
   * never overlap and the only uncovered days are Tuesdays, so the first week
   * that has not yet ended is unambiguously "now" — including during a Tuesday,
   * when it correctly reads as the week about to start.
   *
   * Before the season that is week 1. After the last game it falls through to
   * week 18 rather than to nothing, which is also what a finished season gives
   * for any `now` — see how the schedule page picks a default for a past season.
   */
  function schedCurrentWeek(doc, now) {
    now = now || new Date();
    for (var i = 0; i < doc.weeks.length; i++) {
      if (now < toDate(doc.weeks[i].end)) return doc.weeks[i].week;
    }
    return doc.weeks[doc.weeks.length - 1].week;
  }

  function matches(g, team) {
    return !team || g.away === team || g.home === team;
  }

  /* ---------- the row ----------
   * One game, one line. `opts` adds leading columns for the lists that need
   * them: `week` for a team's season, where the week number is the only ordering
   * the reader has, and `date` for any all-weeks list, where the rows are no
   * longer under a day header that says which day it is. `day` is the same cell
   * inside a single week — "Sun" rather than "Sep 20", because within one week
   * the weekday is the whole of what the date says and three characters of it
   * is width the market beside it needs. `team` is the picked team, which
   * decides which side is highlighted and whose side a result is read from.
   */
  function gameRow(doc, g, opts) {
    opts = opts || {};
    var f = formats(doc);
    var by = schedTeamsByAbbr(doc);
    var d = toDate(g.kickoff);
    var tbd = g.slot === 'tbd';
    var away = by[g.away] || { abbr: g.away };
    var home = by[g.home] || { abbr: g.home };
    var info = (opts.lines || {})[g.id];
    var phase = schedPhase(g, opts.lines);

    // The picked-team highlight says which side of a home/away pairing is
    // "yours". A neutral-site game has no such pairing — neither team is at
    // home — so the row carries the venue instead and no side is colored.
    function team(t, side) {
      var picked = !g.neutral && opts.team === t.abbr;
      // The abbreviation gets its own fixed-width span so that the logo column
      // and the letters column each line up down the page. Putting the image
      // straight into the cell would right-align "NE" and "WSH" to the same
      // edge and leave their logos two characters apart.
      //
      // loading="lazy" is not decoration: the all-weeks list is 272 rows, so
      // 544 logos, and only a screenful is ever visible.
      return '<span class="sched-team ' + side + (picked ? ' is-picked' : '') +
        '" title="' + esc(t.name || t.abbr) + '">' +
        '<img class="sched-logo" src="' + LOGO_DIR + esc(t.abbr) +
          '.svg" alt="" aria-hidden="true" loading="lazy">' +
        '<span class="sched-abbr">' + esc(t.abbr) + '</span></span>';
    }

    // A neutral-site game has no true home team, so "@" would be a lie and the
    // venue is the whole point of the row — it's the only case where the stadium
    // earns its space in a condensed list.
    var sep = g.neutral ? 'vs' : '@';

    // The whole row is the link. Every row gets one — 272 of them a season — so
    // a separate "odds" affordance per row would be 272 pieces of furniture for
    // a page whose whole design is that only exceptions get a marker. The row
    // costs no width, no badge and no column: it looks exactly as it did, and
    // the target is the whole line rather than the three characters of an
    // abbreviation — which is what the row already highlights on hover.
    //
    // g.id is balldontlie's game id since the schedule moved to that source,
    // and it is the last segment of the game page's URL. A row without one
    // still renders as a plain <div> — the id is not load-bearing for anything
    // else here.
    var teams = '<span class="sched-teams">' + team(away, 'away') +
      '<span class="sched-at">' + sep + '</span>' + team(home, 'home') + '</span>';

    /* The same slot in the row, two states, never both. Before the whistle the
     * market is the news and there is no score to tell; after it the score is
     * the news and the line it was played to is history — a settled game still
     * quoting a spread invites the reader to price a game that has already been
     * played. The one page that does keep both is the game's own, which is
     * where a closing line belongs. */
    var state = phase === 'final'
      ? resultCell(g, opts.team, info && info.score)
      : marketCell(info && info.line, home);
    var venue = g.neutral && g.venue
      ? '<span class="sched-venue">' + esc(g.venue) + '</span>' : '';

    // Only the exceptions are labelled, and only where the exception is news.
    //
    // The label is the day the game is played, which is what makes the game odd
    // in the first place. Sunday is the exception that needs a second word: the
    // odd Sundays are the morning international kickoffs and the night game, so
    // "SUN" alone would not say which — hence "SUN A.M." on the morning ones.
    // The night games keep a bare "SUN"; their time cell already reads 8:20 PM.
    //
    // A list of every team already says the day, three times over: the week
    // view groups under "Thursday, September 17", the status-sorted week puts
    // the weekday in front of the time, and the all-weeks list dates every row.
    // Against all of that the badge is a third telling of a fact the reader has
    // not asked about — sixty-seven pills down a season, each one saying what
    // the header above it just said. It is news in one place only: a single
    // team's list, where seventeen rows are seventeen different weeks and "this
    // one is a Thursday night" is a thing about the game rather than about
    // where it sits on the page. So it is drawn when a team is picked and
    // nowhere else.
    //
    // TBD is not one of these and is never dropped: it does not name a day, it
    // says the kickoff time is not set — which is why the time cell beside it
    // reads "TBD" rather than an hour — and no header anywhere says that.
    var badge = '';
    if (g.slot === 'odd') {
      if (opts.team) {
        var day = f.dayAbbr.format(d);
        badge = '<span class="sched-slot odd">' +
          esc(day + (day === 'Sun' && isMorning(f, d) ? ' a.m.' : '')) + '</span>';
      }
    } else if (g.slot !== 'regular') {
      badge = '<span class="sched-slot ' + g.slot + '">' + g.slot + '</span>';
    }

    // The one badge that is not about which day the game is on, and it leads
    // the row's badges because it is the only one that is about right now. It
    // has to exist: in the lists that keep their day and week headers a live
    // game sits in the middle of them, and nothing else on the row says so.
    // The status-sorted week suppresses it — there the group header does say so.
    var live = phase === 'live' && !opts.hideLive
      ? '<span class="sched-slot live">live</span>' : '';

    // A TBD game still has a known calendar day — only the kickoff time is
    // unset — so the date cell is real even where the time cell isn't.
    var cls = 'sched-game' + (tbd ? ' is-tbd' : '') +
      (opts.week ? ' has-week' : '') + (opts.date ? ' has-date' : '') +
      (opts.day ? ' has-day' : '') +
      (opts.slateBreak ? ' is-slate-break' : '');
    var open = g.id
      ? '<a class="' + cls + '" href="/football/schedule/game/' +
          encodeURIComponent(g.id) + '" title="Odds and box score: ' +
          esc(away.abbr + ' ' + sep + ' ' + home.abbr) + '">'
      : '<div class="' + cls + '">';
    return open +
      (opts.week ? '<span class="sched-wk">' + esc(opts.week) + '</span>' : '') +
      (opts.date ? '<span class="sched-date">' + esc(f.dayRow.format(d)) + '</span>' : '') +
      (opts.day ? '<span class="sched-date">' + esc(f.dayAbbr.format(d)) + '</span>' : '') +
      '<span class="sched-time">' + (tbd ? 'TBD' : esc(timeLabel(f, d))) + '</span>' +
      '<span class="sched-matchup">' + teams +
        state + live + badge + venue + '</span>' +
    (g.id ? '</a>' : '</div>');
  }

  /* The final score, on the seasons that have one. `score` is [away, home], the
   * order the matchup beside it reads in.
   *
   * With a team picked the row is that team's season, so the score is written
   * from their side and led by the verdict — seventeen rows of "24-20" leave the
   * reader working out which number was theirs on every one of them. With no
   * team picked there is no side to be on, so it stays a bare score. */
  function resultCell(g, team, score) {
    // The file first, then the one handed in: a committed score belongs to a
    // season that has been archived and is the copy that will still be right
    // in five years. Where both exist they agree; where only the API has one
    // the season is the one being played.
    score = g.score || score;
    if (!score) return '';
    var a = score[0], h = score[1];

    if (team !== g.away && team !== g.home) {
      return '<span class="sched-result">' + a + '-' + h + '</span>';
    }

    var us = team === g.home ? h : a;
    var them = team === g.home ? a : h;
    var cls = us > them ? 'is-w' : (us < them ? 'is-l' : 'is-t');
    var verdict = us > them ? 'W' : (us < them ? 'L' : 'T');
    return '<span class="sched-result ' + cls + '">' + verdict + ' ' +
      us + '-' + them + '</span>';
  }

  /* The spread and the total, on a game that has not finished.
   *
   * The spread is the home team's, signed — "−6.5" is the home side laying it,
   * "+3.5" is the home side getting it. That is how a book quotes a game and
   * how pickem_games stores it, and the row is built to be read that way: the
   * home team is the one the number sits next to, always the second of the two
   * and always the one the "@" points at.
   *
   * The minus is U+2212, not a hyphen, for the reason the pick 'em board uses
   * it: at monospace it is the width of a digit and sits on the same optical
   * line, where a hyphen reads as a bullet in front of the number.
   *
   * The total is the bare line. No "o"/"u" prefix — that names a side of a bet,
   * and there is no price here to take it at; the game's own page is where the
   * two halves of the market are priced.
   */
  function marketCell(line, home) {
    if (!line) return '';
    var spread = line.spread, total = line.total;
    var label = '';
    if (spread === 0) {
      label = 'PK';
    } else if (spread !== null && spread !== undefined) {
      label = (spread < 0 ? '\u2212' : '+') + Math.abs(spread);
    }
    if (!label && (total === null || total === undefined)) return '';

    // One title for the pair, because they are one book's quote of one game and
    // the provenance is the same fact about both. It is also where the team the
    // spread belongs to is named: the cell has no room for three more
    // characters, and hovering is the reader asking which side it is.
    var book = BOOK_NAMES[line.book] || line.book || 'the market';
    return '<span class="sched-market" title="' + esc(book + ': ' +
        (label ? home.abbr + ' ' + label.replace('\u2212', '-')
               : 'no spread posted') +
        (total === null || total === undefined ? '' : ', total ' + total)) + '">' +
      '<span class="sched-spread">' + esc(label) + '</span>' +
      '<span class="sched-total">' +
        (total === null || total === undefined ? '' : esc(total)) +
      '</span></span>';
  }

  /* Book slugs as a person names them, for the market cell's tooltip. The same
   * map the game page carries; only the books a bundle can hold are listed,
   * and an unmapped slug falls through to itself rather than to nothing. */
  var BOOK_NAMES = {
    draftkings: 'DraftKings', fanduel: 'FanDuel', betmgm: 'BetMGM',
    caesars: 'Caesars', betrivers: 'BetRivers', fanatics: 'Fanatics',
    espnbet: 'ESPN BET', bet365: 'bet365', pointsbet: 'PointsBet',
    hardrock: 'Hard Rock Bet'
  };

  /* ---------- per-team links ----------
   * Pro-Football-Reference keys teams by their own three-letter code, which
   * predates several relocations and rebrands and so disagrees with the league's
   * abbreviation on a third of the league — the Cardinals are still "crd", the
   * Chargers still "sdg". Only the codes that differ are listed; everything else
   * is the lowercased abbreviation. */
  var PFR_CODES = {
    ARI: 'crd', BAL: 'rav', GB: 'gnb', HOU: 'htx', IND: 'clt', KC: 'kan',
    LAC: 'sdg', LAR: 'ram', LV: 'rai', NE: 'nwe', NO: 'nor', SF: 'sfo',
    TB: 'tam', TEN: 'oti', WSH: 'was'
  };

  // The season the file is for, which is the year PFR files these games under —
  // not the calendar year, which is the wrong one for every January game and for
  // the whole offseason.
  function schedTeamLinks(doc, abbr) {
    var t = schedTeamsByAbbr(doc)[abbr] || { abbr: abbr };
    var pfr = PFR_CODES[abbr] || abbr.toLowerCase();
    var links = [
      { label: 'Pro-Football-Reference',
        href: 'https://www.pro-football-reference.com/teams/' + pfr + '/' +
          doc.season + '.htm' }
    ];
    return '<div class="sched-links">' +
      '<span class="sched-links-label">' + esc(t.name || abbr) + '</span>' +
      links.map(function (l) {
        return '<a href="' + esc(l.href) + '" target="_blank" rel="noopener">' +
          esc(l.label) + '</a>';
      }).join('') +
      '</div>';
  }

  function groupHeader(title, sub) {
    return '<div class="sched-group"><h3>' + esc(title) + '</h3>' +
      (sub ? '<span class="sched-group-sub">' + esc(sub) + '</span>' : '') + '</div>';
  }

  /* ---------- the three lists ---------- */

  /* ---------- a week in flight ----------
   * A week that is part-played is not read the way a week that is coming up is.
   * Thursday / Sunday / Monday is the right shape for a slate nobody has
   * kicked off yet — it answers "when is this on" — but once the games start
   * it answers a question nobody is asking, and it buries the one game that is
   * actually happening halfway down a page of results and fixtures.
   *
   * So for as long as a week is in flight the day headers give way to the three
   * states a game can be in: what is on now, what is still to come, then what
   * has already happened, newest first — a reader coming back at 8pm on a
   * Sunday wants the 4:25 results, not the 1:00 ones. Every row carries its own
   * weekday, since the header no longer says it, and the weekday is all a row
   * inside one week has to say.
   *
   * "In flight" is deliberately narrower than "not all final": a week where
   * nothing has kicked off yet is every future week on the calendar, and
   * flattening those into one "Scheduled" list would throw away the day
   * grouping for no gain. It takes a game that has started — live or final —
   * *and* a game that has not finished. The moment the last whistle blows the
   * week is chronological again and reads exactly as the 2025 archive does.
   */

  var PHASE_ORDER = ['live', 'pregame', 'final'];
  var PHASE_LABEL = { live: 'In progress', pregame: 'Scheduled', final: 'Final' };

  function inFlight(games, byId) {
    var started = false, unfinished = false;
    games.forEach(function (g) {
      var p = schedPhase(g, byId);
      if (p !== 'pregame') started = true;
      if (p !== 'final') unfinished = true;
    });
    return started && unfinished;
  }

  function statusList(doc, games, opts) {
    var buckets = { live: [], pregame: [], final: [] };
    games.forEach(function (g) { buckets[schedPhase(g, opts.lines)].push(g); });

    return PHASE_ORDER.map(function (phase) {
      var rows = buckets[phase];
      if (!rows.length) return '';
      // Chronological within a bucket, except the finished one — a result is
      // worth reading in the order the results came in.
      rows.sort(function (a, b) {
        var ka = toDate(a.kickoff), kb = toDate(b.kickoff);
        return phase === 'final' ? kb - ka : ka - kb;
      });
      return groupHeader(PHASE_LABEL[phase],
          rows.length + ' game' + (rows.length === 1 ? '' : 's')) +
        '<div class="sched-rows">' +
        rows.map(function (g) {
          // No live badge in here: the header this row is under is the badge,
          // and stamping every row in a group with what the group is called is
          // width spent saying it twice.
          return gameRow(doc, g, { team: opts.team, lines: opts.lines,
                                   day: true, hideLive: true });
        }).join('') + '</div>';
    }).join('');
  }

  // One week: group by calendar day, so a week reads Thu / Sun / Mon — unless
  // the week is part-played, which statusList above re-orders instead.
  function schedRenderWeek(doc, week, opts) {
    opts = opts || {};
    var f = formats(doc);
    var wk = doc.weeks.filter(function (w) { return w.week === week; })[0];
    if (!wk) return '<p class="sched-empty">No week ' + esc(week) + '.</p>';

    var games = wk.games.filter(function (g) { return matches(g, opts.team); });
    if (!games.length) {
      return '<p class="sched-empty">' + (opts.team
        ? esc((schedTeamsByAbbr(doc)[opts.team] || {}).name || opts.team) +
          ' are on bye in week ' + wk.week + '.'
        : 'No games in week ' + wk.week + '.') + '</p>';
    }

    if (inFlight(games, opts.lines)) return statusList(doc, games, opts);
    // Rows are wrapped per day so the zebra striping restarts with each group —
    // counted across the whole list, the headers are siblings too and the
    // stripes land on arbitrary rows.
    var html = '', lastKey = null, prev = null;
    games.forEach(function (g) {
      var d = toDate(g.kickoff);
      var key = f.dayKey.format(d);
      if (key !== lastKey) {
        if (lastKey !== null) html += '</div>';
        html += groupHeader(f.dayLong.format(d)) + '<div class="sched-rows">';
        lastKey = key;
      }
      html += gameRow(doc, g, { team: opts.team, lines: opts.lines,
                                slateBreak: isSlateBreak(f, prev, d) });
      prev = d;
    });
    return html + '</div>';
  }

  // A team across all weeks — one game a week, so eighteen week headers would be
  // eighteen headers over eighteen rows. The week number becomes a column
  // instead and the whole season renders as one uninterrupted block, at the same
  // density as a single week of the all-teams view. Byes are rows rather than
  // omissions: a missing week 7 would otherwise read as a data gap.
  function schedRenderSeason(doc, opts) {
    opts = opts || {};
    var rows = doc.weeks.map(function (wk) {
      var g = wk.games.filter(function (x) { return matches(x, opts.team); })[0];
      return g
        ? gameRow(doc, g, { team: opts.team, lines: opts.lines,
                            week: wk.week, date: true })
        : '<div class="sched-game sched-bye has-week has-date">' +
            '<span class="sched-wk">' + wk.week + '</span>' +
            '<span class="sched-date">&mdash;</span><span class="sched-time"></span>' +
            '<span class="sched-matchup">Bye week</span></div>';
    }).join('');
    return '<div class="sched-rows">' + rows + '</div>';
  }

  // All weeks, all teams: still grouped by week, because 272 rows need the
  // breaks. Each row carries its own date — the week's date range said less than
  // the day the game is actually on.
  function schedRenderAll(doc, opts) {
    opts = opts || {};
    if (opts.team) return schedRenderSeason(doc, opts);
    var f = formats(doc);
    return doc.weeks.map(function (wk) {
      if (!wk.games.length) return '';
      var prev = null;
      return groupHeader('Week ' + wk.week) + '<div class="sched-rows">' +
        wk.games.map(function (g) {
          var d = toDate(g.kickoff);
          var row = gameRow(doc, g, { date: true, lines: opts.lines,
                                      slateBreak: isSlateBreak(f, prev, d) });
          prev = d;
          return row;
        }).join('') + '</div>';
    }).join('');
  }

  /* Drops the memo so the next schedLoad goes back to the network. The memo is
   * per-page-load state and normally right to keep; the exception is a page
   * that was restored rather than loaded, where "since the page loaded" can
   * mean days ago. */
  function schedInvalidate() {
    docs = {};
    lines = {};
  }

  /* The lines alone. The fixture list is committed and a reader who has had the
   * page open for an hour is holding a correct copy of it; what has moved in
   * that hour is which games are under way, what they are, and what the market
   * is — so a page that wants to catch up drops this half and keeps the 35 KB
   * it already has. */
  function schedInvalidateLines() {
    lines = {};
  }

  global.SCHED_SEASONS = SEASONS;
  global.SCHED_CURRENT_SEASON = SEASONS[0];
  global.schedLoad = schedLoad;
  global.schedLoadLines = schedLoadLines;
  global.schedPhase = schedPhase;
  global.schedInvalidate = schedInvalidate;
  global.schedInvalidateLines = schedInvalidateLines;
  global.schedTeamsByAbbr = schedTeamsByAbbr;
  global.schedCurrentWeek = schedCurrentWeek;
  global.schedRenderWeek = schedRenderWeek;
  global.schedRenderSeason = schedRenderSeason;
  global.schedRenderAll = schedRenderAll;
  global.schedTeamLinks = schedTeamLinks;
})(window);
