// Shared navigation data and hamburger drawer component
//
// One list drives the home page grid, the /football hub grid and /appendix.
// The hamburger drawer is not a directory: it holds the account row, the theme
// control and a link to /appendix, and nothing else.

const GOLF_TOURNAMENTS = [
  { slug: 'masters', name: 'The Masters', dates: 'Apr 9-12' },
  // { slug: 'pga-championship', name: 'PGA Championship', dates: 'May 14-17' },
  // { slug: 'us-open', name: 'US Open', dates: 'Jun 18-21' },
  // { slug: 'british-open', name: 'The Open', dates: 'Jul 16-19' },
];

const CURRENT_GOLF_YEAR = 2026;

// Item flags:
//   hidden   — kept for the route it documents, rendered nowhere (see NFL Odds)
//   admin    — only rendered for a signed-in admin (UI gating only; the pages
//              themselves are static and served to anyone with the URL), and
//              marked with a small lock so the admin can tell which rows only
//              they see
//   external — opens in a new tab
//   beta     — a "beta" tag after the label, for pages still being proven out
//
// A section may also carry `href` (its own landing page) and `hidden` (left off
// the hubs that list sections; its landing page still mounts it).
const NAV_SECTIONS = [
  {
    // The football pages split three ways by what you are actually doing on
    // them: betting, playing a pool, or running a fantasy roster.
    label: 'Gambling',
    items: [
      { label: "Baker's Action", href: '/football/action', emoji: '🏈', admin: true, hidden: true },
      { label: 'Bet Tracker', href: '/bets', emoji: '🎯' },
      // Every Action Network bet, filterable, with a P/L chart over the
      // filtered set. Admin-only, and enforced: /api/action-ledger checks
      // X-User-Id, so the gate is more than this flag.
      { label: 'Action Ledger', href: '/football/action-ledger', emoji: '📒', admin: true },
      // /football/schedule: the week's slate, read for its lines rather than
      // its kickoff times, which is what puts it under Gambling.
      { label: 'Schedule', href: '/football/schedule', emoji: '📅' },
      // The week's slate read for its edges: the softest and toughest
      // matchups, and the DraftKings yards lines the projection model
      // disagrees with most.
      { label: 'Weekly Edges', href: '/football/weekly-edges', emoji: '⚡', beta: true },
      // Season-to-date team numbers, read side by side across the league.
      // One card here; its pages are the Team Stats section below.
      { label: 'Team Stats', href: '/football/team-stats', emoji: '📈' },
    ],
  },
  {
    label: 'Fantasy',
    items: [
      // Baker's Oven holds per-account leagues and boards, but the landing
      // page is public and pitches itself to signed-out visitors, so it is
      // listed for everyone.
      { label: "Baker's Oven", href: '/football/bakers-oven', emoji: '🔥' },
      { label: 'Trade Calculator', href: '/football/trade-calculator', emoji: '⚖️' },
    ],
  },
  {
    // Pools, not fixtures: the same slate played by a set of rules against
    // other people. Pick 'Em is every game, Survivor is one team a week.
    label: 'Games',
    items: [
      { label: "Pick 'Em", href: '/football/pickem', emoji: '🏆' },
      { label: 'Survivor', href: '/football/survivor', emoji: '☠️' },
    ],
  },
  {
    // Experiments: boards still being proven out, kept apart from the pages
    // above until they earn a place there.
    label: 'Sandbox',
    items: [
      { label: "Baker's Buns", href: '/football/bakers-buns', emoji: '🍞' },
      // The week's longest-reception prices against a likelihood built from
      // play-by-play rather than from the ladder being priced.
      { label: 'Longest Reception', href: '/football/long-reception', emoji: '📏' },
      // A finished season's waiver market, not a live board: the Cut Throat 2025
      // FAAB log, frozen. League history rather than anything to act on this
      // week.
      { label: 'Waiver Board', href: '/football/waivers', emoji: '💸', admin: true },
      // The JHBC power rankings as swipeable trading cards, built from
      // data/power_rankings_cards.json.
      { label: 'Power Rankings', href: '/power-rankings', emoji: '🐝', admin: true },
    ],
  },
  {
    // The cards on /football/team-stats, which mounts them itself.
    label: 'Team Stats',
    href: '/football/team-stats',
    hidden: true,
    items: [
      { label: 'Yards vs Points', href: '/football/team-stats/yards-vs-points', emoji: '📐' },
      // Points by quarter, scored and allowed, one team's games stacked.
      { label: 'Quarter Splits', href: '/football/team-stats/quarter-splits', emoji: '⏱️' },
    ],
  },
  {
    label: 'Appendix',
    href: '/appendix',
    // The one section the drawer links, as a single row to /appendix. The
    // items below are the cards on that page.
    items: [
      { label: 'Golf', href: '/golf', emoji: '🏌️' },
      // Reference rather than a football destination: it is not a slate to bet
      // or a board to play, it is what has been captured off /football/schedule
      // and how current each capture is. Filed here with the Grading System.
      { label: 'Live Stats', href: '/football/live-stats', emoji: '📡' },
      { label: 'Grading System', href: '/football/grading-system', emoji: '📊' },
      { label: 'Sharply Stupid Blog', href: 'https://sharplystupid.substack.com/', emoji: '📰', external: true },
      { label: 'Acknowledgements', href: '/acknowledgements', emoji: '🧠' },
    ],
  },
];

// Admin state is read at render time, not at load: nav.js is included on pages
// that do not load auth.js at all, and on the ones that do the session can
// change under a long-lived page.
function navVisibleItems(section) {
  const admin = typeof isLoggedIn === 'function' && isLoggedIn()
    && typeof isAdmin === 'function' && isAdmin();
  return section.items.filter(i => !i.hidden && (!i.admin || admin));
}

const NAV_BETA_HTML = ' <span class="nav-beta">beta</span>';
const NAV_ADMIN_HTML = '<span class="nav-admin" title="Admin only" aria-label="Admin only">'
  + '<svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">'
  + '<rect x="3" y="7" width="10" height="7" rx="1.5"/><path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2"/></svg></span>';

// What follows a label: the admin lock and the beta tag, whichever apply.
function navTagsHTML(item) {
  return (item.admin ? NAV_ADMIN_HTML : '') + (item.beta ? NAV_BETA_HTML : '');
}

// A section's cards, for the home page, the /football hub and /appendix. Title
// only — the label and its emoji say what the destination is, and a sentence of
// description under each one turned the grid into something to read rather than
// something to scan.
function buildHubCardsHTML(sectionLabel) {
  const section = NAV_SECTIONS.find(s => s.label === sectionLabel);
  if (!section) return '';
  return navVisibleItems(section).map(item => {
    const target = item.external ? ' target="_blank"' : '';
    const emoji = item.emoji ? `<span class="hub-emoji">${item.emoji}</span>` : '';
    return `<a class="hub-card is-title-only" href="${item.href}"${target}><h3>${emoji}${item.label}${navTagsHTML(item)}</h3></a>`;
  }).join('\n      ');
}

// Mount every `<div class="hub-grid" data-nav-section="...">` on the page.
function mountHubGrids(root) {
  const scope = root || document;
  scope.querySelectorAll('[data-nav-section]').forEach(el => {
    el.innerHTML = buildHubCardsHTML(el.getAttribute('data-nav-section'));
  });
}

// The account row leads the drawer rather than sitting in the header, which is
// left with just the menu button and the title. Signed out it reads "Sign In"
// and goes to the same page.
//
// The theme circles ride this row: two 24px buttons in the space the name
// leaves empty cost nothing, where a footer of their own cost a heading, a rule
// and the bottom of the drawer.
function buildNavAccountHTML() {
  const user = typeof getUser === 'function' ? getUser() : null;
  const label = user ? user.username : 'Sign In';
  const themeHTML = typeof Theme !== 'undefined' ? Theme.controlHTML() : '';
  return `<li class="nav-account"><a class="nav-section-label" href="/account">${label}</a>${themeHTML}</li>`;
}

// Account and theme, then Appendix and the projection model's explainer.
// Every other destination is on a hub grid or the bar, so the drawer does not
// list them again.
function buildNavDrawerHTML() {
  const appendix = NAV_SECTIONS.find(s => s.label === 'Appendix');
  const appendixHTML = `<li class="nav-standalone"><a href="${appendix.href}">${appendix.label}</a></li>`;
  const modelHTML = '<li class="nav-standalone"><a href="/football/projection-model">Projection Model</a></li>';

  return `<div class="nav-overlay" id="nav-overlay">
    <div class="nav-drawer">
      <div class="nav-drawer-header">
        <h2>Dynast-Z</h2>
        <button class="nav-close" id="nav-close" aria-label="Close menu">&times;</button>
      </div>
      <ul>
        ${buildNavAccountHTML()}
        ${appendixHTML}
        ${modelHTML}
        ${typeof Standalone !== 'undefined' ? Standalone.rowHTML() : ''}
      </ul>
    </div>
  </div>`;
}

// --- Bar icons ---
// Drawn here rather than shipped as files so they inherit the bar's colour with
// no second request: one path set each, stroked in currentColor, sized by the
// stylesheet. 24x24 box, 1.8 stroke, so they read at one weight.
const NAV_ICONS = {
  // A house: the site root, which is where the hub grid lives.
  home: '<path d="M3.5 10.7 12 4l8.5 6.7"/><path d="M5.8 9.2v9.9a1.9 1.9 0 0 0 1.9 1.9h8.6a1.9 1.9 0 0 0 1.9-1.9V9.2"/><path d="M9.9 21v-5.3a1.3 1.3 0 0 1 1.3-1.3h1.6a1.3 1.3 0 0 1 1.3 1.3V21"/>',
  // A calendar: the slate is a week of dates before it is anything else.
  odds: '<path d="M4 6.5a2.5 2.5 0 0 1 2.5-2.5h11A2.5 2.5 0 0 1 20 6.5v12a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 18.5z"/><path d="M8 2.5v4M16 2.5v4M4 10h16"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  // A magnifying glass: the player search.
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.5 15.5 5 5"/>',
};

function navIconHTML(name) {
  return `<svg class="nav-tab-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${NAV_ICONS[name]}</svg>`;
}

// The shortcut destinations on the bar. Everything else is reached from a hub
// grid — these are here because they are the pages people come back to daily. Home
// leads, because the bar has no title on it to be the way back to "/".
const NAV_TABS = [
  { label: 'Home', href: '/', icon: 'home' },
  { label: 'Schedule', href: '/football/schedule', icon: 'odds' },
];

// The page a tab points at, or a page under it (a game page under /schedule),
// marks that tab. Exact match on the site root only, so "/" is not a prefix of
// everything.
function navTabIsCurrent(href) {
  const path = location.pathname.replace(/\/+$/, '') || '/';
  return path === href || path.startsWith(href + '/');
}

// One header serves both shapes. Its DOM order is the mobile order — the
// tabs, then search, then the menu button — and the desktop rule pulls the menu
// button back in front of the title with `order`, so reading order and tab order match the
// visual order at both widths without a second copy of the button.
function buildHeaderHTML() {
  const tabs = NAV_TABS.map(tab => {
    const current = navTabIsCurrent(tab.href) ? ' aria-current="page"' : '';
    return `<a class="nav-tab" href="${tab.href}"${current}>${navIconHTML(tab.icon)}<span class="nav-tab-label">${tab.label}</span></a>`;
  }).join('\n    ');

  return `<header class="site-header">
    ${tabs}
    <button class="nav-tab nav-search-tab" id="nav-search-toggle" aria-haspopup="dialog" aria-controls="nav-search-modal">${navIconHTML('search')}<span class="nav-tab-label">Search</span></button>
    ${buildNavSearchModalHTML()}
    <button class="nav-tab hamburger" id="nav-toggle" aria-label="Menu">${navIconHTML('menu')}<span class="nav-tab-label">Menu</span></button>
    <h1 class="site-title"><a href="/">Dynast-Z</a></h1>
  </header>`;
}

// --- Player and team search ---
// The bar's Search tab opens the search box from /football/player-projections
// in a modal: the Trade Calculator's player list (/api/players), warmed in the
// background after launch, searched once two characters are typed, filtered on every word, with the teams it matches
// listed above the players. Before that, the modal lists the last five picks. A player opens on that page, a team on
// /football/team/<abbr> — or, on that page already, the pick goes to
// the page (window.playerProjectionsPick, window.defenseVsPlayersPick)
// instead of reloading it.
const NAV_SEARCH_POS = ['QB', 'RB', 'WR', 'TE'];
const NAV_SEARCH_MAX = 10;
const NAV_SEARCH_TEAM_MAX = 3;
// The schedule's abbreviations, which are the logo filenames and the `team`
// path segment /football/team reads. Kept here rather than read from the
// schedule file, which most pages do not load.
const NAV_TEAMS = [
  ['ARI', 'Arizona', 'Cardinals'], ['ATL', 'Atlanta', 'Falcons'], ['BAL', 'Baltimore', 'Ravens'],
  ['BUF', 'Buffalo', 'Bills'], ['CAR', 'Carolina', 'Panthers'], ['CHI', 'Chicago', 'Bears'],
  ['CIN', 'Cincinnati', 'Bengals'], ['CLE', 'Cleveland', 'Browns'], ['DAL', 'Dallas', 'Cowboys'],
  ['DEN', 'Denver', 'Broncos'], ['DET', 'Detroit', 'Lions'], ['GB', 'Green Bay', 'Packers'],
  ['HOU', 'Houston', 'Texans'], ['IND', 'Indianapolis', 'Colts'], ['JAX', 'Jacksonville', 'Jaguars'],
  ['KC', 'Kansas City', 'Chiefs'], ['LAC', 'Los Angeles', 'Chargers'], ['LAR', 'Los Angeles', 'Rams'],
  ['LV', 'Las Vegas', 'Raiders'], ['MIA', 'Miami', 'Dolphins'], ['MIN', 'Minnesota', 'Vikings'],
  ['NE', 'New England', 'Patriots'], ['NO', 'New Orleans', 'Saints'], ['NYG', 'New York', 'Giants'],
  ['NYJ', 'New York', 'Jets'], ['PHI', 'Philadelphia', 'Eagles'], ['PIT', 'Pittsburgh', 'Steelers'],
  ['SEA', 'Seattle', 'Seahawks'], ['SF', 'San Francisco', '49ers'], ['TB', 'Tampa Bay', 'Buccaneers'],
  ['TEN', 'Tennessee', 'Titans'], ['WSH', 'Washington', 'Commanders'],
].map(([abbr, city, nick]) => ({ abbr, name: city + ' ' + nick, key: navFold(abbr + ' ' + city + ' ' + nick) }));
// The dynasty sources' Washington; balldontlie and the schedule say WSH.
const NAV_TEAM_ALIAS = { WAS: 'WSH' };

function navEsc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}

// Case, accents and punctuation dropped, as on the page, so "amon ra" finds
// Amon-Ra.
function navFold(s) {
  return String(s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .toLowerCase().replace(/[^a-z0-9 ]/g, '');
}

// The list is also kept in localStorage — slimmed to what the search reads,
// ~30 KB against the endpoint's ~90 KB — so a search right after launch is
// instant. A copy under a day old is used as is; past six hours it is still
// used, and refreshed behind it for next time.
const NAV_PLAYERS_KEY = 'dz_search_players';
const NAV_PLAYERS_REFRESH = 6 * 3600 * 1000;
const NAV_PLAYERS_MAX_AGE = 24 * 3600 * 1000;

function navFetchPlayers() {
  return fetch('/api/players').then(r => r.json()).then(d => {
    if (!Array.isArray(d)) throw new Error((d && d.error) || 'player list unavailable');
    const seen = {};
    const players = d.filter(p => NAV_SEARCH_POS.includes(p.position) && p.team && p.team !== 'FA')
      .map(p => ({ name: p.name, pos: p.position, team: NAV_TEAM_ALIAS[p.team] || p.team }))
      .filter(p => {
        const k = navFold(p.name) + '|' + p.pos;
        return seen[k] ? false : (seen[k] = true);
      });
    try {
      localStorage.setItem(NAV_PLAYERS_KEY, JSON.stringify({ t: Date.now(), players }));
    } catch (e) { /* storage is a speed-up, not a requirement */ }
    return players;
  });
}

function navStoredPlayers() {
  try {
    const doc = JSON.parse(localStorage.getItem(NAV_PLAYERS_KEY) || 'null');
    if (doc && Array.isArray(doc.players) && doc.players.length && Date.now() - doc.t < NAV_PLAYERS_MAX_AGE) return doc;
  } catch (e) { /* fall through to the network */ }
  return null;
}

// The search key is folded here rather than stored, so a change to navFold
// never meets keys folded the old way.
let navPlayersReq = null;
function navLoadPlayers() {
  if (!navPlayersReq) {
    const stored = navStoredPlayers();
    let req;
    if (stored) {
      req = Promise.resolve(stored.players);
      if (Date.now() - stored.t > NAV_PLAYERS_REFRESH) navFetchPlayers().catch(() => {});
    } else {
      req = navFetchPlayers();
    }
    navPlayersReq = req.then(players => players.map(p => ({ ...p, key: navFold(p.name) })))
      .catch(e => { navPlayersReq = null; throw e; });
  }
  return navPlayersReq;
}

// Warm the list once the page has settled, so the first search does not wait
// on it: in idle time where the browser offers it (not Safari), else shortly
// after load. Only where a way into search shows: the phone bar's Search tab,
// or a page's own field (data-nav-search-open, the home page on wide screens).
// Checked at warm time, since that field is parsed after initPage runs.
function navPrefetchPlayers() {
  const warm = () => {
    const field = document.querySelector('[data-nav-search-open]');
    if (!window.matchMedia('(max-width: 640px)').matches && !(field && field.offsetParent)) return;
    navLoadPlayers().catch(() => {});
  };
  const schedule = () => (window.requestIdleCallback
    ? requestIdleCallback(warm, { timeout: 4000 })
    : setTimeout(warm, 1500));
  if (document.readyState === 'complete') schedule();
  else window.addEventListener('load', schedule, { once: true });
}

const NAV_SEARCH_MIN = 2;
const NAV_RECENT_KEY = 'dz_recent_searches';
const NAV_RECENT_MAX = 5;

function buildNavSearchModalHTML() {
  return `<dialog class="nav-search-modal" id="nav-search-modal" aria-label="Search players and teams">
      <div class="nav-search-field">
        ${navIconHTML('search')}
        <input type="text" class="nav-search-input" id="nav-player" placeholder="Search players or teams…" aria-label="Search players and teams"
               autocomplete="off" spellcheck="false" enterkeyhint="go" role="combobox" aria-autocomplete="list"
               aria-expanded="false" aria-controls="nav-player-list" autofocus>
        <button type="button" class="nav-search-close" id="nav-search-close" aria-label="Close search">&times;</button>
      </div>
      <div class="nav-search-list" id="nav-player-list" role="listbox" aria-label="Players and teams"></div>
    </dialog>`;
}

// Teams match on the abbreviation, city or nickname, so "ny" finds both New
// York teams.
function navSearchTeams(words) {
  if (!words.length) return [];
  return NAV_TEAMS.filter(t => words.every(w => t.key.includes(w))).slice(0, NAV_SEARCH_TEAM_MAX);
}

// The last few picks, newest first, in this browser only. Storage can be
// missing or full (private windows); recents are a convenience, so any failure
// is an empty list.
function navRecentLoad() {
  try {
    const list = JSON.parse(localStorage.getItem(NAV_RECENT_KEY) || '[]');
    return Array.isArray(list) ? list.filter(o => o && o.name && o.team).slice(0, NAV_RECENT_MAX) : [];
  } catch (e) {
    return [];
  }
}

function navRecentSave(o) {
  const entry = o.isTeam
    ? { name: o.name, team: o.team, tag: 'DEF', isTeam: true }
    : { name: o.name, pos: o.pos, team: o.team, tag: o.pos };
  const same = r => !!r.isTeam === !!entry.isTeam && r.name === entry.name && (r.isTeam || r.pos === entry.pos);
  const list = [entry].concat(navRecentLoad().filter(r => !same(r))).slice(0, NAV_RECENT_MAX);
  try { localStorage.setItem(NAV_RECENT_KEY, JSON.stringify(list)); } catch (e) { /* recents are optional */ }
}

// Arrows move, Enter picks, Escape closes (the dialog's own cancel). The modal
// also closes on its X, a tap on the backdrop, and a pick. It opens from the
// bar's Search tab or from any [data-nav-search-open] element on the page.
function wireNavSearch() {
  const toggle = document.getElementById('nav-search-toggle');
  const modal = document.getElementById('nav-search-modal');
  const input = document.getElementById('nav-player');
  const list = document.getElementById('nav-player-list');
  if (!toggle || !modal || !input || !list || typeof modal.showModal !== 'function') return;
  let shown = [], active = -1;
  navPrefetchPlayers();

  const markActive = () => {
    list.querySelectorAll('.nav-search-opt').forEach((o, i) => {
      o.setAttribute('aria-selected', String(i === active));
      if (i === active) o.scrollIntoView({ block: 'nearest' });
    });
    if (active >= 0) input.setAttribute('aria-activedescendant', 'nav-opt-' + active);
    else input.removeAttribute('aria-activedescendant');
  };

  const optHTML = (o, i) =>
    `<button type="button" class="nav-search-opt" role="option" id="nav-opt-${i}" data-i="${i}" tabindex="-1" aria-selected="false">` +
    `<img src="/assets/icons/nfl/${navEsc(o.team)}.svg" alt="">${navEsc(o.name)}<span class="nav-search-pos">${navEsc(o.tag)}</span></button>`;

  // `head` is a heading over the rows, `note` a line under them.
  const showList = (rows, head, note) => {
    shown = rows;
    active = rows.length ? 0 : -1;
    list.innerHTML = (head && rows.length ? `<div class="nav-search-head">${head}</div>` : '') +
      rows.map(optHTML).join('') + (note ? `<div class="nav-search-note">${note}</div>` : '');
    input.setAttribute('aria-expanded', String(rows.length > 0));
    markActive();
  };

  // Under two characters there is nothing to search yet: the box shows the
  // recent picks instead.
  const search = () => {
    const text = input.value;
    const words = navFold(text).split(/\s+/).filter(Boolean);
    if (navFold(text).replace(/\s+/g, '').length < NAV_SEARCH_MIN) {
      const recent = navRecentLoad();
      showList(recent, 'Recent', recent.length ? '' : 'Type at least 2 letters to search');
      return;
    }
    const teams = navSearchTeams(words).map(t => ({ team: t.abbr, name: t.name, tag: 'DEF', isTeam: true }));
    navLoadPlayers().then(players => {
      if (!modal.open || input.value !== text) return;
      const rows = teams.concat(players.filter(p => words.every(w => p.key.includes(w)))
        .slice(0, NAV_SEARCH_MAX).map(p => ({ ...p, tag: p.pos })));
      showList(rows, '', rows.length ? '' : 'No match');
    }).catch(() => {
      // No player list: teams still work, from the list above.
      if (!modal.open || input.value !== text) return;
      showList(teams, '', 'Players unavailable');
    });
  };

  // Focus in the same tap that opens it, or iOS will not raise the keyboard.
  const open = () => {
    input.value = '';
    modal.showModal();
    input.focus();
    search();
  };

  const pick = (o) => {
    if (!o) return;
    navRecentSave(o);
    modal.close();
    const path = location.pathname.replace(/\/+$/, '');
    if (o.isTeam) {
      if (/^\/football\/team(\/|$)/.test(path) && typeof window.defenseVsPlayersPick === 'function'
          && window.defenseVsPlayersPick(o.team)) return;
      location.href = '/football/team/' + encodeURIComponent(o.team);
      return;
    }
    if (path === '/football/player-projections' && typeof window.playerProjectionsPick === 'function'
        && window.playerProjectionsPick(o.name, o.pos, o.team)) return;
    location.href = '/football/player-projections?' + new URLSearchParams({ player: o.name, pos: o.pos });
  };

  toggle.addEventListener('click', open);
  // A page's own field opens the same modal. Delegated, because the header —
  // and so this — is mounted before the rest of the page is parsed.
  document.addEventListener('click', (e) => {
    if (e.target.closest('[data-nav-search-open]')) open();
  });
  document.getElementById('nav-search-close').addEventListener('click', () => modal.close());
  // A click on the dialog element itself, not its contents, is the backdrop.
  modal.addEventListener('click', (e) => {
    if (e.target === modal) modal.close();
  });
  modal.addEventListener('close', () => {
    input.value = '';
    input.blur();
    input.removeAttribute('aria-activedescendant');
  });
  input.addEventListener('input', search);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!shown.length) return;
      active = (active + (e.key === 'ArrowDown' ? 1 : -1) + shown.length) % shown.length;
      markActive();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (active >= 0) pick(shown[active]);
    }
  });
  // mousedown, not click: keeps the focus in the field, so the keyboard stays up.
  list.addEventListener('mousedown', (e) => {
    const opt = e.target.closest('.nav-search-opt');
    if (!opt) return;
    e.preventDefault();
    pick(shown[Number(opt.getAttribute('data-i'))]);
  });
}

// --- Swipe the sheet down to close ---
// Narrow screens only: there the drawer is a bottom sheet with a grab handle on
// it, and a handle that cannot be dragged is a lie. Wide screens keep the
// left-hand drawer, where a downward drag means nothing, so the media query is
// the whole condition.
//
// The gesture starts only at the top of the sheet's own scroll — the drawer is
// `overflow-y: auto` and a list that can still scroll up owns the touch. The
// axis is decided once, on the first few pixels of movement: down is the sheet,
// anything else hands the touch back to the list.
function wireDrawerSwipe(drawer, close) {
  const narrow = window.matchMedia('(max-width: 640px)');
  let startY = 0, startX = 0, startT = 0, dy = 0;
  let tracking = false, dragging = false;

  drawer.addEventListener('touchstart', (e) => {
    tracking = dragging = false;
    dy = 0;
    if (!narrow.matches || e.touches.length !== 1 || drawer.scrollTop > 0) return;
    startY = e.touches[0].clientY;
    startX = e.touches[0].clientX;
    startT = e.timeStamp;
    tracking = true;
  }, { passive: true });

  // Non-passive: once the drag is ours we preventDefault, or iOS rubber-bands
  // the page behind the sheet while the sheet is moving.
  drawer.addEventListener('touchmove', (e) => {
    if (!tracking) return;
    const y = e.touches[0].clientY - startY;
    const x = e.touches[0].clientX - startX;
    if (!dragging) {
      if (Math.abs(y) < 6 && Math.abs(x) < 6) return;
      // Up, or mostly sideways: not a dismiss. Give the touch back.
      if (y <= 0 || Math.abs(x) > Math.abs(y)) { tracking = false; return; }
      dragging = true;
      drawer.style.transition = 'none';
    }
    dy = Math.max(0, y);
    e.preventDefault();
    drawer.style.transform = `translateY(${dy}px)`;
  }, { passive: false });

  // Dropping both inline styles in the same frame as the class change is what
  // makes the finish animate: the browser interpolates from where the finger
  // left the sheet to translateY(0) or translateY(100%), whichever the class
  // now says, under the sheet's own transition.
  const release = (e) => {
    if (!tracking) return;
    const flung = dy / Math.max(1, e.timeStamp - startT) > 0.5;
    const far = dy > drawer.offsetHeight * 0.28;
    drawer.style.transition = '';
    drawer.style.transform = '';
    if (dragging && (far || flung)) close();
    tracking = dragging = false;
    dy = 0;
  };
  drawer.addEventListener('touchend', release);
  drawer.addEventListener('touchcancel', release);
}

// The drawer's behaviour, shared by both mount paths below: open, the three
// ways of closing, and the swipe.
function wireNavDrawer() {
  const overlay = document.getElementById('nav-overlay');
  if (!overlay) return;
  const close = () => overlay.classList.remove('open');

  document.getElementById('nav-toggle').addEventListener('click', () => {
    overlay.classList.add('open');
  });
  document.getElementById('nav-close').addEventListener('click', close);
  overlay.addEventListener('click', (e) => {
    if (e.target === e.currentTarget) close();
  });

  const drawer = overlay.querySelector('.nav-drawer');
  if (drawer) wireDrawerSwipe(drawer, close);
}

function initPage() {
  const headerMount = document.getElementById('header-mount');
  if (headerMount) {
    headerMount.outerHTML = buildHeaderHTML();
  }

  const drawerMount = document.getElementById('nav-drawer-mount');
  if (drawerMount) {
    drawerMount.outerHTML = buildNavDrawerHTML();
  }

  if (typeof Theme !== 'undefined') Theme.mountToggle();
  if (typeof Standalone !== 'undefined') Standalone.mount();

  wireNavDrawer();
  wireNavSearch();
}

function initNavDrawer() {
  const placeholder = document.getElementById('nav-drawer-mount');
  if (placeholder) {
    placeholder.innerHTML = buildNavDrawerHTML();
  }

  if (typeof Theme !== 'undefined') Theme.mountToggle();
  if (typeof Standalone !== 'undefined') Standalone.mount();

  wireNavDrawer();
}
