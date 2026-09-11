/* Heatmap — value-driven color scales for conditional formatting (window.Heatmap).
 *
 * Two factories, each returning a pure value→CSS-color function:
 *   • sequential — single track across [min,max]; green→red HSL gradient.
 *                  The shape league schedule's gradientHue() draws by hand.
 *   • diverging  — centered at 0; positive ramps one color, negative another.
 *                  The shape scout / team / trade-calculator's z-score wash
 *                  draws by hand.
 *
 * Both of those pages now hand a bare number to CSS and let a color-mix() or
 * an hsl() there do the mixing, which is strictly better where it applies: the
 * scale re-colors on a theme change without the table being rebuilt. This
 * module is for the callers that cannot do that — anything drawing to a canvas
 * or building an SVG attribute, where var() does not resolve.
 *
 * Pure: the returned function reads only its argument and the captured config.
 *
 * Theme: the defaults are read from the theme tokens (--heat-seq-*, --heat-*)
 * at the moment a scale is built, not baked in, because the same hue needs a
 * lower lightness to read on a white page than on a black one. A caller that
 * keeps a scale across a theme change should rebuild it — see the
 * `themechange` event in scripts/base/theme.js. An explicit cfg value always
 * wins, so a chart with its own palette is unaffected.
 */
(function (global) {
  'use strict';

  // Read a theme token, falling back to the dark value the site shipped with.
  function tok(name, fallback) {
    if (global.Theme && global.Theme.color) return global.Theme.color(name, fallback);
    return fallback;
  }

  // '70%' -> 70. The tokens carry units so CSS can spend them directly.
  function pct(v, fallback) {
    var n = parseFloat(v);
    return isNaN(n) ? fallback : n;
  }

  // Sequential HSL scale. Defaults reproduce schedule's gradientColor exactly
  // (hue 140°→0°, then the theme's saturation and lightness, and --heat-null
  // for a null value or a zero-width range).
  function sequential(cfg) {
    cfg = cfg || {};
    var min = cfg.min, max = cfg.max;
    var hueStart = cfg.hueStart != null ? cfg.hueStart : 140;
    var hueEnd = cfg.hueEnd != null ? cfg.hueEnd : 0;
    var sat = cfg.sat != null ? cfg.sat : pct(tok('--heat-seq-sat', '70%'), 70);
    var light = cfg.light != null ? cfg.light : pct(tok('--heat-seq-light', '45%'), 45);
    var nullColor = cfg.nullColor != null ? cfg.nullColor : tok('--heat-null', '#8b949e');
    return function (value) {
      if (value == null || max === min) return nullColor;
      var t = Math.max(0, Math.min(1, (value - min) / (max - min)));
      var hue = hueStart - t * (hueStart - hueEnd);
      return 'hsl(' + hue.toFixed(0) + ', ' + sat + '%, ' + light + '%)';
    };
  }

  // Diverging rgba scale around zero: green for positive scaled by posMax, red
  // for negative scaled by negMax. The two hues come from the theme's heat
  // fills, which are the bright end of the ramp in both themes — a wash wants
  // a bright colour at low alpha, not a dark one.
  function diverging(cfg) {
    cfg = cfg || {};
    var posMax = cfg.posMax || 1;
    var negMax = cfg.negMax || 1;
    var pos = cfg.posColor || rgb(tok('--heat-z-fill', '#22c55e'), [34, 197, 94]);
    var neg = cfg.negColor || rgb(tok('--heat-bad-fill', '#f0883e'), [220, 38, 38]);
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

  // '#22c55e' or 'rgb(34, 197, 94)' -> [34, 197, 94]. getComputedStyle hands
  // back whichever form the stylesheet used, so both have to parse.
  function rgb(value, fallback) {
    var v = String(value || '').trim();
    var m = v.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
    if (m) {
      var h = m[1];
      if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
      return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
    }
    m = v.match(/^rgba?\(([^)]+)\)$/i);
    if (m) {
      var parts = m[1].split(',').slice(0, 3).map(function (x) { return parseInt(x, 10); });
      if (parts.length === 3 && !parts.some(isNaN)) return parts;
    }
    return fallback;
  }

  global.Heatmap = { sequential: sequential, diverging: diverging };
})(window);
