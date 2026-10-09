// Runs apps_script/Code.gs in Node with an in-memory sheet.
// usage: node apps_script_harness.js <requests.json>
// requests.json: [{"token": "...", "body": {...}}, ...]
// prints {"responses": [...], "sheet": [[header...], [row...], ...]}
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const rows = [];
const isoDate = /^\d{4}-\d{2}-\d{2}$/;
const sheet = {
  getLastRow: () => rows.length,
  appendRow: r => rows.push(r.slice()),
  getDataRange: () => ({ getValues: () => rows.map(r => r.slice()) }),
  // Like Sheets, store yyyy-MM-dd strings as Date values.
  getRange: (row, col, n, w) => ({
    setValues: vals => vals.forEach((v, i) => {
      rows[row - 1 + i] = v.map(c => (typeof c === 'string' && isoDate.test(c)) ? new Date(c + 'T00:00:00+08:00') : c);
    }),
  }),
};
const ctx = {
  SpreadsheetApp: { getActiveSpreadsheet: () => ({
    getSheetByName: () => (rows.length || sheet.created ? sheet : null),
    insertSheet: () => { sheet.created = true; return sheet; },
    getSpreadsheetTimeZone: () => 'Asia/Taipei',
  }) },
  LockService: { getScriptLock: () => ({ waitLock() {}, releaseLock() {} }) },
  Utilities: { formatDate: d => new Date(d.getTime() + 8 * 3600e3).toISOString().slice(0, 10) },
  ContentService: {
    MimeType: { JSON: 'json' },
    createTextOutput: s => ({ text: s, setMimeType() { return this; } }),
  },
  JSON, Set, Object, String,
};
vm.createContext(ctx);
const src = fs.readFileSync(path.join(__dirname, '..', 'apps_script', 'Code.gs'), 'utf8')
  .replace(/const TOKEN = '[^']*'/, "const TOKEN = 'test-token-0123456789'");
vm.runInContext(src + '\nthis.doPost = doPost;', ctx);

const requests = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const responses = requests.map(r => JSON.parse(ctx.doPost({
  parameter: { token: r.token }, postData: { contents: JSON.stringify(r.body) },
}).text));
const out = rows.map(r => r.map(c => c instanceof Date ? ctx.Utilities.formatDate(c) : c));
console.log(JSON.stringify({ responses, sheet: out }));
