// 請把下面這行改成你自己想的一串英數字（至少 16 碼），並在 Dify 的網址後面帶上同一串
const TOKEN = 'CHANGE_ME_TO_A_LONG_RANDOM_STRING';

const SHEET_NAME = 'data';
const HEADERS = ['date', 'asin', 'title', 'category', 'rank', 'price', 'currency',
  'price_tier', 'sub_category', 'brand', 'selling_points',
  'prev_rank', 'rank_change', 'is_new', 'url'];

function doPost(e) {
  if (!e || !e.parameter || e.parameter.token !== TOKEN) return reply({ ok: false, error: 'bad token' });
  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const sheet = ss.getSheetByName(SHEET_NAME) || ss.insertSheet(SHEET_NAME);
    if (sheet.getLastRow() === 0) sheet.appendRow(HEADERS);
    const tz = ss.getSpreadsheetTimeZone();
    const day = v => (Object.prototype.toString.call(v) === '[object Date]') ? Utilities.formatDate(v, tz, 'yyyy-MM-dd') : String(v);

    const incoming = JSON.parse(e.postData.contents).rows || [];
    const existing = sheet.getDataRange().getValues().slice(1);
    const seen = new Set();
    const last = {}; // asin@category -> 最近一次較早日期的名次
    existing.forEach(r => {
      const d = day(r[0]), k = r[1] + '@' + r[3];
      seen.add(d + '@' + k);
      if (!last[k] || d > last[k].d) last[k] = { d: d, rank: r[4] };
    });

    const out = [];
    incoming.forEach(r => {
      const k = r.asin + '@' + r.category;
      if (seen.has(r.date + '@' + k)) return;
      seen.add(r.date + '@' + k);
      const p = (last[k] && last[k].d < r.date) ? last[k] : null;
      const prev = p ? p.rank : '';
      const change = (p && r.rank !== '' && prev !== '') ? prev - r.rank : '';
      const isNew = (!p && existing.length > 0) ? '新進榜' : '';
      out.push([r.date, r.asin, r.title, r.category, r.rank, r.price, r.currency,
        r.price_tier, r.sub_category, r.brand, r.selling_points,
        prev, change, isNew, 'https://www.amazon.com/dp/' + r.asin]);
    });
    if (out.length) {
      sheet.getRange(sheet.getLastRow() + 1, 1, out.length, HEADERS.length).setValues(out);
    }
    return reply({ ok: true, added: out.length, skipped: incoming.length - out.length });
  } catch (err) {
    return reply({ ok: false, error: String(err) });
  } finally {
    lock.releaseLock();
  }
}

function reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
