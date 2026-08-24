// Shared navigation data and hamburger drawer component

const GOLF_TOURNAMENTS = [
  { slug: 'masters', name: 'The Masters', dates: 'Apr 9-12' },
  // { slug: 'pga-championship', name: 'PGA Championship', dates: 'May 14-17' },
  // { slug: 'us-open', name: 'US Open', dates: 'Jun 18-21' },
  // { slug: 'british-open', name: 'The Open', dates: 'Jul 16-19' },
];

const CURRENT_GOLF_YEAR = 2026;

function buildNavItems() {
  const items = []
  items.push(
    { type: 'section', label: 'Betting' },
    { type: 'link', label: 'Bets', href: '/bets' },
    { type: 'section', label: 'Football' },
    // Baker's Oven holds per-account leagues and boards, but the landing
    // page is public and pitches itself to signed-out visitors, so it is
    // listed for everyone.
    { type: 'link', label: "Baker's Oven", href: '/football/bakers-oven' },
    { type: 'link', label: 'Trade Calculator', href: '/football/trade-calculator' },
    { type: 'link', label: 'NFL Schedule', href: '/football/schedule' },
    { type: 'link', label: "Baker's Buns", href: '/football/bakers-buns' },
    { type: 'link', label: 'NFL Odds', href: '/odds' },
    { type: 'link', label: 'JHBC', href: '/league/1314983622930870272' },
    { type: 'link', label: 'Drew Dynasty', href: '/league/1312081645817327616' },
    // { type: 'section', label: 'News' },
    { type: 'section', label: 'Resources' },
    { type: 'link', label: 'Sharply Stupid Blog', href: 'https://sharplystupid.substack.com/', external: true },
    { type: 'link', label: 'Acknowledgements', href: '/acknowledgements' },
  );

  items.push(
    { type: 'section', label: 'Golf' },
    // { type: 'link', label: 'Season Calendar', href: '/golf/' + CURRENT_GOLF_YEAR },
  );
  for (const t of GOLF_TOURNAMENTS) {
    items.push({ type: 'link', label: t.name, href: '/golf/' + CURRENT_GOLF_YEAR + '/' + t.slug });
  }
  // items.push({ type: 'link', label: 'Archive', href: '/archive' });
  return items;
}

const NAV_ITEMS = buildNavItems();

function buildNavDrawerHTML() {
  const items = NAV_ITEMS.map(item => {
    if (item.type === 'section') {
      return `<li><span class="nav-section-label">${item.label}</span></li>`;
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

function buildIndexNavHTML() {
  let html = '<ul>';
  let inSection = false;

  NAV_ITEMS.forEach(item => {
    if (item.type === 'section') {
      if (inSection) html += '</ul></li>';
      html += `<li><span class="section-label">${item.label}</span><ul>`;
      inSection = true;
    } else {
      const target = item.external ? ' target="_blank"' : '';
      html += `<li><a href="${item.href}"${target}>${item.label}</a></li>`;
    }
  });

  if (inSection) html += '</ul></li>';
  html += '</ul>';
  return html;
}
