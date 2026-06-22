/* Heatmap — value-driven color scales for conditional formatting (window.Heatmap).
 *
 * Two factories, each returning a pure value→CSS-color function:
 *   • sequential — single track across [min,max]; green→red HSL gradient.
 *                  Replaces league schedule's gradientColor(value,min,max).
 *   • diverging  — centered at 0; positive ramps one color, negative another.
 *                  Replaces league scout's z-score zColor(z).
 *
 * Pure: the returned function reads only its argument and the captured config.
 */
(function (global) {
  'use strict';

  // Sequential HSL scale. Defaults reproduce schedule's gradientColor exactly
  // (hue 140°→0°, 70% sat, 45% light, gray for null / zero-width range).
  function sequential(cfg) {
    cfg = cfg || {};
    var min = cfg.min, max = cfg.max;
    var hueStart = cfg.hueStart != null ? cfg.hueStart : 140;
    var hueEnd = cfg.hueEnd != null ? cfg.hueEnd : 0;
    var sat = cfg.sat != null ? cfg.sat : 70;
    var light = cfg.light != null ? cfg.light : 45;
    var nullColor = cfg.nullColor != null ? cfg.nullColor : '#8b949e';
    return function (value) {
      if (value == null || max === min) return nullColor;
      var t = Math.max(0, Math.min(1, (value - min) / (max - min)));
      var hue = hueStart - t * (hueStart - hueEnd);
      return 'hsl(' + hue.toFixed(0) + ', ' + sat + '%, ' + light + '%)';
    };
  }

  // Diverging rgba scale around zero. Defaults reproduce scout's zColor exactly
  // (green for positive scaled by posMax, red for negative scaled by negMax).
  function diverging(cfg) {
    cfg = cfg || {};
    var posMax = cfg.posMax || 1;
    var negMax = cfg.negMax || 1;
    var pos = cfg.posColor || [34, 197, 94];
    var neg = cfg.negColor || [220, 38, 38];
    var zero = cfg.zero != null ? cfg.zero : 'transparent';
    var nullColor = cfg.nullColor != null ? cfg.nullColor : '';
    return function (value) {
      if (value == null) return nullColor;
      if (value > 0) {
        return 'rgba(' + pos.join(', ') + ', ' + Math.min(value / posMax, 1).toFixed(2) + ')';
      }
      if (value < 0) {
        return 'rgba(' + neg.join(', ') + ', ' + Math.min(Math.abs(value) / negMax, 1).toFixed(2) + ')';
      }
      return zero;
    };
  }

  global.Heatmap = { sequential: sequential, diverging: diverging };
})(window);
