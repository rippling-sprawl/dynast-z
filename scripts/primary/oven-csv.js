/* The Baker's Oven — CSV import/export (window.OvenCSV).
 *
 * Zero dependencies, matching the rest of the repo. The parser is a real
 * RFC-4180 state machine rather than split(',') because player notes and
 * "Last, First" names contain commas, and a naive split silently corrupts rows
 * instead of failing loudly.
 *
 * Schema: only `Player` is required. Headers match case- and space-insensitively.
 * Unknown columns are preserved on the row (`extra`) and never cause an error —
 * the point is that you can keep your own working columns in the sheet.
 */
(function (global) {
  'use strict';

  // Canonical field -> accepted header aliases (all compared normalized).
  var HEADER_ALIASES = {
    player: ['player', 'name', 'playername', 'fullname'],
    pos: ['pos', 'position'],
    team: ['team', 'nfl', 'nflteam'],
    tier: ['tier'],
    myRank: ['myrank', 'rank', 'rk', 'mine', 'myrk'],
    grade: ['grade', 'like', 'likedislike', 'opinion'],
    note: ['note', 'notes', 'comment', 'comments'],
  };

  var GRADES = ['like', 'fade'];

  function normHeader(h) {
    return String(h == null ? '' : h).toLowerCase().replace(/[^a-z0-9]/g, '');
  }

  /* ---------- parsing ---------- */

  // RFC-4180: quoted fields may contain commas, newlines, and "" escapes.
  // Handles \r\n, \n and \r line endings, and strips a UTF-8 BOM.
  function parse(text) {
    if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
    var rows = [];
    var row = [];
    var field = '';
    var inQuotes = false;
    var i = 0;
    var started = false; // distinguishes an empty trailing line from a real ""

    while (i < text.length) {
      var c = text[i];
      if (inQuotes) {
        if (c === '"') {
          if (text[i + 1] === '"') { field += '"'; i += 2; continue; }
          inQuotes = false; i++; continue;
        }
        field += c; i++; continue;
      }
      if (c === '"') { inQuotes = true; started = true; i++; continue; }
      if (c === ',') { row.push(field); field = ''; started = false; i++; continue; }
      if (c === '\r' || c === '\n') {
        if (c === '\r' && text[i + 1] === '\n') i++;
        row.push(field);
        if (row.length > 1 || row[0] !== '' || started) rows.push(row);
        row = []; field = ''; started = false; i++; continue;
      }
      field += c; started = true; i++;
    }
    row.push(field);
    if (row.length > 1 || row[0] !== '' || started) rows.push(row);
    return rows;
  }

  // Locate the header row. Google Sheets exports often carry a title or a blank
  // spacer line above the real headers, so scan the first few rows for one that
  // actually contains a recognizable player column.
  function findHeaderRow(rows) {
    for (var i = 0; i < Math.min(rows.length, 5); i++) {
      var normed = rows[i].map(normHeader);
      for (var j = 0; j < normed.length; j++) {
        if (HEADER_ALIASES.player.indexOf(normed[j]) !== -1) return i;
      }
    }
    return -1;
  }

  function mapColumns(headerRow) {
    var map = {};       // canonical field -> column index
    var extras = [];    // {index, label} for unrecognized columns
    var normed = headerRow.map(normHeader);
    for (var i = 0; i < normed.length; i++) {
      var matched = null;
      for (var field in HEADER_ALIASES) {
        if (HEADER_ALIASES[field].indexOf(normed[i]) !== -1) { matched = field; break; }
      }
      // First occurrence wins, so a duplicate header can't clobber a good column.
      if (matched && map[matched] === undefined) map[matched] = i;
      else if (!matched && headerRow[i] && headerRow[i].trim()) {
        extras.push({ index: i, label: headerRow[i].trim() });
      }
    }
    return { map: map, extras: extras };
  }

  function toInt(value) {
    if (value == null) return null;
    var n = parseInt(String(value).replace(/[^0-9-]/g, ''), 10);
    return isNaN(n) ? null : n;
  }

  function cleanGrade(value) {
    var v = String(value == null ? '' : value).trim().toLowerCase();
    if (!v) return null;
    if (GRADES.indexOf(v) !== -1) return v;
    // `love` and `avoid` were grades of their own until the scale merged to
    // like/none/fade, so they arrive in every sheet exported before that and in
    // every hand-kept sheet built from one. Same table the board reads.
    if (OVEN.GRADE_LEGACY[v]) return OVEN.GRADE_LEGACY[v];
    // Tolerate the obvious synonyms rather than dropping an opinion on a typo.
    if (v === 'l' || v === 'lv' || v === 'high' || v === 'up' ||
        v === '+' || v === '++' || v === 'target') return 'like';
    if (v === 'f' || v === 'a' || v === 'low' || v === 'down' ||
        v === '-' || v === 'no' || v === 'hate') return 'fade';
    return null;
  }

  /* Parse a CSV into board rows.
   * Returns { rows, errors, warnings, headers, extras }.
   * Throws only when the file has no usable header — every other problem is
   * reported as a warning so a mostly-good file still imports. */
  function parseBoard(text) {
    var rows = parse(text);
    if (!rows.length) throw new Error('That file looks empty.');

    var headerIndex = findHeaderRow(rows);
    if (headerIndex === -1) {
      throw new Error(
        'No "Player" column found. The first row needs a header naming each ' +
        'column — download the template to see the expected format.'
      );
    }

    var cols = mapColumns(rows[headerIndex]);
    var map = cols.map;
    var out = [];
    var warnings = [];
    var seen = {};

    for (var r = headerIndex + 1; r < rows.length; r++) {
      var raw = rows[r];
      var name = (raw[map.player] || '').trim();
      if (!name) continue; // blank spacer rows are normal in a working sheet

      var key = name.toLowerCase();
      if (seen[key]) {
        warnings.push('Duplicate row for "' + name + '" (line ' + (r + 1) + ') — kept the first.');
        continue;
      }
      seen[key] = true;

      var extra = {};
      for (var e = 0; e < cols.extras.length; e++) {
        var val = raw[cols.extras[e].index];
        if (val != null && String(val).trim()) extra[cols.extras[e].label] = String(val).trim();
      }

      out.push({
        name: name,
        pos: (raw[map.pos] || '').trim().toUpperCase(),
        team: (raw[map.team] || '').trim().toUpperCase(),
        tier: toInt(raw[map.tier]),
        myRank: toInt(raw[map.myRank]),
        grade: cleanGrade(raw[map.grade]),
        note: (raw[map.note] || '').trim(),
        extra: extra,
        player_id: null,   // filled in by /api/football/resolve
        srcLine: r + 1,
      });
    }

    if (!out.length) throw new Error('Found a header row but no player rows beneath it.');

    // MyRank drives board order. When absent, fall back to file order so a
    // hand-sorted sheet still works without anyone numbering 300 rows.
    var ranked = out.filter(function (p) { return p.myRank != null; }).length;
    if (ranked === 0) {
      out.forEach(function (p, i) { p.myRank = i + 1; });
      warnings.push('No MyRank column — using the row order from your file as the board order.');
    } else if (ranked < out.length) {
      warnings.push((out.length - ranked) + ' row(s) have no MyRank; they sort to the bottom.');
    }

    return {
      rows: out,
      warnings: warnings,
      headers: Object.keys(map),
      extras: cols.extras.map(function (x) { return x.label; }),
    };
  }

  /* ---------- writing ---------- */

  function escapeField(v) {
    var s = v == null ? '' : String(v);
    return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }

  function toCSV(header, rows) {
    var lines = [header.map(escapeField).join(',')];
    for (var i = 0; i < rows.length; i++) lines.push(rows[i].map(escapeField).join(','));
    return lines.join('\r\n');
  }

  var TEMPLATE_HEADER = ['Player', 'Pos', 'Team', 'Tier', 'MyRank', 'Grade', 'Note'];

  // Build a starter CSV from the FantasyPros half-PPR snapshot so the first
  // upload is one edit away, and so the download -> edit -> upload round trip
  // is guaranteed to parse.
  function buildTemplate(fpPlayers, limit) {
    var n = limit || 250;
    var rows = fpPlayers.slice(0, n).map(function (p, i) {
      return [p.name, p.position, p.team, p.tier == null ? '' : p.tier, i + 1, '', ''];
    });
    return toCSV(TEMPLATE_HEADER, rows);
  }

  // Export the current board back out, preserving any extra columns the user
  // keeps in their own sheet.
  function boardToCSV(rows) {
    var extraLabels = [];
    rows.forEach(function (p) {
      Object.keys(p.extra || {}).forEach(function (k) {
        if (extraLabels.indexOf(k) === -1) extraLabels.push(k);
      });
    });
    var header = TEMPLATE_HEADER.concat(extraLabels);
    var body = rows.map(function (p) {
      var base = [p.name, p.pos || '', p.team || '', p.tier == null ? '' : p.tier,
        p.myRank == null ? '' : p.myRank, p.grade || '', p.note || ''];
      return base.concat(extraLabels.map(function (k) { return (p.extra || {})[k] || ''; }));
    });
    return toCSV(header, body);
  }

  function download(filename, text) {
    var blob = new Blob([text], { type: 'text/csv;charset=utf-8;' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 0);
  }

  global.OvenCSV = {
    parse: parse,
    parseBoard: parseBoard,
    buildTemplate: buildTemplate,
    boardToCSV: boardToCSV,
    toCSV: toCSV,
    download: download,
    GRADES: GRADES,
    TEMPLATE_HEADER: TEMPLATE_HEADER,
  };
})(window);
