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
const NAV_SECTIONS = [
  {
    label: 'Football',
    // The section heading is itself the football hub, so /football needs no
    // separate self-referential row inside its own list.
    href: '/football',
    items: [
      { label: "Baker's Buns", href: '/football/bakers-buns', emoji: '🍞',
        desc: 'Season notes, projections &amp; open positions' },
      { label: 'NFL Schedule', href: '/football/schedule', emoji: '📅',
        desc: 'The full season by week &amp; team, primetime flagged' },
      // Baker's Oven holds per-account leagues and boards, but the landing
      // page is public and pitches itself to signed-out visitors, so it is
      // listed for everyone.
      { label: "Baker's Oven", href: '/football/bakers-oven', emoji: '🔥',
        desc: 'Live draft companion &mdash; your leagues, big board &amp; next pick' },
      { label: 'Action', href: '/football/action', emoji: '🏈', admin: true,
        desc: 'The open Action Network book &mdash; season futures and every week of the schedule' },
      { label: 'Bets', href: '/bets', emoji: '🎯',
        desc: 'Track your wagers &amp; history' },
      { label: 'Trade Calculator', href: '/football/trade-calculator', emoji: '⚖️',
        desc: 'Value any dynasty trade with blended rankings' },
      { label: 'NFL Odds', href: '/odds', emoji: '🎲', hidden: true,
        desc: 'From FanDuel, DraftKings and theScore' },
    ],
  },
  {
    label: 'Everything Else',
    items: [
      { label: 'Golf', href: '/golf', emoji: '🏌️',
        desc: 'Majors, leaderboards, 3-balls &amp; groups' },
      { label: 'Grading System', href: '/football/grading-system', emoji: '📊',
        desc: 'How player &amp; pick values are calculated' },
      { label: 'Sharply Stupid Blog', href: 'https://sharplystupid.substack.com/',
        emoji: '📰', external: true, desc: 'The blog' },
      { label: 'Acknowledgements', href: '/acknowledgements', emoji: '🧠',
        desc: 'Resources &amp; acknowledgements' },
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

// The drawer's flat list, sections included.
function buildNavItems() {
  const items = [];
  for (const section of NAV_SECTIONS) {
    items.push({ type: 'section', label: section.label, href: section.href });
    for (const item of navVisibleItems(section)) {
      items.push({ type: 'link', label: item.label, href: item.href, external: item.external });
    }
  }
  return items;
}

// A section's cards, for the home page and the /football hub.
function buildHubCardsHTML(sectionLabel) {
  const section = NAV_SECTIONS.find(s => s.label === sectionLabel);
  if (!section) return '';
  return navVisibleItems(section).map(item => {
    const target = item.external ? ' target="_blank"' : '';
    const emoji = item.emoji ? `<span class="hub-emoji">${item.emoji}</span>` : '';
    const desc = item.desc ? `<p>${item.desc}</p>` : '';
    return `<a class="hub-card" href="${item.href}"${target}><h3>${emoji}${item.label}</h3>${desc}</a>`;
  }).join('\n      ');
}

// Mount every `<div class="hub-grid" data-nav-section="...">` on the page.
function mountHubGrids(root) {
  const scope = root || document;
  scope.querySelectorAll('[data-nav-section]').forEach(el => {
    el.innerHTML = buildHubCardsHTML(el.getAttribute('data-nav-section'));
  });
}

function buildNavDrawerHTML() {
  const items = buildNavItems().map(item => {
    if (item.type === 'section') {
      return item.href
        ? `<li><a class="nav-section-label" href="${item.href}">${item.label}</a></li>`
        : `<li><span class="nav-section-label">${item.label}</span></li>`;
    }
    const cls = item.type === 'sub' ? ' class="nav-sub"' : '';
    const target = item.external ? ' target="_blank"' : '';
    return `<li${cls}><a href="${item.href}"${target}>${item.label}</a></li>`;
  }).join('\n        ');

  // The theme switch is a setting rather than a destination, so it sits under
  // the links in its own footer instead of joining the list. Its markup comes
  // from scripts/base/theme.js — see mountToggle() there for the wiring.
  const themeHTML = typeof Theme !== 'undefined' ? Theme.controlHTML() : '';

  return `<div class="nav-overlay" id="nav-overlay">
    <div class="nav-drawer">
      <div class="nav-drawer-header">
        <h2>Dynast-Z</h2>
        <button class="nav-close" id="nav-close" aria-label="Close menu">&times;</button>
      </div>
      <ul>
        ${items}
      </ul>
      ${themeHTML}
    </div>
  </div>`;
}

function buildHeaderHTML() {
  const user = typeof getUser === 'function' ? getUser() : null;
  const acctHTML = user
    ? `<a href="/account" style="font-size:11px;font-family:monospace;color:var(--accent-2);text-decoration:none">${user.username}</a>`
    : `<a href="/account" style="font-size:11px;font-family:monospace;color:var(--text-4);text-decoration:none">Sign In</a>`;
  return `<header>
    <div style="display: flex; align-items: center; gap: 12px;">
      <button class="hamburger" id="nav-toggle" aria-label="Menu">&#9776;</button>
      <h1><a href="/" style="color: inherit; text-decoration: none;">Dynast-Z</a></h1>
    </div>
    ${acctHTML}
  </header>`;
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

  document.getElementById('nav-toggle').addEventListener('click', () => {
    document.getElementById('nav-overlay').classList.add('open');
  });
  document.getElementById('nav-close').addEventListener('click', () => {
    document.getElementById('nav-overlay').classList.remove('open');
  });
  document.getElementById('nav-overlay').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) e.currentTarget.classList.remove('open');
  });
}

function initNavDrawer() {
  const placeholder = document.getElementById('nav-drawer-mount');
  if (placeholder) {
    placeholder.innerHTML = buildNavDrawerHTML();
  }

  if (typeof Theme !== 'undefined') Theme.mountToggle();

  document.getElementById('nav-toggle').addEventListener('click', () => {
    document.getElementById('nav-overlay').classList.add('open');
  });
  document.getElementById('nav-close').addEventListener('click', () => {
    document.getElementById('nav-overlay').classList.remove('open');
  });
  document.getElementById('nav-overlay').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) e.currentTarget.classList.remove('open');
  });
}
