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

  // Sum the rendered heights of the anchor elements (skips null/missing).
  function topOf(anchors) {
    return (anchors || []).reduce(function (sum, el) {
      return sum + (el && el.offsetHeight || 0);
    }, 0);
  }

  // Pin `el` directly below the given anchors. Returns the applied top (px).
  function pinBelow(el, anchors) {
    if (!el) return 0;
    var top = topOf(anchors);
    el.style.top = top + 'px';
    return top;
  }

  global.Sticky = { topOf: topOf, pinBelow: pinBelow };
})(window);
