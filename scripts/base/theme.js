// Theme — dark (default) or light, remembered across visits.
//
// Loaded from <head>, before the stylesheets, so the `data-theme` attribute is
// on <html> before the first paint. A deferred or body-end script would let one
// dark frame through on a light-mode reload, which is the flash this avoids.
// It is the only script the site loads that way, and it stays small for that
// reason: read a string, set an attribute, define the API.
//
// The choice is stored under STORAGE_KEY, and nothing is stored until the
// reader actually picks a side. Until they do the site is dark, which is what
// it has always been — deliberately not prefers-color-scheme, because that
// would flip the site out from under every existing reader on a light desktop
// without them asking for it. To follow the OS instead, make resolve() return
// `stored() || preferred()`.
//
// Anything that draws its own colours in JS (the Board scatter, the market
// radar, the schedule gradient) cannot use CSS tokens, so it listens for the
// `themechange` event this dispatches and repaints. See Theme.color() for
// reading a token's current value from script.

(function (global) {
  'use strict';

  var STORAGE_KEY = 'dz-theme';
  var DARK = 'dark';
  var LIGHT = 'light';

  function stored() {
    try {
      var v = global.localStorage.getItem(STORAGE_KEY);
      return v === DARK || v === LIGHT ? v : null;
    } catch (e) {
      // Private mode / storage disabled. The toggle still works for the
      // session; it just will not survive a reload.
      return null;
    }
  }

  // Not consulted by default — see resolve(). Kept so following the OS is a
  // one-line change rather than a rewrite.
  function preferred() {
    try {
      return global.matchMedia('(prefers-color-scheme: light)').matches ? LIGHT : DARK;
    } catch (e) {
      return DARK;
    }
  }

  function resolve() {
    return stored() || DARK;
  }

  function apply(theme) {
    var root = document.documentElement;
    if (theme === LIGHT) root.setAttribute('data-theme', LIGHT);
    else root.removeAttribute('data-theme');
  }

  function get() {
    return document.documentElement.getAttribute('data-theme') === LIGHT ? LIGHT : DARK;
  }

  function set(theme) {
    theme = theme === LIGHT ? LIGHT : DARK;
    if (theme === get()) return theme;
    apply(theme);
    try {
      global.localStorage.setItem(STORAGE_KEY, theme);
    } catch (e) { /* see stored() */ }
    syncControls();
    global.dispatchEvent(new CustomEvent('themechange', { detail: { theme: theme } }));
    return theme;
  }

  function toggle() {
    return set(get() === LIGHT ? DARK : LIGHT);
  }

  // Read a theme token's computed value. For canvas/SVG drawn in script, where
  // `var(--x)` is not available. Falls back to whatever the caller expects.
  function color(token, fallback) {
    var v = getComputedStyle(document.documentElement)
      .getPropertyValue(token.charAt(0) === '-' ? token : '--' + token);
    return (v && v.trim()) || fallback || '';
  }

  // --- The control in the nav drawer -------------------------------------
  // Markup lives here rather than in nav.js so the whole feature is one file;
  // nav.js only has to drop the string in and call mountToggle().

  function controlHTML() {
    return '' +
      '<div class="theme-toggle" role="group" aria-label="Color theme">' +
        '<span class="theme-toggle-label">Theme</span>' +
        '<div class="theme-switch">' +
          '<button type="button" class="theme-opt" data-theme-set="dark" aria-pressed="false">' +
            '<span class="theme-opt-icon" aria-hidden="true">&#9789;</span>Dark' +
          '</button>' +
          '<button type="button" class="theme-opt" data-theme-set="light" aria-pressed="false">' +
            '<span class="theme-opt-icon" aria-hidden="true">&#9788;</span>Light' +
          '</button>' +
        '</div>' +
      '</div>';
  }

  function syncControls() {
    var current = get();
    var opts = document.querySelectorAll('[data-theme-set]');
    for (var i = 0; i < opts.length; i++) {
      var on = opts[i].getAttribute('data-theme-set') === current;
      opts[i].classList.toggle('is-active', on);
      opts[i].setAttribute('aria-pressed', on ? 'true' : 'false');
    }
  }

  // Idempotent: pages that call both initPage() and initNavDrawer() would
  // otherwise bind the handler twice.
  function mountToggle(root) {
    var scope = root || document;
    var opts = scope.querySelectorAll('[data-theme-set]');
    for (var i = 0; i < opts.length; i++) {
      if (opts[i].dataset.themeBound) continue;
      opts[i].dataset.themeBound = '1';
      opts[i].addEventListener('click', function () {
        set(this.getAttribute('data-theme-set'));
      });
    }
    syncControls();
  }

  apply(resolve());

  global.Theme = {
    get: get,
    set: set,
    toggle: toggle,
    color: color,
    controlHTML: controlHTML,
    mountToggle: mountToggle,
    syncControls: syncControls,
    DARK: DARK,
    LIGHT: LIGHT,
  };
})(window);
