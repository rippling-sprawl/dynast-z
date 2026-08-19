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

  function schedLoad(season) {
    if (docs[season]) return docs[season];
    docs[season] = fetch('/data/nfl_schedule_' + season + '.json')
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
   * longer under a day header that says which day it is. `team` is the picked
   * team, which decides which side is highlighted and whose side a result is
   * read from.
   */
  function gameRow(doc, g, opts) {
    opts = opts || {};
    var f = formats(doc);
    var by = schedTeamsByAbbr(doc);
    var d = toDate(g.kickoff);
    var tbd = g.slot === 'tbd';
    var away = by[g.away] || { abbr: g.away };
    var home = by[g.home] || { abbr: g.home };

    // The picked-team highlight says which side of a home/away pairing is
    // "yours". A neutral-site game has no such pairing — neither team is at
    // home — so the row carries the venue instead and no side is colored.
    function team(t, side) {
      var picked = !g.neutral && opts.team === t.abbr;
      return '<span class="sched-team ' + side + (picked ? ' is-picked' : '') +
        '" title="' + esc(t.name || t.abbr) + '">' + esc(t.abbr) + '</span>';
    }

    // A neutral-site game has no true home team, so "@" would be a lie and the
    // venue is the whole point of the row — it's the only case where the stadium
    // earns its space in a condensed list.
    var sep = g.neutral ? 'vs' : '@';
    var venue = g.neutral && g.venue
      ? '<span class="sched-venue">' + esc(g.venue) + '</span>' : '';

    // Only the exceptions are labelled. A regular Sunday-afternoon game is the
    // default case on 181 of 272 rows, and stamping every one of them "regular"
    // would bury the ~67 that are actually worth noticing — the badge means
    // something precisely because most rows don't have one.
    //
    // The label is the day the game is played, which is what makes the game odd
    // in the first place. Sunday is the exception that needs a second word: the
    // odd Sundays are the morning international kickoffs and the night game, so
    // "SUN" alone would not say which — hence "SUN A.M." on the morning ones.
    // The night games keep a bare "SUN"; their time cell already reads 8:20 PM.
    var badge = '';
    if (g.slot === 'odd') {
      var day = f.dayAbbr.format(d);
      badge = '<span class="sched-slot odd">' +
        esc(day + (day === 'Sun' && isMorning(f, d) ? ' a.m.' : '')) + '</span>';
    } else if (g.slot !== 'regular') {
      badge = '<span class="sched-slot ' + g.slot + '">' + g.slot + '</span>';
    }

    // A TBD game still has a known calendar day — only the kickoff time is
    // unset — so the date cell is real even where the time cell isn't.
    return '<div class="sched-game' + (tbd ? ' is-tbd' : '') +
        (opts.week ? ' has-week' : '') + (opts.date ? ' has-date' : '') +
        (opts.slateBreak ? ' is-slate-break' : '') + '">' +
      (opts.week ? '<span class="sched-wk">' + esc(opts.week) + '</span>' : '') +
      (opts.date ? '<span class="sched-date">' + esc(f.dayRow.format(d)) + '</span>' : '') +
      '<span class="sched-time">' + (tbd ? 'TBD' : esc(timeLabel(f, d))) + '</span>' +
      '<span class="sched-matchup">' +
        '<span class="sched-teams">' + team(away, 'away') +
          '<span class="sched-at">' + sep + '</span>' + team(home, 'home') + '</span>' +
        resultCell(g, opts.team) + badge + venue + '</span>' +
    '</div>';
  }

  /* The final score, on the seasons that have one. `score` is [away, home], the
   * order the matchup beside it reads in.
   *
   * With a team picked the row is that team's season, so the score is written
   * from their side and led by the verdict — seventeen rows of "24-20" leave the
   * reader working out which number was theirs on every one of them. With no
   * team picked there is no side to be on, so it stays a bare score. */
  function resultCell(g, team) {
    if (!g.score) return '';
    var a = g.score[0], h = g.score[1];

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

  // One week: group by calendar day, so a week reads Thu / Sun / Mon.
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
      html += gameRow(doc, g, { team: opts.team, slateBreak: isSlateBreak(f, prev, d) });
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
        ? gameRow(doc, g, { team: opts.team, week: wk.week, date: true })
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
          var row = gameRow(doc, g, { date: true, slateBreak: isSlateBreak(f, prev, d) });
          prev = d;
          return row;
        }).join('') + '</div>';
    }).join('');
  }

  global.SCHED_SEASONS = SEASONS;
  global.SCHED_CURRENT_SEASON = SEASONS[0];
  global.schedLoad = schedLoad;
  global.schedTeamsByAbbr = schedTeamsByAbbr;
  global.schedCurrentWeek = schedCurrentWeek;
  global.schedRenderWeek = schedRenderWeek;
  global.schedRenderSeason = schedRenderSeason;
  global.schedRenderAll = schedRenderAll;
  global.schedTeamLinks = schedTeamLinks;
})(window);
