// Shared renderer for a single bet "tile". Used by /bets and /bets/history.
// Depends on helpers from bets.js (fmtOdds, fmtMoney, fmtDate, profitLoss).

function escapeHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function renderBetTile(bet, opts) {
  const showActions = !opts || opts.actions !== false;
  const status = bet.status || 'pending';
  // Hide the wager-status chip when an admin is viewing their own bets (they
  // settle their own wagers, so "paid/unpaid" is noise). Auditing another user
  // still shows it.
  const adminSelf = (typeof isAdmin === 'function' && isAdmin())
    && !(typeof getAuditTarget === 'function' && getAuditTarget());
  const wagerStatus = adminSelf ? '' : (bet.wager_status || '');
  const pl = profitLoss(bet);

  const pick = escapeHtml(bet.side || 'Bet') +
    (bet.selection ? ' <span style="color:#8b949e;font-weight:400">' + escapeHtml(bet.selection) + '</span>' : '');

  // Match (emphasized) with the event date pinned to its right (MM.DD.YY).
  const matchText = bet.match ? escapeHtml(bet.match)
    : (bet.opponent ? 'vs ' + escapeHtml(bet.opponent) : '');
  let matchLine = '';
  if (bet.side && bet.opponent) {
    matchLine =
      '<div class="bet-match-line">' +
        '<span class="bet-match">' + matchText + '</span>' +
        (bet.event_date ? '<span class="bet-event-date">' + escapeHtml(fmtDateShort(bet.event_date)) + '</span>' : '') +
      '</div>';
  }

  // Stake / odds / to win on their own line.
  const wager = [];
  if (bet.stake) wager.push('<span class="k">Stake:</span> ' + escapeHtml(fmtMoney(bet.stake)));
  if (bet.odds_american) wager.push('<span class="k">Odds:</span> ' + escapeHtml(fmtOdds(bet.odds_american)));
  if (bet.to_win) wager.push('<span class="k">To win:</span> ' + escapeHtml(fmtMoney(bet.to_win)));
  const wagerLine = wager.length ? '<div class="bet-wager">' + wager.join(' &middot; ') + '</div>' : '';

  // Remaining metadata (player, P/L).
  const meta = [];
  if (bet.player) meta.push('<span class="k">Player:</span> ' + escapeHtml(bet.player));
  if (pl !== null) {
    const cls = pl > 0 ? 'pos' : (pl < 0 ? 'neg' : '');
    meta.push('<span class="k">P/L:</span> <span class="bet-pl ' + cls + '">' +
      escapeHtml((pl > 0 ? '+' : '') + fmtMoney(pl)) + '</span>');
  }

  const metaLine = meta.length ? '<div class="bet-meta">' + meta.join(' &middot; ') + '</div>' : '';

  const leagueChip = bet.league ? '<span class="bet-league-chip">' + escapeHtml(bet.league) + '</span>' : '';
  const betTypeChip = bet.bet_type ? '<span class="bet-type-chip">' + escapeHtml(bet.bet_type) + '</span>' : '';
  // Edit opens the quick-action modal (see bet-edit-modal.js), falling back to
  // the full /place form via the href if that module isn't loaded / JS is off.
  const editLink = showActions
    ? '<a class="bet-edit" href="/bets/place?id=' + encodeURIComponent(bet.id) + '" data-bet-edit>Edit</a>'
    : '';
  const bottom = (leagueChip || betTypeChip || editLink)
    ? '<div class="bet-tile-bottom">' + leagueChip + betTypeChip + editLink + '</div>'
    : '';

  return (
    '<div class="bet-tile status-' + status + '"' +
      (bet.id ? ' data-bet-id="' + escapeHtml(bet.id) + '"' : '') + '>' +
      '<div class="bet-tile-top">' +
        '<span class="bet-pick">' + pick + '</span>' +
        '<span class="bet-status-group">' +
          (bet._test ? '<span class="bet-test-badge" title="Seeded demo bet — not saved to your history">TEST</span>' : '') +
          '<span class="bet-status status-' + status + '" title="Event status — how the bet resolved">' + escapeHtml(status) + '</span>' +
          (wagerStatus ? '<span class="bet-wager-status wager-' + escapeHtml(wagerStatus) + '" title="Wager status — where the money stands">' + escapeHtml(wagerStatus) + '</span>' : '') +
        '</span>' +
      '</div>' +
      matchLine +
      wagerLine +
      metaLine +
      bottom +
    '</div>'
  );
}
