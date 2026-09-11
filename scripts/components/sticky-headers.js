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

  /* The horizontal twin of pinBelow, and the reason it has to exist.
   *
   * A column pinned with `left` has to be told the exact width of everything
   * pinned to its left, and CSS cannot ask. So the offsets were written by hand
   * -- `left: 34px` for the player column, `left: 118px` for survivor's status
   * -- against widths somebody measured once. They were wrong the first time a
   * username was longer than the guess: on the survivor standings the status
   * column was told 118px when rank and player actually span 646px, so the
   * moment the board was wide enough to scroll, status jumped 528px to the left
   * and landed on top of the player column.
   *
   * Measured instead. `cells` are the pinned columns in left-to-right order,
   * given as selectors; each one is offset by the real rendered width of the
   * ones before it, header and body together so a column cannot shear. Widths
   * come from the header cell, which is the whole column's width by definition.
   *
   * Idempotent and cheap -- a handful of getBoundingClientRect on one row -- so
   * callers re-run it after every render and on resize rather than trying to
   * work out whether anything moved. */
  function pinColumns(table, selectors) {
    if (!table || !selectors || !selectors.length) return;
    var offset = 0;
    selectors.forEach(function (sel) {
      var head = table.querySelector('thead ' + sel);
      if (!head) return;
      var cells = table.querySelectorAll('thead ' + sel + ', tbody ' + sel);
      for (var i = 0; i < cells.length; i++) {
        // Only columns CSS actually pinned. A media query that unpins one --
        // survivor's status on a phone -- must win, so the offset is applied to
        // what is sticky and skipped for what is not.
        if (getComputedStyle(cells[i]).position !== 'sticky') continue;
        cells[i].style.left = offset + 'px';
      }
      offset += head.getBoundingClientRect().width;
    });
  }

  global.Sticky = { topOf: topOf, spanAtTop: spanAtTop, pinBelow: pinBelow,
                    pinColumns: pinColumns };
})(window);
