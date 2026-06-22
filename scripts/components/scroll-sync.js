/* Scroll sync — keep a follower element's scroll offset mirrored to a driver's
 * (window.ScrollSync). Used by the odds board so a top-pinned heading row stays
 * horizontally aligned with the body strips that scroll beneath it.
 */
(function (global) {
  'use strict';

  // Mirror driver → follower on the given axis ('x' default, or 'y').
  // Returns an unbind function.
  function link(driver, follower, opts) {
    var axis = (opts && opts.axis) || 'x';
    var prop = axis === 'y' ? 'scrollTop' : 'scrollLeft';
    var handler = function () { follower[prop] = driver[prop]; };
    driver.addEventListener('scroll', handler);
    return function () { driver.removeEventListener('scroll', handler); };
  }

  global.ScrollSync = { link: link };
})(window);
