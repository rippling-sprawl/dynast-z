// Shared navigation data and hamburger drawer component
const NAV_ITEMS = [
  { type: 'section', label: 'Tools' },
  { type: 'link', label: 'Trade Calculator', href: '/trade-calculator' },
  { type: 'section', label: 'Leagues' },
  { type: 'link', label: 'JHBC', href: '/league/1314983622930870272' },
  { type: 'section', label: 'News' },
  { type: 'link', label: 'Sharply Stupid Blog', href: 'https://sharplystupid.substack.com/', external: true },
  { type: 'section', label: 'Resources' },
  { type: 'link', label: 'Acknowledgements', href: '/acknowledgements' },
];

function buildNavDrawerHTML() {
  const items = NAV_ITEMS.map(item => {
    if (item.type === 'section') {
      return `<li><span class="nav-section-label">${item.label}</span></li>`;
    }
    const cls = item.type === 'sub' ? ' class="nav-sub"' : '';
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
        ${items}
      </ul>
    </div>
  </div>`;
}

function buildHeaderHTML(statusText) {
  return `<header>
    <div style="display: flex; align-items: center; gap: 12px;">
      <button class="hamburger" id="nav-toggle" aria-label="Menu">&#9776;</button>
      <h1><a href="/" style="color: inherit; text-decoration: none;">Dynast-Z</a></h1>
    </div>
    <span id="header-status">${statusText || ''}</span>
  </header>`;
}

function initPage(statusText) {
  const headerMount = document.getElementById('header-mount');
  if (headerMount) {
    headerMount.outerHTML = buildHeaderHTML(statusText);
  }

  const drawerMount = document.getElementById('nav-drawer-mount');
  if (drawerMount) {
    drawerMount.outerHTML = buildNavDrawerHTML();
  }

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
