// Power Rankings cards.
//
// One controlled model drives the page: `model` is loaded from
// /api/power-rankings (the Supabase copy of record), every card is rendered
// from it, and every edit goes through update(), which swaps in a new model,
// re-renders and autosaves. Nothing reads card state back out of the DOM. Rank
// is array order; HP is derived from rank.
//
// Saves carry the version they were edited from and the server refuses a
// stale one (409), so no tab, script or deploy can overwrite newer cards. The
// seed file is only read while the table is still empty, and the first load
// saves it as version 1.

const API_URL = '/api/power-rankings';
const SEED_URL = '/data/power_rankings_seed.json';
// Unsaved edits, tagged with the version they started from, so a reload can
// pick them back up. A draft from an older version can't be replayed safely;
// it moves to STRANDED_KEY for the editor to offer as a copy.
const DRAFT_KEY = 'dz_power_rankings_draft_v2';
const STRANDED_KEY = 'dz_power_rankings_stranded';
// Before the server copy existed, edits lived only here.
const LEGACY_DRAFT_KEY = 'dz_power_rankings_draft';

let model = null;
let index = 0;
let editing = false;
let version = 0;          // the server version `model` was edited from
let dirty = false;        // edits not yet on the server
let saving = false;
let saveError = '';
let saveTimer = 0;
let stranded = null;      // { model, reason } a draft that could not be applied

const els = {
  body: document.body,
  track: document.getElementById('pr-track'),
  dots: document.getElementById('pr-dots'),
  count: document.getElementById('pr-count'),
  title: document.getElementById('pr-title'),
  draft: document.getElementById('pr-draft'),
  toggle: document.getElementById('pr-edit-toggle'),
  editor: document.getElementById('pr-editor'),
  modal: document.getElementById('pr-modal'),
  modalTitle: document.getElementById('pr-modal-title'),
  modalBody: document.getElementById('pr-modal-body'),
};

// ---------- helpers ----------

function escapeHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// Move text allows *italic*, the one bit of markup Rankings.md leaned on.
function richText(s) {
  return escapeHtml(s).replace(/\*([^*]+)\*/g, '<em>$1</em>');
}

function safeUrl(u) {
  if (!u || !String(u).trim()) return '';
  try {
    const url = new URL(u, location.href);
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : '';
  } catch (e) {
    return '';
  }
}

// youtu.be/ID, watch?v=ID, shorts/ID, embed/ID → ID; anything else → ''.
function youtubeId(u) {
  if (!u) return '';
  const m = String(u).match(/(?:youtu\.be\/|[?&]v=|\/shorts\/|\/embed\/)([\w-]{11})/);
  return m ? m[1] : '';
}

// instagram.com/reel/ID or /p/ID → its embed page; anything else → ''.
// Instagram has no public thumbnail, so these cards need an `image` poster.
function instagramEmbed(u) {
  const m = String(u || '').match(/instagram\.com\/(reel|p)\/([\w-]+)/);
  return m ? `https://www.instagram.com/${m[1]}/${m[2]}/embed/` : '';
}

// The share link's start time (?t=34, &t=1m2s, &start=34) in seconds, or 0.
function youtubeStart(u) {
  const m = String(u || '').match(/[?&](?:t|start)=(?:(\d+)h)?(?:(\d+)m)?(\d+)?s?(?:&|$)/);
  return m ? (+m[1] || 0) * 3600 + (+m[2] || 0) * 60 + (+m[3] || 0) : 0;
}

function readStored(key) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch (e) {
    return null;
  }
}

function writeStored(key, value) {
  try {
    if (value == null) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(value));
  } catch (e) { /* private mode */ }
}

const isDeck = m => !!m && Array.isArray(m.cards) && Array.isArray(m.tiers);

function writeDraft() {
  writeStored(DRAFT_KEY, { version, model });
}

function clearDraft() {
  writeStored(DRAFT_KEY, null);
}

function strand(m, reason) {
  stranded = { model: m, reason };
  writeStored(STRANDED_KEY, stranded);
}

function tierOf(card) {
  return model.tiers.find(t => t.id === card.tier) || model.tiers[model.tiers.length - 1];
}

function canEdit() {
  if (new URLSearchParams(location.search).has('edit')) return true;
  const role = typeof getUser === 'function' ? (getUser() || {}).role : null;
  return role === 'editor' || role === 'admin';
}

// ---------- energy glyphs ----------

const GLYPHS = {
  // crown
  queen: '<path d="M3 17h18l-1.5-9-4.5 4-3-6-3 6-4.5-4z" fill="currentColor"/><rect x="3.5" y="18.5" width="17" height="2" rx="1" fill="currentColor"/>',
  // stinger
  hornets: '<path d="M12 2c3.5 4 6 7.5 6 11a6 6 0 0 1-12 0c0-3.5 2.5-7 6-11z" fill="currentColor"/><path d="M12 19v4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  // striped abdomen
  wasps: '<ellipse cx="12" cy="12" rx="6.5" ry="9" fill="none" stroke="currentColor" stroke-width="2"/><path d="M6 9h12M5.6 13h12.8M7 17h10" stroke="currentColor" stroke-width="2.4"/>',
  // leaf
  notbees: '<path d="M5 19C5 10 11 5 20 4c-1 9-6 15-15 15z" fill="currentColor"/><path d="M5 19l8-8" stroke="rgba(0,0,0,.35)" stroke-width="1.6" stroke-linecap="round"/>',
  // colorless star
  none: '<path d="M12 3l2.6 5.6 6.1.7-4.5 4.2 1.2 6L12 16.6 6.6 19.5l1.2-6-4.5-4.2 6.1-.7z" fill="currentColor"/>',
};

function energy(tierId) {
  const id = GLYPHS[tierId] ? tierId : 'none';
  return `<span class="pr-energy" data-tier="${id}"><svg viewBox="0 0 24 24" aria-hidden="true">${GLYPHS[id]}</svg></span>`;
}

const ICON_OUT = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 17L17 7M8 7h9v9"/></svg>';
const ICON_NOTE = '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M9 17.5V5l11-2v12.5a3 3 0 1 1-2-2.8V7.3l-7 1.3v8.9a3 3 0 1 1-2-2.8z"/></svg>';

// ---------- card rendering ----------

function moveHtml(move, ci, mi, tier) {
  const cost = Math.max(1, Math.min(4, parseInt(move.cost, 10) || 1));
  const costIcons = Array.from({ length: cost }, (_, k) => energy(k === 0 ? tier.id : 'none')).join('');
  const links = (move.links || [])
    .map(l => ({ label: l.label || l.url, href: safeUrl(l.url) }))
    .filter(l => l.href)
    .map(l => `<a class="pr-link" href="${escapeHtml(l.href)}" target="_blank" rel="noopener">${ICON_OUT}<span>${escapeHtml(l.label)}</span></a>`);
  if (move.modal && (move.modal.body || move.modal.title)) {
    links.push(`<button class="pr-link" type="button" data-modal="${ci}:${mi}">${ICON_NOTE}<span>${escapeHtml(move.modal.label || 'Read more')}</span></button>`);
  }
  const hasText = !!(move.text && move.text.trim());
  return `
    <div class="pr-move">
      <div class="pr-cost">${costIcons}</div>
      <div class="pr-move-body${!hasText && !links.length ? ' pr-move-only-name' : ''}">
        <div class="pr-move-name">${escapeHtml(move.name || 'Untitled move')}</div>
        ${hasText ? `<div class="pr-move-text">${richText(move.text)}</div>` : ''}
        ${links.length ? `<div class="pr-links">${links.join('')}</div>` : ''}
      </div>
      <div class="pr-dmg">${escapeHtml(move.damage || '')}</div>
    </div>`;
}

function statValue(v) {
  if (!v) return '';
  return GLYPHS[v] ? energy(v) : escapeHtml(v);
}

// What the art window shows before anything is tapped: the card's own image,
// else its video's thumbnail.
function posterOf(card) {
  const yt = youtubeId(card.video);
  return safeUrl(card.image) || (yt ? `https://i.ytimg.com/vi/${yt}/hqdefault.jpg` : '');
}

function cardHtml(card, i) {
  const n = model.cards.length;
  const tier = tierOf(card);
  const hp = (n - i) * 10;
  const yt = youtubeId(card.video);
  const ig = yt ? '' : instagramEmbed(card.video);
  const poster = posterOf(card);
  const title = card.name || card.nickname || 'Unnamed';
  const titleLen = title.length;
  const art = poster
    ? `<img src="${escapeHtml(poster)}" alt="${escapeHtml(title)}" decoding="async" referrerpolicy="no-referrer" draggable="false">`
    : `<div class="pr-art-placeholder">${energy(tier.id)}<span>${escapeHtml(tier.name)}</span></div>`;
  const moves = (card.moves || []).map((m, mi) => moveHtml(m, i, mi, tier)).join('')
    || '<p class="pr-empty">No moves yet. Still charging up.</p>';
  // "Evolves from": the pre-evolution portrait tab in the top-left corner.
  const evo = card.evolvesFrom && card.evolvesFrom.name ? card.evolvesFrom : null;
  const evoImg = evo ? safeUrl(evo.image) : '';

  return `
    <article class="pr-card" data-tier="${escapeHtml(tier.id)}" aria-label="${escapeHtml(`#${i + 1} ${title}`)}">
      <div class="pr-face${evo ? ' has-evo' : ''}">
        ${evo ? `<div class="pr-evo" aria-hidden="true">
          <span class="pr-evo-stage">${escapeHtml(tier.stage || '')}</span>
          <span class="pr-evo-frame">${evoImg ? `<img src="${escapeHtml(evoImg)}" alt="" decoding="async" referrerpolicy="no-referrer" draggable="false">` : ''}</span>
        </div>` : ''}
        <div class="pr-top">
          ${evo
            ? `<span class="pr-evo-from">Evolves from ${escapeHtml(evo.name)}</span>`
            : `<span class="pr-stage-badge">${escapeHtml(tier.stage || '')} · ${escapeHtml(tier.name)}</span>`}
          <span>#${i + 1}</span>
        </div>
        <div class="pr-headline">
          <h2 class="pr-name${titleLen > 24 ? ' is-long' : titleLen > 13 ? ' is-mid' : ''}">${escapeHtml(title)}</h2>
          <span class="pr-hp">${hp}<small>HP</small></span>
          ${energy(tier.id)}
        </div>
        <p class="pr-nick">${card.name && card.nickname ? escapeHtml(card.nickname) : ''}</p>
        <div class="pr-art${tier.holo ? ' is-holo' : ''}">
          <div class="pr-art-inner">
            ${art}
            ${yt ? `<button class="pr-play" type="button" data-play="${yt}" data-start="${youtubeStart(card.video)}" aria-label="Play video">
              <svg viewBox="0 0 68 48" aria-hidden="true"><path d="M66.5 7.7a8.5 8.5 0 0 0-6-6C55.2.3 34 .3 34 .3s-21.2 0-26.5 1.4a8.5 8.5 0 0 0-6 6C.1 13 .1 24 .1 24s0 11 1.4 16.3a8.5 8.5 0 0 0 6 6c5.3 1.4 26.5 1.4 26.5 1.4s21.2 0 26.5-1.4a8.5 8.5 0 0 0 6-6C67.9 35 67.9 24 67.9 24s0-11-1.4-16.3z" fill="#e33"/><path d="M27 34V14l18 10z" fill="#fff"/></svg>
            </button>` : ig ? `<button class="pr-play" type="button" data-reel="${escapeHtml(ig)}" data-title="${escapeHtml(title)}" aria-label="Play reel">
              <svg viewBox="0 0 48 48" aria-hidden="true"><circle cx="24" cy="24" r="23" fill="rgba(0,0,0,.55)" stroke="#fff" stroke-width="2"/><path d="M19 15v18l15-9z" fill="#fff"/></svg>
            </button>` : ''}
          </div>
        </div>
        <div class="pr-strip">${escapeHtml(tier.name)} Manager. Rank: ${i + 1} of ${n}.</div>
        <div class="pr-moves">${moves}</div>
        <div class="pr-stats">
          <div>weakness<span class="pr-stat-val">${statValue(card.weakness)}</span></div>
          <div>resistance<span class="pr-stat-val">${statValue(card.resistance)}</span></div>
        </div>
        <div class="pr-flavor">${richText(card.flavor || tier.tagline || '')}</div>
        <div class="pr-foot">
          <span>Illus. Dynast-Z · ${escapeHtml(model.edition || '')}</span>
          <span>${i + 1}/${n} ${tier.holo ? '★' : '●'}</span>
        </div>
      </div>
    </article>`;
}

// Slide position ↔ card index. Rank is always array order; a countdown model
// just lays the deck out backwards, #N first and #1 last. Self-inverse.
function slot(i) {
  return model.countdown ? model.cards.length - 1 - i : i;
}

function renderAll() {
  const n = model.cards.length;
  index = Math.max(0, Math.min(index, n - 1));
  els.title.textContent = model.title || 'Power Rankings';
  document.title = `${model.title || 'Power Rankings'} | Dynast-Z`;
  const order = model.cards.map((_, p) => slot(p));
  els.track.innerHTML = order.map(i => {
    const c = model.cards[i];
    return `<section class="pr-slide" id="card-${escapeHtml(c.id)}" aria-roledescription="slide" aria-label="#${i + 1} of ${n}"></section>`;
  }).join('');
  els.dots.innerHTML = order.map(i => {
    const c = model.cards[i];
    return `<button class="pr-dot" type="button" data-go="${i}" style="--dot:var(--dot-${escapeHtml(tierOf(c).id)})" aria-label="${escapeHtml(`#${i + 1} ${c.name || c.nickname}`)}"></button>`;
  }).join('');
  renderSaveState();
  playing = -1;
  layout(false);
  markCurrent();
}

// A field edit only changes one card, so only that slide is redrawn; the
// editor's inputs are left alone and keep focus.
function renderSlide(i) {
  const slide = els.track.children[slot(i)];
  if (slide && slide.dataset.mounted) slide.innerHTML = cardHtml(model.cards[i], i);
}

function markCurrent() {
  if (playing >= 0 && playing !== index) stopVideo();
  const n = model.cards.length;
  els.count.textContent = `#${index + 1} of ${n} · ${model.cards[index] ? model.cards[index].name || model.cards[index].nickname : ''}`;
  [...els.dots.children].forEach(d => d.setAttribute('aria-current', +d.dataset.go === index ? 'true' : 'false'));
  const card = model.cards[index];
  if (card) history.replaceState(null, '', `${location.pathname}${location.search}#${card.id}`);
}

// ---------- the deck ----------
//
// Not a strip: the slides are stacked. The current card is on top, the next two
// sit under it, and every card already played has been thrown off the table in
// the direction it was flung (remembered per card, so going back brings it in
// from the same side). `k` is a slide's distance from the top of the deck.

const exits = {};
const DEFAULT_EXIT = { x: -1, y: -0.12 };

function slideTransform(k, exit) {
  if (k < 0) {
    const d = Math.hypot(innerWidth, innerHeight) * 1.1;
    return `translate(${exit.x * d}px, ${exit.y * d}px) rotate(${exit.x * 28}deg)`;
  }
  const depth = Math.min(k, 2);
  return `translateY(${depth * 22}px) scale(${1 - depth * 0.04})`;
}

// Only the cards that can be seen are in the DOM: the one just thrown (so it
// can come back), the top card and the two under it. Every other slide is an
// empty shell that keeps its place and transform; it is filled when it comes
// within reach and emptied when it leaves.
const MOUNT_BEHIND = 1;
const MOUNT_AHEAD = 2;

function layout(animate = true) {
  const top = slot(index);
  [...els.track.children].forEach((slide, p) => {
    const k = p - top;
    const near = k >= -MOUNT_BEHIND && k <= MOUNT_AHEAD;
    if (near && !slide.dataset.mounted) {
      slide.innerHTML = cardHtml(model.cards[slot(p)], slot(p));
      slide.dataset.mounted = '1';
    } else if (!near && slide.dataset.mounted) {
      if (playing === slot(p)) playing = -1;
      slide.innerHTML = '';
      delete slide.dataset.mounted;
    }
    slide.classList.toggle('is-under', k === 1);
    slide.style.transition = animate ? '' : 'none';
    slide.style.transform = slideTransform(k, exits[model.cards[slot(p)].id] || DEFAULT_EXIT);
    // Thrown cards ride above the deck on their way out (and back in).
    slide.style.zIndex = String(k < 0 ? 200 + k : 100 - k);
    slide.style.opacity = k < -1 || k > 2 ? '0' : '1';
    slide.classList.toggle('is-top', k === 0);
    slide.setAttribute('aria-hidden', k === 0 ? 'false' : 'true');
  });
  if (!animate) void els.track.offsetWidth; // commit, so the next change animates
}

// One card forward or back in the order shown (down or up in rank when the
// deck counts down). Off either end, slot() clamps back via goTo.
function step(d) {
  goTo(slot(slot(index) + d));
}

function goTo(i, smooth = true) {
  index = Math.max(0, Math.min(i, model.cards.length - 1));
  layout(smooth);
  markCurrent();
  if (editing) renderEditor();
}

// ---------- the update path ----------

// Every edit goes through here. `structural` edits (add/remove/reorder) need
// the whole deck and the editor redrawn; plain field edits only the one slide.
function update(mutate, { structural = false } = {}) {
  const next = structuredClone(model);
  mutate(next);
  model = next;
  dirty = true;
  saveError = '';
  writeDraft();
  scheduleSave();
  if (structural) {
    renderAll();
  } else {
    renderSlide(index);
    renderSaveState();
  }
}

// ---------- saving ----------

function api(method, body) {
  const me = typeof getUser === 'function' ? getUser() : null;
  return fetch(API_URL, {
    method,
    cache: 'no-store',
    headers: { 'Content-Type': 'application/json', 'X-User-Id': me ? me.user_id : '' },
    body: body ? JSON.stringify(body) : undefined,
  });
}

function scheduleSave(delay = 700) {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(save, delay);
}

async function save() {
  if (!dirty) return;
  if (saving) { scheduleSave(300); return; }
  saving = true;
  dirty = false;
  const sent = model;
  renderSaveState();
  let retry = false;
  let saved = false;
  try {
    const res = await api('PUT', { model: sent, version });
    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      version = data.version;
      saveError = '';
      saved = true;
      if (dirty) writeDraft(); else clearDraft();
    } else if (res.status === 409) {
      // Saved from somewhere else since this copy loaded. Keep these edits
      // where they can be copied, and switch to the newer cards rather than
      // writing over them.
      saving = false;
      strand(model, `Saved elsewhere${data.updatedBy ? ` by ${data.updatedBy}` : ''} while you were editing, so these edits were not applied.`);
      clearDraft();
      dirty = false;
      await load();
      if (editing) renderEditor();
      return;
    } else {
      dirty = true;
      saveError = data.error || `Save failed (${res.status})`;
    }
  } catch (e) {
    dirty = true;
    saveError = 'Offline. Will retry.';
    retry = true;
  }
  saving = false;
  renderSaveState(saved);
  if (dirty && (retry || !saveError)) scheduleSave(retry ? 5000 : 300);
}

// The header's " · Saving…" / " · Saved" / " · Not saved" (hover for why).
let savedFlash = 0;
function renderSaveState(justSaved = false) {
  if (justSaved) {
    clearTimeout(savedFlash);
    savedFlash = setTimeout(() => { savedFlash = 0; renderSaveState(); }, 1500);
  }
  const text = saveError ? 'Not saved' : saving || dirty ? 'Saving…' : savedFlash ? 'Saved' : '';
  els.draft.textContent = text ? ` · ${text}` : '';
  els.draft.title = saveError;
  els.draft.hidden = !text;
}

function setPath(obj, path, value) {
  const keys = path.split('.');
  let o = obj;
  keys.slice(0, -1).forEach(k => { o = o[k] ?? (o[k] = {}); });
  o[keys[keys.length - 1]] = value;
}

function getPath(obj, path) {
  return path.split('.').reduce((o, k) => (o == null ? o : o[k]), obj);
}

// ---------- editor ----------

function field(label, path, { type = 'text', placeholder = '', area = false } = {}) {
  const v = getPath(model.cards[index], path);
  const val = escapeHtml(v == null ? '' : v);
  const ph = escapeHtml(placeholder);
  const input = area
    ? `<textarea data-path="${path}" placeholder="${ph}">${val}</textarea>`
    : `<input type="${type}" data-path="${path}" value="${val}" placeholder="${ph}"${type === 'number' ? ' min="0" max="4" inputmode="numeric"' : ''}>`;
  return `<label class="pr-field"><span>${label}</span>${input}</label>`;
}

function renderEditor() {
  const card = model.cards[index];
  if (!card) return;
  const n = model.cards.length;
  const tier = tierOf(card);
  const tierOptions = model.tiers.map(t =>
    `<option value="${escapeHtml(t.id)}"${t.id === card.tier ? ' selected' : ''}>${escapeHtml(t.name)}</option>`
  ).join('');

  const moves = (card.moves || []).map((m, mi) => `
    <div class="pr-move-ed">
      <div class="pr-move-ed-head">
        <span>Move ${mi + 1}</span>
        <button class="pr-btn pr-btn-icon pr-btn-sm" type="button" data-action="move-up" data-mi="${mi}" ${mi === 0 ? 'disabled' : ''} aria-label="Move up">↑</button>
        <button class="pr-btn pr-btn-icon pr-btn-sm" type="button" data-action="move-down" data-mi="${mi}" ${mi === card.moves.length - 1 ? 'disabled' : ''} aria-label="Move down">↓</button>
        <button class="pr-btn pr-btn-sm pr-btn-danger" type="button" data-action="move-remove" data-mi="${mi}">Remove</button>
      </div>
      <div class="pr-row pr-row-3">
        ${field('Name', `moves.${mi}.name`)}
        ${field('Damage', `moves.${mi}.damage`, { placeholder: '30' })}
        ${field('Cost', `moves.${mi}.cost`, { type: 'number' })}
      </div>
      ${field('Text', `moves.${mi}.text`, { area: true, placeholder: 'The review point. *italic* works.' })}
      ${(m.links || []).map((l, li) => `
        <div class="pr-link-ed">
          <input data-path="moves.${mi}.links.${li}.label" value="${escapeHtml(l.label)}" placeholder="Label" aria-label="Link label">
          <input type="url" data-path="moves.${mi}.links.${li}.url" value="${escapeHtml(l.url)}" placeholder="https://" aria-label="Link URL">
          <button class="pr-btn pr-btn-icon pr-btn-danger" type="button" data-action="link-remove" data-mi="${mi}" data-li="${li}" aria-label="Remove link">×</button>
        </div>`).join('')}
      ${m.modal ? `
        ${field('Modal button', `moves.${mi}.modal.label`, { placeholder: 'Read more' })}
        ${field('Modal title', `moves.${mi}.modal.title`)}
        ${field('Modal text', `moves.${mi}.modal.body`, { area: true })}` : ''}
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin:4px 0 10px">
        <button class="pr-btn pr-btn-sm" type="button" data-action="link-add" data-mi="${mi}">+ Link</button>
        <button class="pr-btn pr-btn-sm${m.modal ? ' pr-btn-danger' : ''}" type="button" data-action="modal-toggle" data-mi="${mi}">${m.modal ? 'Remove modal' : '+ Modal'}</button>
      </div>
    </div>`).join('');

  els.editor.innerHTML = `
    ${stranded ? `<div class="pr-ed-stranded" role="alert">
      <p>${escapeHtml(stranded.reason)}</p>
      <button class="pr-btn pr-btn-sm" type="button" data-action="stranded-copy">Copy those edits</button>
      <button class="pr-btn pr-btn-sm pr-btn-danger" type="button" data-action="stranded-discard">Dismiss</button>
    </div>` : ''}
    <div class="pr-ed-head">
      <h2>Card ${index + 1} of ${n}</h2>
      <button class="pr-btn pr-btn-icon" type="button" data-action="rank-up" ${index === 0 ? 'disabled' : ''} aria-label="Rank up">↑</button>
      <button class="pr-btn pr-btn-icon" type="button" data-action="rank-down" ${index === n - 1 ? 'disabled' : ''} aria-label="Rank down">↓</button>
      <button class="pr-btn" type="button" data-action="card-add">+ Card</button>
      <button class="pr-btn pr-btn-danger" type="button" data-action="card-remove">Delete</button>
      <span style="flex:1"></span>
      <button class="pr-btn pr-btn-primary" type="button" data-action="export">Export</button>
      <button class="pr-btn" type="button" data-action="copy">Copy</button>
    </div>

    <label class="pr-field"><span>Type (tier)</span><select data-path="tier">${tierOptions}</select></label>
    <div class="pr-row">
      ${field('Name', 'name')}
      ${field('Nickname', 'nickname')}
    </div>
    ${field('Image URL', 'image', { type: 'url', placeholder: '/assets/power-rankings/name.jpg or https://…' })}
    ${field('Video (YouTube or Instagram URL)', 'video', { type: 'url', placeholder: 'YouTube plays in the art window; Instagram in a pop-up' })}
    <div class="pr-row">
      ${field('Evolves from', 'evolvesFrom.name', { placeholder: 'Mike' })}
      ${field('Evolves from image', 'evolvesFrom.image', { type: 'url', placeholder: '/assets/power-rankings/name.jpg' })}
    </div>

    <div class="pr-ed-section"><span>Moves</span><button class="pr-btn pr-btn-sm" type="button" data-action="move-add">+ Move</button></div>
    ${moves || '<p class="pr-ed-note" style="margin-top:0">No moves yet.</p>'}

    <div class="pr-ed-section"><span>Card details</span></div>
    <div class="pr-row">
      ${field('Weakness', 'weakness', { placeholder: 'tier id or text' })}
      ${field('Resistance', 'resistance')}
    </div>
    ${field('Flavor text', 'flavor', { area: true, placeholder: tier.tagline || '' })}

    <p class="pr-ed-note">
      Edits save to the server as you type (version ${version}), the same copy every device and
      environment reads. <strong>Export</strong> or <strong>Copy</strong> for a backup.
      Weakness accepts a tier id (${model.tiers.map(t => `<code>${escapeHtml(t.id)}</code>`).join(', ')}) for an energy icon.
    </p>
  `;
}

function setEditing(on) {
  editing = on;
  els.body.classList.toggle('is-editing', on);
  els.editor.hidden = !on;
  els.toggle.setAttribute('aria-pressed', on ? 'true' : 'false');
  els.toggle.textContent = on ? 'Done' : 'Edit';
  if (on) renderEditor();
  // The stage just changed size; land back on the same card.
  requestAnimationFrame(() => goTo(index, false));
}

const NUMERIC = /(^|\.)cost$/;

els.editor.addEventListener('input', e => {
  const path = e.target.dataset && e.target.dataset.path;
  if (!path) return;
  const value = NUMERIC.test(path) ? (parseInt(e.target.value, 10) || 0) : e.target.value;
  // A tier change recolours the dots and the card, so redraw the deck.
  update(m => setPath(m.cards[index], path, value), { structural: path === 'tier' });
});

els.editor.addEventListener('click', e => {
  const btn = e.target.closest('[data-action]');
  if (!btn) return;
  const mi = parseInt(btn.dataset.mi, 10);
  const li = parseInt(btn.dataset.li, 10);
  const swap = (arr, a, b) => { [arr[a], arr[b]] = [arr[b], arr[a]]; };

  switch (btn.dataset.action) {
    case 'rank-up':
      update(m => swap(m.cards, index, index - 1), { structural: true }); goTo(index - 1, false); break;
    case 'rank-down':
      update(m => swap(m.cards, index, index + 1), { structural: true }); goTo(index + 1, false); break;
    case 'card-add': {
      const tier = model.cards[index] ? model.cards[index].tier : model.tiers[0].id;
      update(m => m.cards.splice(index + 1, 0, {
        id: 'card-' + Date.now().toString(36), tier, name: 'New Card', nickname: '', image: '', video: '',
        moves: [], weakness: '', resistance: '', flavor: '',
      }), { structural: true });
      goTo(index + 1, false);
      break;
    }
    case 'card-remove':
      if (model.cards.length > 1 && confirm(`Delete ${model.cards[index].name}'s card?`)) {
        update(m => m.cards.splice(index, 1), { structural: true });
      }
      break;
    case 'move-add':
      update(m => (m.cards[index].moves = m.cards[index].moves || []).push({ name: 'New Move', damage: '', cost: 1, text: '', links: [] }), { structural: true }); break;
    case 'move-remove':
      update(m => m.cards[index].moves.splice(mi, 1), { structural: true }); break;
    case 'move-up':
      update(m => swap(m.cards[index].moves, mi, mi - 1), { structural: true }); break;
    case 'move-down':
      update(m => swap(m.cards[index].moves, mi, mi + 1), { structural: true }); break;
    case 'link-add':
      update(m => { const mv = m.cards[index].moves[mi]; (mv.links = mv.links || []).push({ label: '', url: '' }); }, { structural: true }); break;
    case 'link-remove':
      update(m => m.cards[index].moves[mi].links.splice(li, 1), { structural: true }); break;
    case 'modal-toggle':
      update(m => {
        const mv = m.cards[index].moves[mi];
        if (mv.modal) delete mv.modal; else mv.modal = { label: 'Read more', title: mv.name || '', body: '' };
      }, { structural: true });
      break;
    case 'export': {
      const blob = new Blob([JSON.stringify(model, null, 2) + '\n'], { type: 'application/json' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'power_rankings_cards.json';
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
      break;
    }
    case 'copy':
      navigator.clipboard.writeText(JSON.stringify(model, null, 2) + '\n').then(() => {
        btn.textContent = 'Copied';
        setTimeout(() => { btn.textContent = 'Copy'; }, 1400);
      }, () => { btn.textContent = 'Copy failed'; });
      break;
    case 'stranded-copy':
      navigator.clipboard.writeText(JSON.stringify(stranded.model, null, 2) + '\n').then(() => {
        btn.textContent = 'Copied';
      }, () => { btn.textContent = 'Copy failed'; });
      break;
    case 'stranded-discard':
      if (confirm('Dismiss these unapplied edits? They can’t be recovered after this.')) {
        stranded = null;
        writeStored(STRANDED_KEY, null);
        renderEditor();
      }
      break;
  }
});

// ---------- deck interactions ----------

// Thrown cards sit a viewport's diagonal away; keep them there on resize.
window.addEventListener('resize', () => { if (model) layout(false); });

document.getElementById('pr-prev').addEventListener('click', () => step(-1));
document.getElementById('pr-next').addEventListener('click', () => step(1));

els.dots.addEventListener('click', e => {
  const b = e.target.closest('[data-go]');
  if (b) goTo(parseInt(b.dataset.go, 10));
});

// The dots are a scrubber too: press anywhere on the row and slide, and the
// deck follows the dot nearest the finger. (Click above still covers taps
// from a keyboard.)
let scrub = null;
function dotAt(x) {
  let best = null;
  let bestDist = Infinity;
  for (const d of els.dots.children) {
    const r = d.getBoundingClientRect();
    const dist = Math.abs(r.left + r.width / 2 - x);
    if (dist < bestDist) { best = d; bestDist = dist; }
  }
  return best ? parseInt(best.dataset.go, 10) : -1;
}
function scrubTo(e) {
  const i = dotAt(e.clientX);
  if (i >= 0 && i !== index) goTo(i);
}
els.dots.addEventListener('pointerdown', e => {
  if (e.button !== 0 || !e.isPrimary) return;
  scrub = e.pointerId;
  try { els.dots.setPointerCapture(e.pointerId); } catch (err) { /* pointer already gone */ }
  els.dots.classList.add('is-scrubbing');
  scrubTo(e);
});
els.dots.addEventListener('pointermove', e => {
  if (e.pointerId === scrub) scrubTo(e);
});
function endScrub(e) {
  if (e.pointerId !== scrub) return;
  scrub = null;
  els.dots.classList.remove('is-scrubbing');
}
els.dots.addEventListener('pointerup', endScrub);
els.dots.addEventListener('pointercancel', endScrub);

els.track.addEventListener('click', e => {
  const b = e.target.closest('[data-modal]');
  if (!b) return;
  const [ci, mi] = b.dataset.modal.split(':').map(Number);
  const modal = model.cards[ci].moves[mi].modal;
  els.modal.classList.remove('is-video');
  els.modalTitle.textContent = modal.title || model.cards[ci].moves[mi].name || '';
  els.modalBody.textContent = modal.body || '';
  els.modal.showModal();
  els.modalBody.scrollTop = 0;
});

// Tap the poster to swap in the player. Only one plays at a time, and it is
// torn down (by redrawing its slide) once the card is swiped away.
let playing = -1;
els.track.addEventListener('click', e => {
  const b = e.target.closest('[data-play]');
  if (!b) return;
  stopVideo();
  const slideIndex = slot([...els.track.children].indexOf(b.closest('.pr-slide')));
  const art = b.closest('.pr-art');
  art.classList.add('is-playing');
  art.querySelector('.pr-art-inner').innerHTML =
    `<iframe src="https://www.youtube-nocookie.com/embed/${encodeURIComponent(b.dataset.play)}?autoplay=1&playsinline=1&rel=0&start=${parseInt(b.dataset.start, 10) || 0}"
      title="YouTube video" allow="autoplay; encrypted-media; picture-in-picture; fullscreen" allowfullscreen></iframe>`;
  playing = slideIndex;
});

function stopVideo() {
  if (playing >= 0 && model.cards[playing]) renderSlide(playing);
  playing = -1;
}

els.modal.addEventListener('click', e => {
  if (e.target === els.modal) els.modal.close(); // backdrop tap
});

document.addEventListener('keydown', e => {
  if (els.modal.open || /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
  if (e.key === 'ArrowRight') step(1);
  if (e.key === 'ArrowLeft') step(-1);
});

// Grab the top card with a finger or mouse and it follows, tilting with the
// drag, while the card under it rises. Let go far or fast enough and it is
// thrown off along the flick (velocity over the last ~100ms, or the drag
// itself if the hand stopped) and the next card is on top; otherwise it
// springs back. A drag also eats the click it ends in, so letting go over a
// link doesn't open it.
let drag = null;
let dragClickGuard = false;

els.track.addEventListener('pointerdown', e => {
  if (e.button !== 0 || !e.isPrimary || e.target.closest('iframe')) return;
  const slide = e.target.closest('.pr-slide.is-top');
  if (!slide) return;
  drag = {
    id: e.pointerId, x: e.clientX, y: e.clientY, slide, moved: false,
    samples: [{ x: e.clientX, y: e.clientY, t: e.timeStamp }],
  };
});

window.addEventListener('pointermove', e => {
  if (!drag || e.pointerId !== drag.id) return;
  const dx = e.clientX - drag.x;
  const dy = e.clientY - drag.y;
  if (!drag.moved) {
    if (Math.hypot(dx, dy) < 8) return;
    drag.moved = true;
    try { els.track.setPointerCapture(drag.id); } catch (err) { /* pointer already gone */ }
    els.body.classList.add('is-dragging');
    drag.under = els.track.children[slot(index) + 1] || null;
    drag.slide.style.transition = 'none';
    if (drag.under) drag.under.style.transition = 'none';
    const card = drag.slide.querySelector('.pr-card');
    if (card) resetTilt(card);
  }
  drag.samples.push({ x: e.clientX, y: e.clientY, t: e.timeStamp });
  while (drag.samples.length > 2 && e.timeStamp - drag.samples[0].t > 100) drag.samples.shift();
  drag.slide.style.transform = `translate(${dx}px, ${dy}px) rotate(${dx * 0.05}deg)`;
  if (drag.under) {
    const p = Math.min(1, Math.hypot(dx, dy) / 220);
    drag.under.style.transform = `translateY(${22 * (1 - p)}px) scale(${0.96 + 0.04 * p})`;
  }
});

function endDrag(e) {
  if (!drag || e.pointerId !== drag.id) return;
  const d = drag;
  drag = null;
  if (!d.moved) return;
  dragClickGuard = true;
  setTimeout(() => { dragClickGuard = false; }, 0);
  els.body.classList.remove('is-dragging');
  d.slide.style.transition = '';
  if (d.under) d.under.style.transition = '';

  const dx = e.clientX - d.x;
  const dy = e.clientY - d.y;
  const first = d.samples[0];
  const last = d.samples[d.samples.length - 1];
  const dt = Math.max(1, last.t - first.t);
  const vx = (last.x - first.x) / dt;
  const vy = (last.y - first.y) / dt;
  const speed = Math.hypot(vx, vy);
  const dist = Math.hypot(dx, dy);
  const hasNext = slot(index) + 1 < model.cards.length;
  // A cancelled pointer (the browser took over to scroll) always springs back.
  const thrown = e.type !== 'pointercancel' && hasNext && (dist > 120 || (speed > 0.6 && dist > 50));
  if (thrown) {
    const [ux, uy] = speed > 0.6 ? [vx, vy] : [dx, dy];
    const len = Math.hypot(ux, uy) || 1;
    exits[model.cards[index].id] = { x: ux / len, y: uy / len };
    step(1);
  } else {
    layout(true);
  }
}
window.addEventListener('pointerup', endDrag);
window.addEventListener('pointercancel', endDrag);
// Reels are portrait, so they don't fit the art window; they play in the
// modal instead, sized for them. Closing it drops the iframe, which stops it.
els.track.addEventListener('click', e => {
  const b = e.target.closest('[data-reel]');
  if (!b) return;
  stopVideo();
  els.modal.classList.add('is-video');
  els.modalTitle.textContent = b.dataset.title || '';
  els.modalBody.innerHTML = `<iframe src="${escapeHtml(b.dataset.reel)}" title="Instagram reel"
    allow="autoplay; encrypted-media; picture-in-picture; fullscreen" allowfullscreen scrolling="no"></iframe>`;
  els.modal.showModal();
});
els.modal.addEventListener('close', () => {
  if (els.modal.classList.contains('is-video')) els.modalBody.innerHTML = '';
});

els.track.addEventListener('click', e => {
  if (dragClickGuard) { e.preventDefault(); e.stopImmediatePropagation(); }
}, true);

// Foil tilt follows a mouse; on touch the foil just drifts on its own, since
// a finger on the card is a swipe.
els.track.addEventListener('pointermove', e => {
  if (e.pointerType !== 'mouse' || drag) return;
  const card = e.target.closest('.pr-card');
  if (!card) return;
  const r = card.getBoundingClientRect();
  const x = (e.clientX - r.left) / r.width;
  const y = (e.clientY - r.top) / r.height;
  card.classList.add('is-tracking');
  card.style.setProperty('--ry', `${(x - 0.5) * 10}deg`);
  card.style.setProperty('--rx', `${(0.5 - y) * 10}deg`);
  card.style.setProperty('--hx', `${x * 100}%`);
  card.style.setProperty('--hy', `${y * 100}%`);
});
els.track.addEventListener('pointerout', e => {
  const card = e.target.closest('.pr-card');
  if (!card || card.contains(e.relatedTarget)) return;
  resetTilt(card);
});

function resetTilt(card) {
  card.classList.remove('is-tracking');
  ['--rx', '--ry', '--hx', '--hy'].forEach(p => card.style.removeProperty(p));
}

els.toggle.addEventListener('click', () => setEditing(!editing));

window.addEventListener('hashchange', () => {
  const i = model ? model.cards.findIndex(c => c.id === decodeURIComponent(location.hash.slice(1))) : -1;
  if (i >= 0 && i !== index) goTo(i);
});

// ---------- boot ----------

// The server copy, or the seed while the table is empty (version 0).
async function fetchDeck() {
  const res = await api('GET');
  if (res.status === 404) {
    const seed = await fetch(SEED_URL, { cache: 'no-cache' });
    if (!seed.ok) throw new Error('No deck and no seed');
    return { model: await seed.json(), version: 0 };
  }
  if (!res.ok) throw new Error(`Load failed (${res.status})`);
  return res.json();
}

async function load() {
  const deck = await fetchDeck();
  model = deck.model;
  version = deck.version;

  // Unsaved edits from this browser: replay them if they were made on this
  // exact version, otherwise set them aside rather than write over newer cards.
  const draft = readStored(DRAFT_KEY);
  if (draft && isDeck(draft.model)) {
    if (draft.version === version) {
      model = draft.model;
      dirty = true;
    } else {
      strand(draft.model, 'This browser had edits that were never saved, made on an older version of the cards.');
      clearDraft();
    }
  }
  const legacy = readStored(LEGACY_DRAFT_KEY);
  if (isDeck(legacy)) {
    strand(legacy, 'This browser has an old local draft from before the cards were saved to the server.');
    writeStored(LEGACY_DRAFT_KEY, null);
  }
  if (!stranded) {
    const kept = readStored(STRANDED_KEY);
    if (kept && isDeck(kept.model)) stranded = kept;
  }
  // An empty table is seeded by the first load; replayed edits go up as well.
  if (version === 0) dirty = true;
  if (dirty) scheduleSave(0);
  const hashId = decodeURIComponent(location.hash.slice(1));
  const fromHash = model.cards.findIndex(c => c.id === hashId);
  index = fromHash >= 0 ? fromHash : slot(0);
  // Every poster is fetched and decoded before the deck is dealt, so no card
  // paints in half-loaded mid-throw. A slow or dead image host can't hold the
  // deck hostage: whatever hasn't arrived after a few seconds loads in place.
  await preloadImages(model.cards
    .flatMap(c => [posterOf(c), c.evolvesFrom ? safeUrl(c.evolvesFrom.image) : ''])
    .filter(Boolean));
  els.body.classList.remove('is-loading');
  renderAll();
}

function preloadImages(urls, timeoutMs = 5000) {
  const loads = [...new Set(urls)].map(src => {
    const img = new Image();
    img.referrerPolicy = 'no-referrer';
    img.src = src;
    return img.decode().catch(() => {});
  });
  return Promise.race([
    Promise.all(loads),
    new Promise(resolve => setTimeout(resolve, timeoutMs)),
  ]);
}

// Admin-only page (a Sandbox item). requireAdmin bounces everyone else before
// anything loads — UI-level gating, like the other admin pages.
if (requireAdmin('/')) {
  if (canEdit()) els.toggle.hidden = false;
  load().catch(() => {
    els.body.classList.remove('is-loading');
    els.track.innerHTML = '<p style="margin:auto;padding:24px;text-align:center">Couldn’t load the rankings.</p>';
  });
}
