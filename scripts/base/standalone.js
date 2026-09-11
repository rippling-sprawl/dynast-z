// Home-screen launches — detection, and the share row that only exists there.
//
// Loaded before nav.js on every page, because nav.js asks this file for the
// drawer row while it is building the drawer's markup.
//
// A site pinned to an iOS home screen opens in a window with no address bar,
// which means no URL to read off and nothing to hand someone the page with.
// That is the whole reason for the button below: in a browser tab the address
// bar already does this job, so the row is not rendered there at all.
//
// The launch state is fixed for the life of the window — iOS does not move a
// page between standalone and tabbed — so it is read once, at load, and cached.

(function (global) {
  'use strict';

  // navigator.standalone is Safari's own flag, and was the only signal iOS
  // gave before 16.4; display-mode is the standard one, which is what Android
  // installs, desktop installs and iOS 16.4+ report. Either is enough, and
  // both are false in an ordinary tab. minimal-ui/fullscreen are in here
  // because a manifest edit to either should not silently drop the row.
  function detect() {
    if (global.navigator.standalone === true) return true;
    try {
      return ['standalone', 'minimal-ui', 'fullscreen']
        .some(function (mode) {
          return global.matchMedia('(display-mode: ' + mode + ')').matches;
        });
    } catch (e) {
      return false;
    }
  }

  var INSTALLED = detect();

  // On <html> for the same reason data-theme is: so a stylesheet can answer
  // "are we in the home-screen app?" without a class on every element that
  // cares. `@media (display-mode: standalone)` covers most of this on its own,
  // but not on iOS before 16.4, which is exactly the case navigator.standalone
  // is here for.
  if (INSTALLED) document.documentElement.setAttribute('data-standalone', '');

  function is() {
    return INSTALLED;
  }

  // --- Copying ------------------------------------------------------------

  // The async clipboard needs a secure context and a user gesture. Both hold
  // for a button click on https, which is every real visit; the fallback is
  // for iOS before 13.4 and for anyone running the site over plain http.
  function copy(text) {
    if (global.isSecureContext && global.navigator.clipboard) {
      return global.navigator.clipboard.writeText(text);
    }
    return legacyCopy(text);
  }

  // execCommand copies the selection, so there has to be one. iOS will not put
  // a caret in a readonly field, hence the hand-built Range rather than the
  // usual textarea.select() — and the field has to be readonly, or focusing it
  // brings the keyboard up over the drawer.
  function legacyCopy(text) {
    return new Promise(function (resolve, reject) {
      var field = document.createElement('textarea');
      field.value = text;
      field.setAttribute('readonly', '');
      field.style.cssText = 'position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;';
      document.body.appendChild(field);

      var selection = global.getSelection();
      var range = document.createRange();
      range.selectNodeContents(field);
      selection.removeAllRanges();
      selection.addRange(range);
      field.setSelectionRange(0, text.length);

      var ok = false;
      try {
        ok = document.execCommand('copy');
      } catch (e) { /* ok stays false */ }

      selection.removeAllRanges();
      document.body.removeChild(field);
      ok ? resolve() : reject(new Error('copy unavailable'));
    });
  }

  // --- The drawer row -----------------------------------------------------
  // Markup lives here rather than in nav.js so the feature is one file, the
  // same arrangement Theme.controlHTML() uses for the theme circles. Empty
  // string in a browser tab, so nav.js can interpolate it unconditionally.
  //
  // A link glyph rather than the iOS share box: this copies a URL, it does not
  // open the share sheet, and the icon should not promise otherwise. Same
  // 24x24 box and 1.8 stroke as the header icons in nav.js.

  var LABEL = 'Share this page';

  function rowHTML() {
    if (!INSTALLED) return '';
    return '' +
      '<li class="nav-standalone">' +
        '<button type="button" class="nav-share" data-share-page>' +
          '<svg class="nav-share-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"' +
          ' stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
            '<path d="M10.6 13.4a4.2 4.2 0 0 0 6 0l3-3a4.2 4.2 0 0 0-6-6l-1.5 1.5"/>' +
            '<path d="M13.4 10.6a4.2 4.2 0 0 0-6 0l-3 3a4.2 4.2 0 0 0 6 6l1.5-1.5"/>' +
          '</svg>' +
          '<span class="nav-share-label" aria-live="polite">' + LABEL + '</span>' +
        '</button>' +
      '</li>';
  }

  // The label doubles as the confirmation — a row that says "Link copied" for
  // a moment is the whole feedback, so it is a live region and there is no
  // toast. Idempotent for the same reason Theme.mountToggle() is: pages call
  // both initPage() and initNavDrawer().
  function mount(root) {
    var scope = root || document;
    var buttons = scope.querySelectorAll('[data-share-page]');
    for (var i = 0; i < buttons.length; i++) {
      if (buttons[i].dataset.shareBound) continue;
      buttons[i].dataset.shareBound = '1';
      buttons[i].addEventListener('click', onClick);
    }
  }

  function onClick() {
    var button = this;
    copy(global.location.href).then(
      function () { flash(button, 'Link copied', 'is-copied'); },
      // Nothing left to try — say what still works rather than just failing,
      // since a long-press on the row's own text can still copy it by hand.
      function () { flash(button, 'Copy failed', 'is-failed'); }
    );
  }

  function flash(button, text, cls) {
    var label = button.querySelector('.nav-share-label');
    clearTimeout(button.shareTimer);
    label.textContent = text;
    button.classList.remove('is-copied', 'is-failed');
    button.classList.add(cls);
    button.shareTimer = setTimeout(function () {
      label.textContent = LABEL;
      button.classList.remove('is-copied', 'is-failed');
    }, 1800);
  }

  global.Standalone = {
    is: is,
    copy: copy,
    rowHTML: rowHTML,
    mount: mount,
  };
})(window);
