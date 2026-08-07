// Shared image lightbox — click an inline content image to open it full screen.
//
// What counts as a content image: anything inside a <figure>, or any image
// marked `data-lightbox` / `class="lightboxable"`. Opt out with
// `data-no-lightbox` on the image or any ancestor (used where a page already
// ships its own viewer, e.g. the Baker's Oven preview).
//
// Clicks are delegated off the document, so images that page JS renders later
// work with no re-binding; refreshLightbox() only adds the keyboard
// affordances (tabindex/role) to images inserted after load.

(function () {
  var OPEN_SELECTOR = 'img[data-lightbox], img.lightboxable, figure img';
  var SKIP_SELECTOR = '[data-no-lightbox]';

  var overlay = null;
  var overlayImg = null;
  var closeBtn = null;
  var lastFocus = null;
  var scrollY = 0;

  function isTarget(el) {
    return !!el && el.tagName === 'IMG' && el.matches(OPEN_SELECTOR) && !el.closest(SKIP_SELECTOR);
  }

  function build() {
    if (overlay) return;
    overlay = document.createElement('div');
    overlay.className = 'lightbox';
    overlay.hidden = true;
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', 'Image viewer');
    overlay.innerHTML =
      '<button type="button" class="lightbox-close" aria-label="Close image">&times;</button>' +
      '<img class="lightbox-image" alt="">';
    overlayImg = overlay.querySelector('.lightbox-image');
    closeBtn = overlay.querySelector('.lightbox-close');
    // Anywhere but the image itself closes — the backdrop and the close button.
    overlay.addEventListener('click', function (e) {
      if (e.target !== overlayImg) closeLightbox();
    });
    document.body.appendChild(overlay);
  }

  function lockScroll() {
    scrollY = window.scrollY || window.pageYOffset || 0;
    document.body.style.top = -scrollY + 'px';
    document.body.classList.add('lightbox-open');
  }

  function unlockScroll() {
    document.body.classList.remove('lightbox-open');
    document.body.style.top = '';
    window.scrollTo(0, scrollY);
  }

  function onKeydown(e) {
    if (e.key === 'Escape') {
      e.preventDefault();
      closeLightbox();
    } else if (e.key === 'Tab') {
      // Only one control in the dialog, so focus simply stays on it.
      e.preventDefault();
      closeBtn.focus();
    }
  }

  function openLightbox(img) {
    build();
    // currentSrc so a responsive/srcset image opens the variant already loaded.
    overlayImg.src = img.currentSrc || img.src;
    overlayImg.alt = img.alt || '';
    lastFocus = document.activeElement;
    lockScroll();
    overlay.hidden = false;
    // One frame laid out but still transparent, so the fade actually runs.
    requestAnimationFrame(function () { overlay.classList.add('open'); });
    closeBtn.focus();
    document.addEventListener('keydown', onKeydown);
  }

  function closeLightbox() {
    if (!overlay || overlay.hidden) return;
    document.removeEventListener('keydown', onKeydown);
    overlay.classList.remove('open');
    overlay.hidden = true;
    overlayImg.removeAttribute('src');
    unlockScroll();
    if (lastFocus && document.contains(lastFocus)) lastFocus.focus();
    lastFocus = null;
  }

  // Give openable images the affordances a <button> would have. Idempotent, so
  // it is safe to re-run over a subtree after rendering new content.
  function refreshLightbox(root) {
    var scope = root || document;
    var imgs = scope.querySelectorAll(OPEN_SELECTOR);
    for (var i = 0; i < imgs.length; i++) {
      var img = imgs[i];
      if (img.dataset.lightboxReady || img.closest(SKIP_SELECTOR)) continue;
      img.dataset.lightboxReady = '1';
      img.tabIndex = 0;
      img.setAttribute('role', 'button');
      img.setAttribute('aria-label', (img.alt ? img.alt + ' — ' : '') + 'open full screen');
    }
  }

  document.addEventListener('click', function (e) {
    var img = e.target.closest ? e.target.closest('img') : null;
    if (!isTarget(img)) return;
    e.preventDefault();
    openLightbox(img);
  });

  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    var el = document.activeElement;
    if (!isTarget(el)) return;
    e.preventDefault();
    openLightbox(el);
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { refreshLightbox(); });
  } else {
    refreshLightbox();
  }

  window.Lightbox = { open: openLightbox, close: closeLightbox, refresh: refreshLightbox };
})();
