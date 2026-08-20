/* Baker's Buns notes — the published note store behind /football/bakers-buns,
 * and the admin modal that writes to it.
 *
 * The notes started as a one-off import of the "NFL 2026-27" Google Doc into
 * data/nfl_projections_2026.json. They now live in Supabase (see
 * scripts/sql/bun_notes.sql and api/bun-notes.py) so they can be added to and
 * corrected from the page itself; scripts/seed_bun_notes.py moved the doc's
 * notes across, and the JSON copy stays only as the fallback this file's
 * consumer renders when the API cannot be reached.
 *
 * Reading is public. Writing is admin-only — enforced on the server, with the
 * UI here merely declining to show controls that would 403 anyway.
 *
 * Depends on: scripts/base/auth.js (getUser / isAdmin) and
 * scripts/components/nfl-pickers.js (the team grid and week menu). Styles for
 * the modal and the bullets live in styles/primary/bakers-buns.css.
 */
(function (global) {
  'use strict';

  var API = '/api/bun-notes';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function admin() {
    return typeof isAdmin === 'function' && isAdmin();
  }

  /* ---------- the season, as one list ----------
   * A note is filed against a week, and "the whole season" is one of the
   * answers — the default one, in fact, since most of what gets written about a
   * team isn't about a particular Sunday. The preseason and the four playoff
   * rounds sit in the same list as the eighteen numbered weeks rather than
   * behind a separate phase control: the writer picks when it happened once,
   * and there is only ever one thing to pick. `short` is what the bullet's chip
   * shows, which is why it has to stay narrow. */
  var WEEKS = [{ value: 'all', label: 'General — no week', short: '' },
               { value: 'pre', label: 'Preseason', short: 'PRE', groupStart: true }];

  for (var w = 1; w <= 18; w++) {
    WEEKS.push({ value: String(w), label: 'Week ' + w, short: 'W' + w, groupStart: w === 1 });
  }

  [['wc', 'Wild Card', 'WC'], ['div', 'Divisional', 'DIV'],
   ['conf', 'Conference', 'CONF'], ['sb', 'Super Bowl', 'SB']]
    .forEach(function (r, i) {
      WEEKS.push({ value: r[0], label: r[1], short: r[2], groupStart: i === 0 });
    });

  var WEEK_BY_VALUE = {};
  WEEKS.forEach(function (o, i) { o.index = i; WEEK_BY_VALUE[o.value] = o; });

  function weekOpt(value) {
    return WEEK_BY_VALUE[String(value)] || WEEK_BY_VALUE.all;
  }

  /* ---------- source links ----------
   * The Sources section of the page is a hand-written list of X posts, each
   * shown as its handle. A note's source is the same thing at bullet scale, so
   * it is parsed the same way: out of the URL. X's oEmbed needs an API key, so
   * there is no fetching the post's text or its author's display name — the
   * handle in the link is all there is, and it is enough to say where a note
   * came from. The server re-parses this and stores nothing it can't verify. */
  var X_POST = /^https?:\/\/(?:www\.)?(?:x|twitter)\.com\/([A-Za-z0-9_]{1,15})\/status(?:es)?\/(\d+)/i;

  function parseXLink(url) {
    var m = X_POST.exec(String(url || '').trim());
    return m ? { url: String(url).trim(), handle: m[1] } : null;
  }

  /* ---------- the store ----------
   * One fetch on load, held in memory. There are a few hundred notes across the
   * league at most, and every team card wants its own slice of them, so the
   * page reads from here rather than going back to the network per team. */

  var notes = [];
  var loaded = false;

  function sortNotes(list) {
    return list.slice().sort(function (a, b) {
      var d = weekOpt(a.week).index - weekOpt(b.week).index;
      if (d) return d;
      // Within a week, the doc's own ordering first (the seeded notes carry it),
      // then the order they were written in.
      var ao = typeof a.order === 'number' ? a.order : 1e9;
      var bo = typeof b.order === 'number' ? b.order : 1e9;
      if (ao !== bo) return ao - bo;
      return String(a.createdAt || '').localeCompare(String(b.createdAt || ''));
    });
  }

  function bunNotesLoad() {
    return fetch(API, { cache: 'no-store' })
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (rows) {
        notes = Array.isArray(rows) ? rows : [];
        loaded = true;
        return true;
      })
      .catch(function () {
        // Left false so the page knows to fall back to the notes committed in
        // data/nfl_projections_2026.json rather than showing a team no notes.
        loaded = false;
        return false;
      });
  }

  function bunNotesLoaded() { return loaded; }

  function bunNotesFor(team, kind) {
    kind = kind || 'note';
    return sortNotes(notes.filter(function (n) {
      return n.team === team && (n.kind || 'note') === kind;
    }));
  }

  // Notes filed with no team: about the league, not about a club.
  function bunNotesLeague() { return bunNotesFor(''); }

  function bunNoteById(id) {
    return notes.filter(function (n) { return n.id === id; })[0] || null;
  }

  function stash(saved) {
    (saved || []).forEach(function (n) {
      var i = -1;
      notes.forEach(function (x, j) { if (x.id === n.id) i = j; });
      if (i === -1) notes.push(n); else notes[i] = n;
    });
  }

  /* ---------- network ---------- */

  function authHeaders(base) {
    var user = typeof getUser === 'function' ? getUser() : null;
    var headers = base || {};
    if (user) headers['X-User-Id'] = user.user_id;
    return headers;
  }

  // Unlike the bets writes, these are not fire-and-forget: a note that silently
  // failed to save is a note the writer believes is published.
  function bunNotesSave(list) {
    return fetch(API, {
      method: 'PUT',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ notes: list })
    }).then(function (r) {
      return r.json().then(function (body) {
        if (!r.ok) throw new Error(body && body.error ? body.error : 'HTTP ' + r.status);
        stash(body.notes);
        return body.notes;
      });
    });
  }

  function bunNotesDelete(id) {
    return fetch(API + '?id=' + encodeURIComponent(id), {
      method: 'DELETE',
      headers: authHeaders()
    }).then(function (r) {
      return r.json().then(function (body) {
        if (!r.ok) throw new Error(body && body.error ? body.error : 'HTTP ' + r.status);
        notes = notes.filter(function (n) { return n.id !== id; });
        return true;
      });
    });
  }

  function newNoteId() {
    return 'n_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
  }

  /* ---------- rendering ----------
   * The bullet is built here rather than on the page so the team card and the
   * league block cannot drift apart, and so the edit affordance is attached in
   * exactly one place. */
  function bunNoteBullet(note) {
    var wk = weekOpt(note.week).short;
    var src = note.source && note.source.url
      ? ' <a class="tc-note-src" href="' + esc(note.source.url) + '" target="_blank" ' +
        'rel="noopener">@' + esc(note.source.handle || 'link') + '</a>'
      : '';
    var edit = admin()
      ? ' <button type="button" class="tc-note-edit" data-note-edit="' + esc(note.id) +
        '" title="Edit note" aria-label="Edit note">' +
        '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
        'stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
        '<path d="M12 20h9"></path>' +
        '<path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"></path></svg></button>'
      : '';
    return '<li data-note-id="' + esc(note.id) + '">' +
      (wk ? '<span class="tc-note-wk">' + esc(wk) + '</span>' : '') +
      esc(note.text) + src + edit + '</li>';
  }

  function bunNoteList(list) {
    if (!list.length) return '';
    return '<ul class="tc-notes">' + list.map(bunNoteBullet).join('') + '</ul>';
  }

  /* ---------- the modal ----------
   * Built once and appended to <body>, like the bet quick-edit modal, so that
   * bullets rendered later — every team card is rendered on open — still find
   * it. A native <dialog>, matching the team card's: Esc, an inert page and a
   * styleable backdrop for free. */

  var dlg, rowsEl, srcInput, srcHint, errEl, titleEl, deleteBtn;
  var teamBtn, teamGrid, teamDd, weekBtn, weekMenu, weekDd;
  var teams = [];
  var draft = { team: '', week: 'all' };
  var editing = null;          // the note being edited, or null when adding
  var onSaved = function () {};

  function ICON_CLOSE() {
    return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      '<path d="M18 6 6 18"></path><path d="m6 6 12 12"></path></svg>';
  }

  function build() {
    dlg = document.createElement('dialog');
    dlg.className = 'bn-modal';
    dlg.id = 'bn-modal';
    dlg.setAttribute('aria-label', 'Add notes');
    dlg.innerHTML =
      '<div class="bn-head">' +
        '<h4 class="bn-title">Add notes</h4>' +
        '<button type="button" class="bn-close" data-close aria-label="Close">' + ICON_CLOSE() + '</button>' +
      '</div>' +
      '<div class="bn-body">' +
        '<div class="dd-row">' +
          '<div class="dd" data-dd="team">' +
            '<button type="button" class="dd-btn" aria-haspopup="dialog" aria-expanded="false">' +
              '<span class="dd-value">League-wide</span></button>' +
            '<div class="dd-pop dd-overlay" role="dialog" aria-modal="true" aria-label="Team" hidden>' +
              '<div class="tp"></div></div>' +
          '</div>' +
          // Both pickers open over the page rather than under their trigger.
          // The team grid always did; the week list has to here, because an
          // anchored panel inside this dialog is clipped by the body's own
          // scroller — a fixed overlay is clipped by nothing.
          '<div class="dd" data-dd="week">' +
            '<button type="button" class="dd-btn" aria-haspopup="dialog" aria-expanded="false">' +
              '<span class="dd-value">General — no week</span></button>' +
            '<div class="dd-pop dd-overlay" role="dialog" aria-modal="true" aria-label="Week" hidden>' +
              '<div class="dd-menu" role="menu"></div></div>' +
          '</div>' +
        '</div>' +
        '<div class="bn-rows"></div>' +
        '<label class="bn-label" for="bn-src">Source <span>optional &mdash; an X post</span></label>' +
        '<input type="url" id="bn-src" class="bn-input" placeholder="https://x.com/handle/status/…" ' +
          'autocomplete="off" spellcheck="false">' +
        '<p class="bn-hint"></p>' +
      '</div>' +
      '<p class="bn-error" hidden></p>' +
      '<div class="bn-actions">' +
        '<button type="button" class="bn-btn is-danger" data-act="delete" hidden>Delete</button>' +
        '<button type="button" class="bn-btn" data-close>Cancel</button>' +
        '<button type="button" class="bn-btn is-primary" data-act="save">Save</button>' +
      '</div>';
    document.body.appendChild(dlg);

    titleEl = dlg.querySelector('.bn-title');
    rowsEl = dlg.querySelector('.bn-rows');
    srcInput = dlg.querySelector('#bn-src');
    srcHint = dlg.querySelector('.bn-hint');
    errEl = dlg.querySelector('.bn-error');
    deleteBtn = dlg.querySelector('[data-act="delete"]');

    var teamRoot = dlg.querySelector('[data-dd="team"]');
    var weekRoot = dlg.querySelector('[data-dd="week"]');
    teamBtn = teamRoot.querySelector('.dd-btn');
    teamGrid = teamRoot.querySelector('.tp');
    weekBtn = weekRoot.querySelector('.dd-btn');
    weekMenu = weekRoot.querySelector('.dd-menu');

    buildWeekMenu(weekMenu, WEEKS);
    teamDd = registerDropdown(teamRoot);
    weekDd = registerDropdown(weekRoot);

    weekMenu.addEventListener('click', function (e) {
      var opt = e.target.closest ? e.target.closest('.dd-opt') : null;
      if (!opt) return;
      draft.week = opt.getAttribute('data-week');
      closeDropdown(weekDd, true);
      syncDraft();
    });

    teamGrid.addEventListener('click', function (e) {
      var btn = e.target.closest ? e.target.closest('.tp-team, .tp-any') : null;
      if (!btn) return;
      draft.team = btn.getAttribute('data-team') || '';
      closeDropdown(teamDd, true);
      syncDraft();
    });

    dlg.addEventListener('click', function (e) {
      if (e.target === dlg || e.target.closest('[data-close]')) { close(); return; }
      var act = e.target.closest('[data-act]');
      if (act && act.dataset.act === 'save') save();
      if (act && act.dataset.act === 'delete') removeNote();
      var add = e.target.closest('[data-row-add]');
      if (add) addRow('', true);
      var del = e.target.closest('[data-row-del]');
      if (del) { del.closest('.bn-row').remove(); syncRows(); }
    });

    // Escape belongs to whichever picker is open before it belongs to the
    // dialog — otherwise closing the team grid closes the whole note with it.
    dlg.addEventListener('cancel', function (e) {
      if (anyDropdownOpen()) { e.preventDefault(); closeAllDropdowns(); }
    });

    dlg.addEventListener('close', function () {
      ScrollLock.unlock();
      closeAllDropdowns();
    });

    rowsEl.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter') return;
      e.preventDefault();
      if (e.metaKey || e.ctrlKey || editing) { save(); return; }
      addRow('', true);
    });

    srcInput.addEventListener('input', syncSource);
  }

  /* One note per row. The first row carries the "+" that adds another, because
   * that is where a writer already is when they realise they have a second
   * thing to say; every row after it carries the "×" that takes it back out. */
  function rowHtml(text, first) {
    return '<div class="bn-row">' +
      '<input type="text" class="bn-input" value="' + esc(text) + '" ' +
        'placeholder="' + (first ? 'Write a note…' : 'And another…') + '" ' +
        'autocomplete="off">' +
      (first
        ? '<button type="button" class="bn-row-btn" data-row-add title="Add another note" ' +
          'aria-label="Add another note">+</button>'
        : '<button type="button" class="bn-row-btn" data-row-del title="Remove this note" ' +
          'aria-label="Remove this note">&times;</button>') +
      '</div>';
  }

  function addRow(text, focus) {
    rowsEl.insertAdjacentHTML('beforeend', rowHtml(text || '', !rowsEl.children.length));
    if (focus) rowsEl.lastElementChild.querySelector('input').focus();
  }

  // After a removal the surviving rows are renumbered, so that the "+" is
  // always on the first one.
  function syncRows() {
    var rows = rowsEl.querySelectorAll('.bn-row');
    if (!rows.length) { addRow('', false); return; }
    var texts = [].map.call(rows, function (r) { return r.querySelector('input').value; });
    rowsEl.innerHTML = texts.map(function (t, i) { return rowHtml(t, i === 0); }).join('');
  }

  function syncDraft() {
    syncTeamPicker(teamBtn, teamGrid, draft.team, teams, { emptyLabel: 'League-wide' });
    syncWeekMenu(weekBtn, weekMenu, draft.week, weekOpt(draft.week).label);
  }

  function syncSource() {
    var raw = srcInput.value.trim();
    if (!raw) { srcHint.textContent = ''; srcHint.className = 'bn-hint'; return; }
    var parsed = parseXLink(raw);
    srcHint.textContent = parsed
      ? '@' + parsed.handle
      : 'Not an X post link — expected x.com/handle/status/…';
    srcHint.className = 'bn-hint' + (parsed ? ' is-ok' : ' is-bad');
  }

  function fail(message) {
    errEl.textContent = message;
    errEl.hidden = !message;
  }

  function open(opts) {
    opts = opts || {};
    editing = opts.note || null;
    fail('');

    draft.team = editing ? (editing.team || '') : (opts.team || '');
    draft.week = editing ? (editing.week || 'all') : (opts.week || 'all');

    titleEl.textContent = editing ? 'Edit note' : 'Add notes';
    dlg.setAttribute('aria-label', titleEl.textContent);
    deleteBtn.hidden = !editing;

    rowsEl.innerHTML = '';
    addRow(editing ? editing.text : '', false);

    srcInput.value = editing && editing.source ? editing.source.url : '';
    syncSource();
    syncDraft();

    dlg.showModal();
    // Taken after showModal so a double-open — which throws — cannot take a
    // lock nothing will release. See scripts/base/scroll-lock.js.
    ScrollLock.lock();
    rowsEl.querySelector('input').focus();
  }

  function close() {
    if (dlg.open) dlg.close();
  }

  function save() {
    var texts = [].map.call(rowsEl.querySelectorAll('input'), function (i) {
      return i.value.trim();
    }).filter(Boolean);

    if (!texts.length) { fail('Write a note first.'); return; }

    var raw = srcInput.value.trim();
    var source = raw ? parseXLink(raw) : null;
    if (raw && !source) { fail('That source is not an X post link.'); return; }

    // One source for the batch: several bullets saved together came off the
    // same post. Editing one note edits that note's own link.
    var payload = texts.map(function (text) {
      var note = {
        id: editing ? editing.id : newNoteId(),
        team: draft.team,
        week: draft.week,
        kind: editing ? (editing.kind || 'note') : 'note',
        text: text
      };
      if (editing && editing.createdAt) note.createdAt = editing.createdAt;
      if (editing && typeof editing.order === 'number') note.order = editing.order;
      if (source) note.source = source;
      return note;
    });

    fail('');
    dlg.classList.add('is-saving');
    bunNotesSave(payload)
      .then(function () {
        dlg.classList.remove('is-saving');
        close();
        onSaved();
      })
      .catch(function (e) {
        dlg.classList.remove('is-saving');
        fail(e.message || 'Could not save.');
      });
  }

  function removeNote() {
    if (!editing) return;
    if (!confirm('Delete this note? This cannot be undone.')) return;
    dlg.classList.add('is-saving');
    bunNotesDelete(editing.id)
      .then(function () {
        dlg.classList.remove('is-saving');
        close();
        onSaved();
      })
      .catch(function (e) {
        dlg.classList.remove('is-saving');
        fail(e.message || 'Could not delete.');
      });
  }

  /* ---------- wiring ----------
   * Called by the page once its team list has landed. Everything admin-only —
   * the floating button, the per-bullet pencils — is wired here and simply
   * never built for anyone else; the server is what actually refuses the write.
   */
  function initBunNotes(opts) {
    opts = opts || {};
    teams = opts.teams || [];
    onSaved = opts.onSaved || function () {};
    // Nothing that writes is offered while the store is unreachable: the page is
    // showing the JSON fallback then, and a note saved against it would vanish
    // into a list the reader cannot see.
    if (!admin() || !loaded) return;

    build();
    buildTeamPicker(teamGrid, teams, { anyLabel: 'League-wide — no team' });

    var fab = opts.fab || document.getElementById('bn-fab');
    if (fab) {
      fab.hidden = false;
      fab.addEventListener('click', function () { open({}); });
    }

    // Delegated off document: the pencils live inside a team card that is
    // rebuilt every time one opens, and the "add a note" buttons with them.
    document.addEventListener('click', function (e) {
      var edit = e.target.closest ? e.target.closest('[data-note-edit]') : null;
      if (edit) {
        var note = bunNoteById(edit.getAttribute('data-note-edit'));
        if (note) { if (opts.beforeOpen) opts.beforeOpen(); open({ note: note }); }
        return;
      }
      var add = e.target.closest ? e.target.closest('[data-note-add]') : null;
      if (add) {
        if (opts.beforeOpen) opts.beforeOpen();
        open({ team: add.getAttribute('data-note-add') || '' });
      }
    });
  }

  global.BUN_WEEKS = WEEKS;
  global.parseXLink = parseXLink;
  global.bunNotesLoad = bunNotesLoad;
  global.bunNotesLoaded = bunNotesLoaded;
  global.bunNotesFor = bunNotesFor;
  global.bunNotesLeague = bunNotesLeague;
  global.bunNoteById = bunNoteById;
  global.bunNoteBullet = bunNoteBullet;
  global.bunNoteList = bunNoteList;
  global.bunNotesSave = bunNotesSave;
  global.bunNotesDelete = bunNotesDelete;
  global.initBunNotes = initBunNotes;
  global.openBunNoteModal = open;
})(window);
