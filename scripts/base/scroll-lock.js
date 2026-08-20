// Shared page scroll lock, for anything that opens over the page: <dialog>s,
// drawers, overlays.
//
// It exists because `body { overflow: hidden }` is not enough on its own:
//
//   - iOS Safari keeps scrolling the page behind a fixed overlay anyway, so the
//     page is pinned with position:fixed at its current offset instead, and the
//     offset is put back when the lock is released.
//   - A page can have more than one thing open at once, and the calls do not
//     nest tidily. <dialog>'s close event is fired from a queued task rather
//     than synchronously, so a dialog that closes another one on its way up —
//     the note form closing the team card — releases the card's lock *after*
//     taking its own. A boolean flag is left off by that ordering; a counter is
//     not.
//
// Every lock() must be paired with exactly one unlock(). For a <dialog> that
// means lock() after showModal() (which throws if it is already open, so the
// lock cannot be taken twice) and unlock() from its close event, which fires
// once however the dialog was closed — button, backdrop or Escape.

(function () {
  var depth = 0;
  var scrollY = 0;

  function lock() {
    if (depth++) return;
    scrollY = window.scrollY || window.pageYOffset || 0;
    document.body.style.top = -scrollY + 'px';
    document.body.classList.add('scroll-locked');
  }

  function unlock() {
    if (!depth || --depth) return;
    document.body.classList.remove('scroll-locked');
    document.body.style.top = '';
    window.scrollTo(0, scrollY);
  }

  window.ScrollLock = { lock: lock, unlock: unlock };
})();
