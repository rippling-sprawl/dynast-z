// Shared league tab bar component
const LEAGUE_TABS = [
  { label: 'Scout', suffix: '/scout' },
  { label: 'Rosters', suffix: '/rosters' },
  { label: 'Schedule', suffix: '/schedule' },
  { label: 'Trades', suffix: '/trades' },
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
