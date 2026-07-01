// Quick-action modal opened from a bet tile's "Edit" link.
//
// Layers a small dialog above the page with:
//   - a quick event-status selector (updates bet.status only, in place)
//   - icon actions: edit (-> /place form), duplicate + delete (same on-click
//     behavior as /place), and a dismiss "x"
//
// Self-initializing: injects its DOM once and delegates clicks off document, so
// it works for tiles rendered asynchronously on /bets, /bets/history and the
// admin audit view. Depends on globals from bets.js (getBet, upsertBet,
// deleteBet, EVENT_STATUSES, fmtDateShort) and bet-tile.js (renderBetTile).

(function () {
  if (typeof EVENT_STATUSES === 'undefined') return; // bets.js not loaded

  // --- icons ----------------------------------------------------------------
  // Pencil is hand-authored here; duplicate + delete reuse the /place glyphs.
  const ICON_EDIT =
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      '<path d="M12 20h9"></path>' +
      '<path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"></path>' +
    '</svg>';
  const ICON_DUPLICATE =
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      '<rect x="9" y="9" width="11" height="11" rx="2"></rect>' +
      '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>' +
    '</svg>';
  const ICON_DELETE =
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      '<path d="M3 6h18"></path>' +
      '<path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>' +
      '<path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"></path>' +
      '<line x1="10" y1="11" x2="10" y2="17"></line>' +
      '<line x1="14" y1="11" x2="14" y2="17"></line>' +
    '</svg>';
  const ICON_CLOSE =
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      '<path d="M18 6 6 18"></path><path d="m6 6 12 12"></path>' +
    '</svg>';

  let overlay, titleEl, subEl, statusWrap, currentId = null;

  function tileFor(id) {
    return document.querySelector('.bet-tile[data-bet-id="' + (window.CSS && CSS.escape ? CSS.escape(id) : id) + '"]');
  }

  function build() {
    overlay = document.createElement('div');
    overlay.className = 'bet-modal-overlay';
    overlay.hidden = true;
    overlay.innerHTML =
      '<div class="bet-modal" role="dialog" aria-modal="true" aria-labelledby="bet-modal-title">' +
        '<button type="button" class="bet-modal-close" data-close aria-label="Close">' + ICON_CLOSE + '</button>' +
        '<div class="bet-modal-title" id="bet-modal-title"></div>' +
        '<div class="bet-modal-sub"></div>' +
        '<div class="bet-modal-label">Event Status</div>' +
        '<div class="bet-modal-status"></div>' +
        '<div class="bet-modal-label">Actions</div>' +
        '<div class="bet-modal-actions">' +
          '<button type="button" class="bet-modal-icon-btn" data-action="edit" title="Edit details">' + ICON_EDIT + '<span>Edit</span></button>' +
          '<button type="button" class="bet-modal-icon-btn" data-action="duplicate" title="Duplicate">' + ICON_DUPLICATE + '<span>Duplicate</span></button>' +
          '<button type="button" class="bet-modal-icon-btn danger" data-action="delete" title="Delete">' + ICON_DELETE + '<span>Delete</span></button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(overlay);

    titleEl = overlay.querySelector('.bet-modal-title');
    subEl = overlay.querySelector('.bet-modal-sub');
    statusWrap = overlay.querySelector('.bet-modal-status');

    // Backdrop click (outside the dialog) and the close button both dismiss.
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay || e.target.closest('[data-close]')) { close(); return; }
      const chip = e.target.closest('.bet-modal-chip');
      if (chip) { setStatus(chip.dataset.status); return; }
      const act = e.target.closest('[data-action]');
      if (act) doAction(act.dataset.action);
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !overlay.hidden) close();
    });
  }

  function renderChips(active) {
    statusWrap.innerHTML = EVENT_STATUSES.map(s =>
      '<button type="button" class="bet-modal-chip status-' + s + (s === active ? ' active' : '') +
        '" data-status="' + s + '">' + s + '</button>'
    ).join('');
  }

  function open(id) {
    const bet = getBet(id);
    if (!bet) return;
    currentId = id;
    titleEl.textContent = (bet.side || 'Bet') + (bet.selection ? ' ' + bet.selection : '');
    const parts = [];
    const match = bet.match || (bet.opponent ? 'vs ' + bet.opponent : '');
    if (match) parts.push(match);
    if (bet.event_date) parts.push(fmtDateShort(bet.event_date));
    subEl.textContent = parts.join('  ·  ');
    renderChips(bet.status || 'pending');
    overlay.hidden = false;
  }

  function close() {
    overlay.hidden = true;
    currentId = null;
  }

  // Quick status change: updates the event status only, re-renders that tile in
  // place, and reflects the new selection in the modal.
  function setStatus(status) {
    const bet = getBet(currentId);
    if (!bet || bet.status === status) return;
    bet.status = status;
    upsertBet(bet);
    renderChips(status);
    const tile = tileFor(currentId);
    if (tile) tile.outerHTML = renderBetTile(getBet(currentId));
  }

  function doAction(action) {
    if (action === 'edit') {
      location.href = '/bets/place?id=' + encodeURIComponent(currentId);
    } else if (action === 'duplicate') {
      // Same as /place's Duplicate: land on a pre-filled new-bet form.
      location.href = '/bets/place?id=' + encodeURIComponent(currentId) + '&duplicate=1';
    } else if (action === 'delete') {
      if (!confirm('Delete this bet? This cannot be undone.')) return;
      const tile = tileFor(currentId);
      deleteBet(currentId);
      if (tile) tile.remove();
      close();
    }
  }

  function init() {
    build();
    // Delegate off document so tiles rendered later still trigger the modal.
    document.addEventListener('click', (e) => {
      const link = e.target.closest('[data-bet-edit]');
      if (!link) return;
      const tile = link.closest('.bet-tile');
      const id = tile && tile.dataset.betId;
      if (!id) return; // no id -> let the href navigate as a fallback
      e.preventDefault();
      open(id);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
