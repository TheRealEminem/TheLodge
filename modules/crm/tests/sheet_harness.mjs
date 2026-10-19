// A stand-in for Google Sheets and Apps Script: enough of SpreadsheetApp, LockService and ContentService to run the
// shared sheet's script (modules/crm/server/sheet_script.py) the way Google would, against a spreadsheet kept in a
// JSON file. test_sheet.py runs it once per request.
//
//     node sheet_harness.mjs <script.js> <spreadsheet.json>     (the request body on stdin, the reply on stdout)
//
// It is strict where Google is: a range outside the sheet, values of the wrong shape, deleting the last unfrozen row
// and a second tab with the same name all throw. A cell that isn't plain text turns "+1 503" or "007" into a number,
// as Sheets does, so a script that forgets to make its columns plain text shows up in the tests.
import fs from "node:fs";
import vm from "node:vm";

const [scriptPath, statePath] = process.argv.slice(2);
const state = JSON.parse(fs.readFileSync(statePath, "utf8"));
const body = fs.readFileSync(0, "utf8");

function fail(message) {
  throw new Error(message);
}

class Range {
  constructor(sheet, row, col, rows, cols) {
    if (row < 1 || col < 1 || rows < 1 || cols < 1 || row + rows - 1 > sheet.s.maxRows || col + cols - 1 > sheet.s.maxCols) {
      fail("The coordinates of the range are outside the dimensions of the sheet.");
    }
    Object.assign(this, { sheet, row, col, rows, cols });
  }
  each(fn) {
    for (let r = 0; r < this.rows; r++) for (let c = 0; c < this.cols; c++) fn(this.row + r, this.col + c, r, c);
  }
  getDisplayValues() {
    const out = [];
    for (let r = 0; r < this.rows; r++) {
      out.push([]);
      for (let c = 0; c < this.cols; c++) out[r].push(this.sheet.get(this.row + r, this.col + c));
    }
    return out;
  }
  setValues(values) {
    if (values.length !== this.rows || values.some((row) => row.length !== this.cols)) {
      fail(`The number of rows or columns in the data does not match the range (${this.rows} by ${this.cols}).`);
    }
    this.each((r, c, i, j) => this.sheet.put(r, c, values[i][j]));
    return this;
  }
  setValue(value) {
    this.each((r, c) => this.sheet.put(r, c, value));
    return this;
  }
  setNumberFormat(format) {
    const whole = this.row === 1 && this.rows === this.sheet.s.maxRows;
    this.each((r, c) => {
      if (whole) {
        if (!this.sheet.s.textCols.includes(c)) this.sheet.s.textCols.push(c);
      } else {
        this.sheet.s.textCells[`${r}:${c}`] = format === "@";
      }
    });
    return this;
  }
  clearContent() {
    this.each((r, c) => this.sheet.put(r, c, ""));
    return this;
  }
  setFontWeight(weight) {
    this.each((r, c) => (this.sheet.s.bold[`${r}:${c}`] = weight === "bold"));
    return this;
  }
  setFontColor() {
    return this;
  }
  setNote(note) {
    this.each((r, c) => (this.sheet.s.notes[`${r}:${c}`] = note));
    return this;
  }
  protect() {
    const p = { range: [this.row, this.col, this.rows, this.cols], description: "", warningOnly: false };
    this.sheet.s.protections.push(p);
    const handle = {
      setDescription: (d) => ((p.description = d), handle),
      setWarningOnly: (w) => ((p.warningOnly = w), handle),
    };
    return handle;
  }
}

class Sheet {
  constructor(s) {
    this.s = s;
  }
  isText(r, c) {
    const cell = this.s.textCells[`${r}:${c}`];
    return cell !== undefined ? cell : this.s.textCols.includes(c);
  }
  get(r, c) {
    return (this.s.cells[r - 1] || [])[c - 1] ?? "";
  }
  put(r, c, value) {
    let v = value === null || value === undefined ? "" : String(value);
    if (!this.isText(r, c) && /^[+-]?\d+(\.\d+)?$/.test(v.trim())) v = String(Number(v));
    while (this.s.cells.length < r) this.s.cells.push([]);
    const row = this.s.cells[r - 1];
    while (row.length < c) row.push("");
    row[c - 1] = v;
  }
  getName() {
    return this.s.name;
  }
  setName(name) {
    this.s.name = name;
    return this;
  }
  getLastRow() {
    for (let r = this.s.cells.length; r >= 1; r--) if (this.s.cells[r - 1].some((v) => v !== "")) return r;
    return 0;
  }
  getLastColumn() {
    let last = 0;
    for (const row of this.s.cells) for (let c = row.length; c > last; c--) if (row[c - 1] !== "") last = c;
    return last;
  }
  getMaxRows() {
    return this.s.maxRows;
  }
  getMaxColumns() {
    return this.s.maxCols;
  }
  insertColumnsAfter(after, n) {
    if (after !== this.s.maxCols) fail("the stand-in only adds columns at the end");
    this.s.maxCols += n;
    return this;
  }
  insertRowsAfter(after, n) {
    if (after !== this.s.maxRows) fail("the stand-in only adds rows at the end");
    this.s.maxRows += n;
    return this;
  }
  getRange(row, col, rows = 1, cols = 1) {
    return new Range(this, row, col, rows, cols);
  }
  getFrozenRows() {
    return this.s.frozen;
  }
  setFrozenRows(n) {
    this.s.frozen = n;
    return this;
  }
  deleteRow(row) {
    if (row < 1 || row > this.s.maxRows) fail("Those rows are out of bounds.");
    if (this.s.maxRows - this.s.frozen <= 1) fail("Sorry, it is not possible to delete all non-frozen rows.");
    this.s.cells.splice(row - 1, 1);
    this.s.maxRows -= 1;
    const moved = {};
    for (const [key, v] of Object.entries(this.s.textCells)) {
      const [r, c] = key.split(":").map(Number);
      if (r !== row) moved[`${r > row ? r - 1 : r}:${c}`] = v;
    }
    this.s.textCells = moved;
    return this;
  }
}

function blankSheet(name) {
  return { name, cells: [], maxRows: 1000, maxCols: 26, frozen: 0, textCols: [], textCells: {}, notes: {}, bold: {}, protections: [] };
}

const spreadsheet = {
  getName: () => state.name,
  getUrl: () => state.url,
  getSheets: () => state.sheets.map((s) => new Sheet(s)),
  getSheetByName: (name) => {
    const s = state.sheets.find((x) => x.name === name);
    return s ? new Sheet(s) : null;
  },
  insertSheet: (name) => {
    if (state.sheets.some((x) => x.name === name)) fail(`A sheet with the name "${name}" already exists.`);
    const s = blankSheet(name);
    state.sheets.push(s);
    return new Sheet(s);
  },
};

let locked = false;
const context = vm.createContext({
  SpreadsheetApp: { getActiveSpreadsheet: () => spreadsheet, flush: () => {} },
  LockService: {
    getScriptLock: () => ({
      waitLock: () => {
        if (state.busy) fail("Lock timeout: another process was holding the lock for too long.");
        locked = true;
      },
      releaseLock: () => (locked = false),
    }),
  },
  ContentService: {
    MimeType: { JSON: "application/json" },
    createTextOutput: (text) => ({ setMimeType: () => ({ text }) }),
  },
  JSON,
  String,
  Math,
  Error,
});
vm.runInContext(fs.readFileSync(scriptPath, "utf8"), context, { filename: "sheet-script.gs" });
const reply = body ? context.doPost({ postData: { contents: body } }) : context.doGet({});
if (locked) fail("the script left its lock held");
fs.writeFileSync(statePath, JSON.stringify(state));
process.stdout.write(reply.text);
