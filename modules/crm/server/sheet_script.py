"""The Apps Script that lets The Lodge read and write the shared Google Sheet (see sheet_sync.py).

It's pasted into the spreadsheet (Extensions, Apps Script) and deployed as a web app; Settings hands it out. It is
kept dumb on purpose, so it rarely needs pasting again: it makes sure the tabs and headers are there, reads every
row as shown, and writes what it's told. Each written cell names the value The Lodge read there, and a cell someone
has changed since is left alone. Everything about what the columns mean lives in sheet_sync.py.

It's in a .py file so it ships inside the app. Bump VERSION when it changes in a way the server relies on: the
server then asks for the new copy to be pasted in.
"""

VERSION = 1

SCRIPT = r"""/** @OnlyCurrentDoc */
/*
 * The Lodge: shared sheet link (version 1)
 *
 * Lets The Lodge, a relationship CRM on your Mac, keep the People and Organizations tabs of this spreadsheet in
 * step with it. It can only open this one spreadsheet.
 *
 * Set it up: Extensions, Apps Script. Replace everything there with this and save. Then Deploy, New deployment,
 * type "Web app", Execute as "Me", Who has access "Anyone", Deploy. Copy the Web app URL into The Lodge
 * (Settings, People: shared sheet).
 *
 * Anyone with that link can read and change this spreadsheet through it, so keep the link like a password.
 */
var LODGE_SCRIPT_VERSION = 1;

function doGet() {
  return reply_({ ok: true, lodge: true, version: LODGE_SCRIPT_VERSION });
}

function doPost(e) {
  var lock = LockService.getScriptLock();
  try {
    lock.waitLock(30000);
  } catch (err) {
    return reply_({ ok: false, version: LODGE_SCRIPT_VERSION, error: "the sheet is busy with another sync" });
  }
  try {
    var req = JSON.parse(e.postData.contents);
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var out;
    if (req.action === "read") out = read_(ss, req.tabs || []);
    else if (req.action === "write") out = write_(ss, req.tabs || {});
    else if (req.action === "hello") out = {};
    else throw new Error("unknown action " + req.action);
    out.ok = true;
    out.version = LODGE_SCRIPT_VERSION;
    out.spreadsheet = { name: ss.getName(), url: ss.getUrl() };
    return reply_(out);
  } catch (err) {
    return reply_({ ok: false, version: LODGE_SCRIPT_VERSION, error: String(err && err.message ? err.message : err) });
  } finally {
    lock.releaseLock();
  }
}

function reply_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

// ── Reading ─────────────────────────────────────────────────────────

function read_(ss, specs) {
  adoptBlankSheet_(ss, specs);
  var tabs = {};
  for (var i = 0; i < specs.length; i++) {
    var spec = specs[i];
    var sheet = ss.getSheetByName(spec.name);
    var created = false;
    if (!sheet) {
      sheet = ss.insertSheet(spec.name);
      created = true;
    }
    var added = ensureHeaders_(sheet, spec);
    var width = sheet.getLastColumn();
    var last = sheet.getLastRow();
    tabs[spec.name] = {
      headers: width ? sheet.getRange(1, 1, 1, width).getDisplayValues()[0] : [],
      rows: last >= 2 && width ? sheet.getRange(2, 1, last - 1, width).getDisplayValues() : [],
      added: added,
      created: created
    };
  }
  return { tabs: tabs };
}

// A new spreadsheet comes with one empty tab: use it rather than leave it lying around.
function adoptBlankSheet_(ss, specs) {
  var sheets = ss.getSheets();
  if (!specs.length || sheets.length !== 1 || ss.getSheetByName(specs[0].name)) return;
  if (sheets[0].getLastRow() === 0 && sheets[0].getLastColumn() === 0) sheets[0].setName(specs[0].name);
}

function headerMap_(sheet) {
  var map = {};
  var width = sheet.getLastColumn();
  if (!width) return map;
  var row = sheet.getRange(1, 1, 1, width).getDisplayValues()[0];
  for (var c = 0; c < row.length; c++) {
    var key = String(row[c]).trim().toLowerCase();
    if (key && !(key in map)) map[key] = c + 1;
  }
  return map;
}

// Headers The Lodge needs that aren't there are added after the last column in use, as plain text columns (so a
// phone number stays "+1 503…" and a date stays as typed).
function ensureHeaders_(sheet, spec) {
  var map = headerMap_(sheet);
  var missing = spec.headers.filter(function (h) { return !(h.toLowerCase() in map); });
  if (!missing.length) return [];
  var start = sheet.getLastColumn() + 1;
  var need = start + missing.length - 1;
  if (sheet.getMaxColumns() < need) sheet.insertColumnsAfter(sheet.getMaxColumns(), need - sheet.getMaxColumns());
  var rows = sheet.getMaxRows();
  sheet.getRange(1, start, rows, missing.length).setNumberFormat("@");
  sheet.getRange(1, start, 1, missing.length).setValues([missing]).setFontWeight("bold");
  for (var i = 0; i < missing.length; i++) {
    var h = missing[i];
    var col = start + i;
    var note = (spec.notes || {})[h];
    if (note) sheet.getRange(1, col).setNote(note);
    if ((spec.quiet || []).indexOf(h) >= 0) {
      var column = sheet.getRange(1, col, rows, 1);
      column.setFontColor("#8a8a8a");
      column.protect().setDescription("The Lodge: " + h).setWarningOnly(true);
    }
  }
  if (sheet.getFrozenRows() < 1) sheet.setFrozenRows(1);
  return missing;
}

// ── Writing ─────────────────────────────────────────────────────────

// tabs: {name: {keys: {id, name}, updates: [{at, cells: {header: {was, value}}}], appends: [{header: value}],
// deletes: [at]}}. "at" finds a row: {row, id, name}, any of them. The row number is tried first; if that row no
// longer fits (rows were sorted or inserted since), the one row whose id and name cells match, and none if several do.
function write_(ss, tabs) {
  var done = { updated: 0, skipped: 0, appended: 0, deleted: 0 };
  for (var name in tabs) {
    var sheet = ss.getSheetByName(name);
    if (!sheet) continue;
    var ops = tabs[name];
    var keys = ops.keys || {};
    var map = headerMap_(sheet);
    var width = sheet.getLastColumn();
    var last = sheet.getLastRow();
    var data = last >= 2 && width ? sheet.getRange(2, 1, last - 1, width).getDisplayValues() : [];
    var finder = locator_(data, map, keys);

    var updates = ops.updates || [];
    for (var u = 0; u < updates.length; u++) {
      var row = finder(updates[u].at);
      var cells = updates[u].cells || {};
      for (var h in cells) {
        var c = map[h.toLowerCase()];
        if (!row || !c) {
          done.skipped++;
          continue;
        }
        var now = c <= width ? String(data[row - 2][c - 1]) : "";
        if (now !== cells[h].was) {   // someone changed it since The Lodge read it: theirs stands
          done.skipped++;
          continue;
        }
        sheet.getRange(row, c).setNumberFormat("@").setValue(cells[h].value);
        if (c <= width) data[row - 2][c - 1] = cells[h].value;
        done.updated++;
      }
    }

    // Rows to delete are found before any are added, so a new row is never mistaken for one.
    var gone = [];
    var deletes = ops.deletes || [];
    for (var d = 0; d < deletes.length; d++) {
      var at = finder(deletes[d]);
      if (at && gone.indexOf(at) < 0) gone.push(at);
    }

    var appends = ops.appends || [];
    if (appends.length) {
      var cols = sheet.getLastColumn();
      var first = Math.max(sheet.getLastRow(), 1) + 1;
      var end = first + appends.length - 1;
      if (sheet.getMaxRows() < end) sheet.insertRowsAfter(sheet.getMaxRows(), end - sheet.getMaxRows());
      var values = appends.map(function (a) {
        var out = [];
        for (var i = 0; i < cols; i++) out.push("");
        for (var k in a) {
          var col = map[k.toLowerCase()];
          if (col && col <= cols) out[col - 1] = a[k];
        }
        return out;
      });
      sheet.getRange(first, 1, values.length, cols).setNumberFormat("@").setValues(values);
      done.appended += values.length;
    }

    gone.sort(function (a, b) { return b - a; });
    for (var g = 0; g < gone.length; g++) {
      if (sheet.getMaxRows() <= sheet.getFrozenRows() + 1) sheet.getRange(gone[g], 1, 1, sheet.getLastColumn()).clearContent();
      else sheet.deleteRow(gone[g]);
      done.deleted++;
    }
  }
  SpreadsheetApp.flush();
  return done;
}

function locator_(data, map, keys) {
  var idCol = keys.id ? map[keys.id.toLowerCase()] : null;
  var nameCol = keys.name ? map[keys.name.toLowerCase()] : null;
  function value(r, c) {
    return c && c <= data[r].length ? String(data[r][c - 1]) : "";
  }
  function fits(r, at) {
    if (at.id !== undefined && at.id !== null && value(r, idCol) !== at.id) return false;
    if (at.name !== undefined && at.name !== null && value(r, nameCol) !== at.name) return false;
    return true;
  }
  return function (at) {
    if (!at) return null;
    if (at.row && at.row >= 2 && at.row - 2 < data.length && fits(at.row - 2, at)) return at.row;
    if ((at.id === undefined || at.id === "") && at.name === undefined) return null;   // too vague to search for
    var found = null;
    for (var r = 0; r < data.length; r++) {
      if (!fits(r, at)) continue;
      if (found !== null) return null;   // two rows fit: better to leave it for the next sync than pick the wrong one
      found = r + 2;
    }
    return found;
  };
}
"""
