// Shared navigation data and hamburger drawer component
//
// One list drives three surfaces: the hamburger drawer (every page), the home
// page grid, and the /football hub grid. Sections here are the site's shape —
// keep them in sync with the breadcrumbs on the pages they point at.

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
//              themselves are static and served to anyone with the URL)
//   external — opens in a new tab
//
// A section may also carry `href` (its own landing page) and `collapsed` (the
// drawer shows that landing page as one link instead of listing the items).
const NAV_SECTIONS = [
  {
    // The football pages split three ways by what you are actually doing on
    // them: betting, playing a pool, or running a fantasy roster. There is no
    // Football heading over the three — /football is still the hub the
    // breadcrumbs point at, but the drawer names the three things instead of
    // the sport they share.
    label: 'Gambling',
    items: [
      { label: "Baker's Buns", href: '/football/bakers-buns', emoji: '🍞' },
      { label: "Baker's Action", href: '/football/action', emoji: '🏈', admin: true },
      { label: 'Bet Tracker', href: '/bets', emoji: '🎯' },
      // /football/schedule: the week's slate, read for its lines rather than
      // its kickoff times, which is what puts it under Gambling.
      { label: 'Odds', href: '/football/schedule', emoji: '📅' },
      { label: 'NFL Odds', href: '/odds', emoji: '🎲', hidden: true },
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
    label: 'Appendix',
    href: '/appendix',
    // Collapsed in the drawer: one link to /appendix rather than a heading with
    // a row per item under it. The items below are the cards on that page.
    collapsed: true,
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

// The drawer's flat list, sections included. A `collapsed` section contributes
// a single link to its own landing page instead of a heading and its rows.
function buildNavItems() {
  const items = [];
  for (const section of NAV_SECTIONS) {
    if (section.collapsed) {
      items.push({ type: 'link', label: section.label, href: section.href, standalone: true });
      continue;
    }
    items.push({ type: 'section', label: section.label, href: section.href });
    for (const item of navVisibleItems(section)) {
      items.push({ type: 'link', label: item.label, href: item.href, external: item.external });
    }
  }
  return items;
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
    return `<a class="hub-card is-title-only" href="${item.href}"${target}><h3>${emoji}${item.label}</h3></a>`;
  }).join('\n      ');
}

// Mount every `<div class="hub-grid" data-nav-section="...">` on the page.
function mountHubGrids(root) {
  const scope = root || document;
  scope.querySelectorAll('[data-nav-section]').forEach(el => {
    el.innerHTML = buildHubCardsHTML(el.getAttribute('data-nav-section'));
  });
}

// The account row leads the drawer rather than sitting in the header: it is a
// destination like every other row, and the header is left with just the menu
// button and the title. Signed out it reads "Sign In" and goes to the same page.
//
// The theme circles ride this row. They are a setting rather than a
// destination, but they are also the only one, and two 24px buttons in the
// space the name leaves empty cost nothing — where a footer of their own cost
// a heading, a rule and the bottom of the drawer.
function buildNavAccountHTML() {
  const user = typeof getUser === 'function' ? getUser() : null;
  const label = user ? user.username : 'Sign In';
  const themeHTML = typeof Theme !== 'undefined' ? Theme.controlHTML() : '';
  return `<li class="nav-account"><a class="nav-section-label" href="/account">${label}</a>${themeHTML}</li>`;
}

function buildNavDrawerHTML() {
  const items = buildNavItems().map(item => {
    if (item.type === 'section') {
      return item.href
        ? `<li><a class="nav-section-label" href="${item.href}">${item.label}</a></li>`
        : `<li><span class="nav-section-label">${item.label}</span></li>`;
    }
    // `standalone` is a top-level destination with no heading over it, so it
    // needs a rule above it or it reads as one more row of the section before.
    const cls = item.standalone ? ' class="nav-standalone"'
      : item.type === 'sub' ? ' class="nav-sub"' : '';
    const target = item.external ? ' target="_blank"' : '';
    return `<li${cls}><a href="${item.href}"${target}>${item.label}</a></li>`;
  }).join('\n        ');

  return `<div class="nav-overlay" id="nav-overlay">
    <div class="nav-drawer">
      <div class="nav-drawer-header">
        <h2>Dynast-Z</h2>
        <button class="nav-close" id="nav-close" aria-label="Close menu">&times;</button>
      </div>
      <ul>
        ${buildNavAccountHTML()}
        ${items}
        ${typeof Standalone !== 'undefined' ? Standalone.rowHTML() : ''}
      </ul>
    </div>
  </div>`;
}

// --- Bar icons ---
// Drawn here rather than shipped as files so they inherit the bar's colour with
// no second request: one path set each, stroked in currentColor, sized by the
// stylesheet. 24x24 box, 1.8 stroke, so the three read at one weight.
const NAV_ICONS = {
  // A house: the site root, which is where the hub grid lives.
  home: '<path d="M3.5 10.7 12 4l8.5 6.7"/><path d="M5.8 9.2v9.9a1.9 1.9 0 0 0 1.9 1.9h8.6a1.9 1.9 0 0 0 1.9-1.9V9.2"/><path d="M9.9 21v-5.3a1.3 1.3 0 0 1 1.3-1.3h1.6a1.3 1.3 0 0 1 1.3 1.3V21"/>',
  // A calendar: the slate is a week of dates before it is anything else.
  odds: '<path d="M4 6.5a2.5 2.5 0 0 1 2.5-2.5h11A2.5 2.5 0 0 1 20 6.5v12a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 18.5z"/><path d="M8 2.5v4M16 2.5v4M4 10h16"/>',
  // A scored loaf: dome, base, three slashes.
  buns: '<path d="M3.4 14.4a8.6 7.4 0 0 1 17.2 0"/><path d="M2.6 14.4h18.8V17a3 3 0 0 1-3 3H5.6a3 3 0 0 1-3-3z"/><path d="M8.6 8.2 7.2 11.1M12.4 7.5 11 10.7M16.2 8.7l-1.3 2.7"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
};

function navIconHTML(name) {
  return `<svg class="nav-tab-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${NAV_ICONS[name]}</svg>`;
}

// The shortcut destinations on the bar. Everything else is a drawer row —
// these are here because they are the pages people come back to daily. Home
// leads, because the bar has no title on it to be the way back to "/".
const NAV_TABS = [
  { label: 'Home', href: '/', icon: 'home' },
  { label: 'Odds', href: '/football/schedule', icon: 'odds' },
  { label: 'Buns', href: '/football/bakers-buns', icon: 'buns' },
];

// The page a tab points at, or a page under it (a game page under /schedule),
// marks that tab. Exact match on the site root only, so "/" is not a prefix of
// everything.
function navTabIsCurrent(href) {
  const path = location.pathname.replace(/\/+$/, '') || '/';
  return path === href || path.startsWith(href + '/');
}

// One header serves both shapes. Its DOM order is the mobile order — the two
// tabs, then the menu button — and the desktop rule pulls the menu button back
// in front of the title with `order`, so reading order and tab order match the
// visual order at both widths without a second copy of the button.
function buildHeaderHTML() {
  const tabs = NAV_TABS.map(tab => {
    const current = navTabIsCurrent(tab.href) ? ' aria-current="page"' : '';
    return `<a class="nav-tab" href="${tab.href}"${current}>${navIconHTML(tab.icon)}<span class="nav-tab-label">${tab.label}</span></a>`;
  }).join('\n    ');

  return `<header class="site-header">
    ${tabs}
    <button class="nav-tab hamburger" id="nav-toggle" aria-label="Menu">${navIconHTML('menu')}<span class="nav-tab-label">Menu</span></button>
    <h1 class="site-title"><a href="/">Dynast-Z</a></h1>
  </header>`;
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
