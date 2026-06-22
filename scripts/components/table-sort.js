/* Table sort — a functional sorting component (window.Sort).
 *
 * MVC split: this module is the MODEL only — pure comparators, a pure sort,
 * and pure state transitions. It never touches the DOM. Each page keeps its own
 * render (the VIEW) and wires header clicks (the CONTROLLER) to these helpers.
 *
 * Two header idioms are supported:
 *   • toggle  — one active column; clicking flips asc/desc. State {key, dir}.
 *               Used by league schedule / generic tables.
 *   • cycle   — a two-column "name vs value" table where the value column is the
 *               default. Clicking the name column cycles asc → desc → back to the
 *               value column; clicking the value column toggles its direction.
 *               State {mode:'name'|'<value>', <value>Dir, nameDir}. Used by the
 *               odds board (OU strips and outright/award tables).
 *
 * Directions are the strings 'asc' | 'desc' everywhere.
 */
(function (global) {
  'use strict';

  // Pure comparator. opts:
  //   numeric   — compare as numbers (default false → locale string compare)
  //   nullsLast — null/undefined always sort last, regardless of dir (default true)
  //   accessor  — map a row to its sort value (default identity)
  function comparator(dir, opts) {
    opts = opts || {};
    var numeric = !!opts.numeric;
    var nullsLast = opts.nullsLast !== false;
    var get = opts.accessor || function (x) { return x; };
    var desc = dir === 'desc';
    return function (a, b) {
      var av = get(a), bv = get(b);
      var aNull = av === null || av === undefined || (numeric && isNaN(av));
      var bNull = bv === null || bv === undefined || (numeric && isNaN(bv));
      if (aNull && bNull) return 0;
      if (aNull) return nullsLast ? 1 : -1;
      if (bNull) return nullsLast ? -1 : 1;
      if (numeric) return desc ? bv - av : av - bv;
      var cmp = String(av).localeCompare(String(bv));
      return desc ? -cmp : cmp;
    };
  }

  // Pure: return a new sorted array (never mutates the input).
  function sortBy(rows, dir, opts) {
    return rows.slice().sort(comparator(dir, opts));
  }

  // --- toggle idiom (pure state transition) ---
  // Same column → flip direction; new column → defaultDir (value or fn(key)).
  function toggle(state, key, defaultDir) {
    if (state && state.key === key) {
      return { key: key, dir: state.dir === 'asc' ? 'desc' : 'asc' };
    }
    var dir = typeof defaultDir === 'function' ? defaultDir(key) : (defaultDir || 'asc');
    return { key: key, dir: dir };
  }

  // --- cycle idiom (pure state transitions) for the name/value two-column table ---
  // `valueMode` is the state's default mode string (e.g. 'fmv').
  function cycleName(state, valueMode) {
    if (state.mode !== 'name') {
      return Object.assign({}, state, { mode: 'name', nameDir: 'asc' });
    }
    if (state.nameDir === 'asc') {
      return Object.assign({}, state, { nameDir: 'desc' });
    }
    return Object.assign({}, state, { mode: valueMode }); // third click → back to value
  }

  function cycleValue(state, valueMode, dirField) {
    if (state.mode !== valueMode) {
      return Object.assign({}, state, { mode: valueMode });
    }
    var next = state[dirField] === 'desc' ? 'asc' : 'desc';
    var patch = {};
    patch[dirField] = next;
    return Object.assign({}, state, patch);
  }

  // VIEW helper: the little ▲/▼ glyph. Returns '' when dir is falsy (inactive).
  function arrow(dir, cls) {
    if (!dir) return '';
    return '<span class="' + (cls || 'sort-arrow') + '">' +
      (dir === 'asc' ? ' ▲' : ' ▼') + '</span>';
  }

  global.Sort = {
    comparator: comparator,
    sortBy: sortBy,
    toggle: toggle,
    cycleName: cycleName,
    cycleValue: cycleValue,
    arrow: arrow,
  };
})(window);
