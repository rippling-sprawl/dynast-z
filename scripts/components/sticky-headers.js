/* Sticky headers — compute `top` offsets for stacked position:sticky elements
 * (window.Sticky). A pinned row must sit below everything already pinned above
 * it; this measures those anchors' heights so the stack stays visible.
 *
 * Pages own the DOM queries and which elements pin where; this module only does
 * the measurement math. The odds board uses it to pin breadcrumbs below the site
 * header, then table heads below the breadcrumbs (and column rows below titles).
 */
(function (global) {
  'use strict';

  /* One anchor's share of the band of chrome across the top of the viewport.
   *
   * Normally that is just its height — but the site header is one element with
   * two shapes (styles/base/styles.css): sticky at the top on wide screens,
   * and on narrow ones the tab bar fixed to the *bottom* edge. Down there it
   * owns nothing up here, so it has to measure 0 or everything pinned against
   * it hangs a bar's height below where it belongs.
   *
   * A fixed box is measured off its rect, which for `position: fixed` is its
   * viewport box at every scroll offset — so the answer is a layout constant,
   * which is what these callers need: they bake it into a `style.top` a sticky
   * element then holds all the way down the page. (The declared `top` is no
   * use for the test: getComputedStyle resolves it to a used value, so the
   * bottom bar's `top: auto` reads back as its distance down the viewport.)
   * Sticky and static anchors keep their height, which is what a header
   * actually pinned at the top is worth. */
  function spanAtTop(el) {
    if (!el) return 0;
    if (getComputedStyle(el).position !== 'fixed') return el.offsetHeight || 0;
    var r = el.getBoundingClientRect();
    return r.top <= 0 ? Math.max(0, r.bottom) : 0;
  }

  // Sum the anchor elements' share of the top of the viewport (skips missing).
  function topOf(anchors) {
    return (anchors || []).reduce(function (sum, el) {
      return sum + spanAtTop(el);
    }, 0);
  }

  // Pin `el` directly below the given anchors. Returns the applied top (px).
  function pinBelow(el, anchors) {
    if (!el) return 0;
    var top = topOf(anchors);
    el.style.top = top + 'px';
    return top;
  }

  global.Sticky = { topOf: topOf, spanAtTop: spanAtTop, pinBelow: pinBelow };
})(window);
