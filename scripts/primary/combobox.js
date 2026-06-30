// Lightweight custom combobox/dropdown, shared by all Bets form controls.
// Replaces native <datalist> (which can't control placement or item count).
//
//   attachCombobox(inputEl, () => ['Bills', ...], { selectOnly, capitalize })
//
// Options may be plain strings, or objects { label, value, search }:
//   label  = text shown in the dropdown
//   value  = what's written into the input when chosen (defaults to label)
//   search = text matched against the query (defaults to label); lets hidden
//            terms like a team abbreviation match without appearing in the list.
//
// - selectOnly: true  -> behaves like a <select> (input is read-only, shows the
//   full list, no free text). Used for League / Status.
// - selectOnly: false -> filterable autocomplete that still allows free text.
//   Used for Side / Opponent.
// At most 6 options are visible at once (the rest scroll). Pressing Enter
// commits the highlighted option and never submits the surrounding form.

function _normalizeOption(o) {
  if (o && typeof o === 'object') {
    const label = o.label != null ? o.label : '';
    return {
      label: label,
      value: o.value != null ? o.value : label,
      search: String(o.search != null ? o.search : label).toLowerCase(),
    };
  }
  return { label: String(o), value: String(o), search: String(o).toLowerCase() };
}

function attachCombobox(input, optionsProvider, options) {
  const opts = options || {};
  const selectOnly = !!opts.selectOnly;

  // Wrap the input so the menu can be positioned against it.
  const wrap = document.createElement('div');
  wrap.className = 'combo' + (selectOnly ? ' combo-select' : '') + (opts.capitalize ? ' combo-cap' : '');
  input.parentNode.insertBefore(wrap, input);
  wrap.appendChild(input);
  if (selectOnly) input.setAttribute('readonly', 'readonly');
  input.setAttribute('autocomplete', 'off');

  const menu = document.createElement('div');
  menu.className = 'combo-menu';
  wrap.appendChild(menu);

  let filtered = [];
  let active = -1;
  let open = false;

  function getFiltered() {
    const all = (optionsProvider() || []).map(_normalizeOption);
    const f = selectOnly ? '' : input.value.trim().toLowerCase();
    if (!f) return all;
    return all.filter(o => o.search.includes(f));
  }

  function render() {
    filtered = getFiltered();
    if (!filtered.length) {
      menu.innerHTML = '<div class="combo-empty">No matches — free text is fine</div>';
      return;
    }
    menu.innerHTML = filtered.map((o, i) =>
      '<div class="combo-option' + (i === active ? ' active' : '') + '" data-i="' + i + '">' +
        String(o.label).replace(/&/g, '&amp;').replace(/</g, '&lt;') +
      '</div>'
    ).join('');
  }

  function openMenu() {
    if (open) return;
    open = true;
    active = -1;
    render();
    menu.classList.add('open');
  }
  function closeMenu() {
    open = false;
    menu.classList.remove('open');
  }
  function choose(opt) {
    input.value = opt.value;
    closeMenu();
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }
  function move(delta) {
    if (!open) { openMenu(); }
    if (!filtered.length) return;
    active = (active + delta + filtered.length) % filtered.length;
    render();
    const activeEl = menu.querySelector('.combo-option.active');
    if (activeEl) activeEl.scrollIntoView({ block: 'nearest' });
  }

  input.addEventListener('focus', () => { openMenu(); });
  input.addEventListener('click', () => { openMenu(); render(); });
  if (!selectOnly) {
    input.addEventListener('input', () => { active = -1; openMenu(); render(); });
  }
  input.addEventListener('blur', () => { setTimeout(closeMenu, 150); });

  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); move(1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); move(-1); }
    else if (e.key === 'Enter') {
      // Commit the field; never submit the form.
      e.preventDefault();
      if (open && active >= 0 && filtered[active] != null) choose(filtered[active]);
      else closeMenu();
    } else if (e.key === 'Escape') {
      closeMenu();
    }
  });

  // Mousedown (not click) so it fires before the input's blur closes the menu.
  menu.addEventListener('mousedown', (e) => {
    const optEl = e.target.closest('.combo-option');
    if (!optEl) return;
    e.preventDefault();
    choose(filtered[Number(optEl.dataset.i)]);
  });
}
