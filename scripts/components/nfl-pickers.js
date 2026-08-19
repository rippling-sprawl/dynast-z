/* Shared NFL pickers — the week menu and the team grid.
 *
 * Extracted from /football/schedule, where they started, so that
 * /football/bakers-buns can file a note against the same team and the same week
 * the schedule filters by. Styles live in styles/components/nfl-pickers.css.
 *
 * The markup a consumer supplies is the contract:
 *
 *   <div class="dd-row">
 *     <div class="dd" id="dd-week">
 *       <button class="dd-btn" aria-haspopup="true" aria-expanded="false">
 *         <span class="dd-value">All weeks</span>
 *       </button>
 *       <div class="dd-pop dd-menu" role="menu" aria-label="Week" hidden></div>
 *     </div>
 *     <div class="dd" id="dd-team">
 *       <button class="dd-btn" aria-haspopup="dialog" aria-expanded="false">
 *         <span class="dd-value">All teams</span>
 *       </button>
 *       <div class="dd-pop dd-overlay" role="dialog" aria-modal="true" hidden>
 *         <div class="tp"></div>
 *       </div>
 *     </div>
 *   </div>
 *
 * Panels are filled by buildWeekMenu / buildTeamPicker, opened and closed by
 * registerDropdown, and kept in step with the consumer's own state by
 * syncWeekMenu / syncTeamPicker. Selection handling stays with the consumer:
 * the schedule toggles a filter, the notes modal sets a field, and the two want
 * different things to happen on a pick.
 *
 * Everything is ES5 globals, like the rest of scripts/ — no modules.
 */
(function (global) {
  'use strict';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  /* The league, in the shape it is actually organised in. A feed ships teams as
   * one flat alphabetical list, and alphabetical is the one ordering nobody
   * thinks about football in — a reader looking for the Bears looks in the NFC
   * North, not between Atlanta and Cincinnati. Realignment has happened once
   * since 2002, so a static map is the right home for it; the abbreviations are
   * the feeds' own, which is also how the logo files are named. */
  var NFL_CONFERENCES = [
    { name: 'AFC', divisions: [
      { name: 'East',  teams: ['BUF', 'MIA', 'NE', 'NYJ'] },
      { name: 'North', teams: ['BAL', 'CIN', 'CLE', 'PIT'] },
      { name: 'South', teams: ['HOU', 'IND', 'JAX', 'TEN'] },
      { name: 'West',  teams: ['DEN', 'KC', 'LAC', 'LV'] }
    ] },
    { name: 'NFC', divisions: [
      { name: 'East',  teams: ['DAL', 'NYG', 'PHI', 'WSH'] },
      { name: 'North', teams: ['CHI', 'DET', 'GB', 'MIN'] },
      { name: 'South', teams: ['ATL', 'CAR', 'NO', 'TB'] },
      { name: 'West',  teams: ['ARI', 'LAR', 'SEA', 'SF'] }
    ] }
  ];

  // The two feeds name a team differently — the schedule ships `name`, the
  // projections ship `team` — so read both rather than making either rename.
  function teamName(t) {
    if (!t) return '';
    return t.name || t.team || t.abbr || '';
  }

  function teamMap(teams) {
    var by = {};
    (teams || []).forEach(function (t) { if (t && t.abbr) by[t.abbr] = t; });
    return by;
  }

  /* ---------- open / shut ----------
   * Two filters, one control. The triggers are identical — same box, same
   * caret, same behaviour — and only what opens underneath differs: a list of
   * weeks on one, the league's logos on the other. The week list could have
   * stayed a native <select>, but a native select cannot be made to match a
   * custom trigger across browsers, and "these are the two filters" is the
   * thing the row has to say first. */

  var dropdowns = [];

  /* The team grid opens as an overlay rather than as a panel hanging off its
   * trigger — thirty-two logos is a lightbox-sized thing, not a menu-sized
   * one, and anchored under the button it would either shove the page down or
   * run off the bottom of a phone. Same treatment as the image viewer on
   * /football: centerd over a dimmed page, with the body pinned underneath so
   * iOS doesn't scroll it behind the overlay. body.lightbox-open and its
   * scroll restore come from lightbox.css. */
  var scrollY = 0;

  function lockScroll() {
    scrollY = window.scrollY || window.pageYOffset || 0;
    document.body.style.top = -scrollY + 'px';
    document.body.classList.add('lightbox-open');
  }

  function unlockScroll() {
    if (!document.body.classList.contains('lightbox-open')) return;
    document.body.classList.remove('lightbox-open');
    document.body.style.top = '';
    window.scrollTo(0, scrollY);
  }

  function closeDropdown(dd, refocus) {
    if (!dd || dd.panel.hidden) return;
    dd.panel.hidden = true;
    dd.btn.setAttribute('aria-expanded', 'false');
    if (dd.modal) unlockScroll();
    if (refocus) dd.btn.focus();
  }

  function closeAllDropdowns() {
    dropdowns.forEach(function (d) { closeDropdown(d, false); });
  }

  // Whether anything is open right now. A consumer inside a <dialog> needs this
  // to know that an Escape was meant for the picker rather than for the dialog.
  function anyDropdownOpen() {
    return dropdowns.some(function (d) { return !d.panel.hidden; });
  }

  function openDropdown(dd) {
    dropdowns.forEach(function (d) { if (d !== dd) closeDropdown(d, false); });
    dd.panel.hidden = false;
    dd.btn.setAttribute('aria-expanded', 'true');
    if (dd.modal) lockScroll();
    // Opening lands on the current choice, so the keyboard starts where the
    // filter already is rather than at the top of a list of nineteen weeks.
    var here = dd.panel.querySelector('.is-on') || dd.panel.querySelector('button');
    if (here) here.focus();
  }

  // Arrows walk the panel in DOM order. That is exactly right for the week
  // list, and for the team grid it reads across each division and on to the
  // next — the same path the eye takes.
  var ARROW = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 };

  function registerDropdown(root) {
    var dd = {
      root: root,
      btn: root.querySelector('.dd-btn'),
      panel: root.querySelector('.dd-pop')
    };
    dd.modal = dd.panel.classList.contains('dd-overlay');
    dropdowns.push(dd);

    dd.btn.addEventListener('click', function (e) {
      e.stopPropagation();
      if (dd.panel.hidden) openDropdown(dd); else closeDropdown(dd, true);
    });

    // The dimmed backdrop is the overlay itself; anything landing on it
    // rather than on the grid is a click outside, which closes.
    if (dd.modal) {
      dd.panel.addEventListener('click', function (e) {
        if (e.target === dd.panel) closeDropdown(dd, true);
      });
    }

    dd.panel.addEventListener('keydown', function (e) {
      var items, i;
      // A modal keeps the keyboard inside it while it is open.
      if (dd.modal && e.key === 'Tab') {
        e.preventDefault();
        items = [].slice.call(dd.panel.querySelectorAll('button'));
        i = items.indexOf(document.activeElement);
        items[(i + (e.shiftKey ? -1 : 1) + items.length) % items.length].focus();
        return;
      }
      var step = ARROW[e.key];
      if (!step) return;
      e.preventDefault();
      items = [].slice.call(dd.panel.querySelectorAll('button'));
      i = items.indexOf(document.activeElement);
      var next = items[(i + step + items.length) % items.length];
      if (next) next.focus();
    });

    return dd;
  }

  document.addEventListener('click', function (e) {
    if (!e.target.closest || !e.target.closest('.dd')) closeAllDropdowns();
  });

  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    dropdowns.forEach(function (d) { closeDropdown(d, true); });
  });

  /* ---------- the team grid ---------- */

  // One team: the logo, with the full name as both the accessible name and the
  // tooltip. The logos are served from this app rather than hotlinked from
  // nfl.com, so the picker cannot break when they reorganise their CDN — see
  // assets/icons/nfl/.
  function teamButton(abbr, byAbbr) {
    var name = teamName(byAbbr[abbr]) || abbr;
    return '<button type="button" class="tp-team" data-team="' + esc(abbr) + '"' +
      ' aria-pressed="false" title="' + esc(name) + '">' +
      '<img src="/assets/icons/nfl/' + esc(abbr) + '.svg" alt="' + esc(name) + '">' +
      '</button>';
  }

  /* Fill a `.tp` grid with the league.
   *
   *   grid   the .tp element
   *   teams  [{ abbr, name|team }] — the feed's own list
   *   opts   { anyLabel } adds a full-width "no team" choice (data-team="") for
   *          a picker where no team is a real answer rather than the absence of
   *          one. The schedule passes none: there, un-picking is re-tapping.
   */
  function buildTeamPicker(grid, teams, opts) {
    opts = opts || {};
    var byAbbr = teamMap(teams);

    // Any team the feed knows about that the division map doesn't — a
    // relocation, or a changed abbreviation upstream — still gets a button,
    // because a team silently missing from the picker is also a team that
    // cannot be picked at all.
    var placed = {};
    var html = NFL_CONFERENCES.map(function (conf) {
      return '<div class="tp-conf"><h3 class="tp-conf-name">' + esc(conf.name) + '</h3>' +
        conf.divisions.map(function (div) {
          return '<div class="tp-div"><span class="tp-div-name">' + esc(div.name) + '</span>' +
            '<div class="tp-teams">' + div.teams.map(function (abbr) {
              placed[abbr] = true;
              return teamButton(abbr, byAbbr);
            }).join('') + '</div></div>';
        }).join('') + '</div>';
    }).join('');

    var stray = (teams || []).filter(function (t) { return t.abbr && !placed[t.abbr]; });
    if (stray.length) {
      html += '<div class="tp-conf tp-stray"><h3 class="tp-conf-name">Other</h3>' +
        '<div class="tp-div"><div class="tp-teams">' +
        stray.map(function (t) { return teamButton(t.abbr, byAbbr); }).join('') +
        '</div></div></div>';
    }

    if (opts.anyLabel) {
      html = '<button type="button" class="tp-any" data-team="" aria-pressed="false">' +
        esc(opts.anyLabel) + '</button>' + html;
    }

    grid.innerHTML = html;
  }

  /* The trigger says what the picker is currently set to — it is the only place
   * that reads once the panel is shut. The team one carries the logo as well as
   * the name, so the closed control still shows the same thing the open grid
   * does. With a pick made, everything else steps back so the one selected logo
   * is the only thing at full strength. */
  function syncTeamPicker(btn, grid, team, teams, opts) {
    opts = opts || {};
    var byAbbr = teamMap(teams);
    var t = team ? (byAbbr[team] || { abbr: team }) : null;

    btn.querySelector('.dd-value').innerHTML = t
      ? '<img class="dd-logo" src="/assets/icons/nfl/' + esc(t.abbr) + '.svg" alt="">' +
        esc(teamName(t) || t.abbr)
      : esc(opts.emptyLabel || 'All teams');

    grid.classList.toggle('has-pick', !!team);
    var btns = grid.querySelectorAll('.tp-team, .tp-any');
    for (var i = 0; i < btns.length; i++) {
      var on = btns[i].getAttribute('data-team') === (team || '');
      btns[i].classList.toggle('is-on', on);
      btns[i].setAttribute('aria-pressed', on ? 'true' : 'false');
    }
  }

  /* ---------- the option menu ---------- */

  /* Fill a `.dd-menu` with options.
   *
   *   menu     the .dd-menu element
   *   options  [{ value, label, note, groupStart }] — the caller decides what
   *            the list is. The schedule's week menu is "all weeks" plus the
   *            eighteen in its data file; the notes modal's also carries the
   *            preseason and the four playoff rounds, since a note can be about
   *            either and neither is a numbered week.
   *   attr     the data-* suffix a pick is read back off, defaulting to "week".
   *            The schedule has two of these menus side by side — weeks and
   *            seasons — and each one's click handler looks for its own
   *            attribute, so a stray click in the wrong panel reads as no pick
   *            rather than as a week 2026.
   */
  function buildOptionMenu(menu, options, attr) {
    attr = attr || 'week';
    menu.innerHTML = (options || []).map(function (o) {
      return '<button type="button" class="dd-opt' +
        (o.groupStart ? ' is-group-start' : '') +
        '" data-' + attr + '="' + esc(o.value) + '" role="menuitem">' +
        esc(o.label) +
        (o.note ? '<span class="dd-note">' + esc(o.note) + '</span>' : '') +
        '</button>';
    }).join('');
  }

  function syncOptionMenu(btn, menu, value, label, attr) {
    attr = attr || 'week';
    btn.querySelector('.dd-value').textContent = label;
    var opts = menu.querySelectorAll('.dd-opt');
    for (var i = 0; i < opts.length; i++) {
      opts[i].classList.toggle('is-on',
        opts[i].getAttribute('data-' + attr) === String(value));
    }
  }

  /* The week menu is the option menu with the attribute it has always used —
   * kept as its own name because that is what /football/schedule and the notes
   * modal both call, and because "the week menu" is what it is to them. */
  function buildWeekMenu(menu, options) { buildOptionMenu(menu, options, 'week'); }

  function syncWeekMenu(btn, menu, value, label) {
    syncOptionMenu(btn, menu, value, label, 'week');
  }

  global.NFL_CONFERENCES = NFL_CONFERENCES;
  global.registerDropdown = registerDropdown;
  global.openDropdown = openDropdown;
  global.closeDropdown = closeDropdown;
  global.closeAllDropdowns = closeAllDropdowns;
  global.anyDropdownOpen = anyDropdownOpen;
  global.buildTeamPicker = buildTeamPicker;
  global.syncTeamPicker = syncTeamPicker;
  global.buildOptionMenu = buildOptionMenu;
  global.syncOptionMenu = syncOptionMenu;
  global.buildWeekMenu = buildWeekMenu;
  global.syncWeekMenu = syncWeekMenu;
})(window);
