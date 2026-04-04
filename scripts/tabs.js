// Shared league tab bar component
const LEAGUE_TABS = [
  { label: 'Rosters', suffix: '' },
  { label: 'Scout', suffix: '/scout' },
  { label: 'Latest Trades', suffix: '/new-trades' },
  { label: 'Past Trades', suffix: '/trades' },
  //{ label: 'Power Rankings', suffix: '/power' },
];

function initTabBar(leagueId) {
  const currentPath = window.location.pathname.replace(/\/$/, '');
  const tabBar = document.getElementById('tab-bar');
  if (!tabBar) return;

  tabBar.innerHTML = LEAGUE_TABS.map(t => {
    const href = `/league/${leagueId}${t.suffix}`;
    const isActive = currentPath === href ? ' active' : '';
    return `<a class="tab${isActive}" href="${href}">${t.label}</a>`;
  }).join('');
}
