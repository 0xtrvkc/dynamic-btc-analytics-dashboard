// Scrapes the all-time MVRV series from blockchain.com's chart page and writes mvrv.json.
//
// Data source note: this reads the JSON the public chart page itself loads
// (api.blockchain.info/charts/mvrv). It is not a documented API and can change
// without notice; check blockchain.com's terms before relying on it. If the scrape
// fails or the result looks wrong, this script exits non-zero and the existing
// mvrv.json is left untouched, so the dashboard keeps serving the last good data.
//
// Usage: node scripts/update_mvrv.js            (writes mvrv.json)
//        node scripts/update_mvrv.js --check F  (only validate file F against mvrv.json)

const fs = require('fs');
const path = require('path');
const os = require('os');

const OUT = 'mvrv.json';
const MIN_POINT_RETENTION = 0.95; // refuse to shrink history by more than 5%
const MAX_FIRST_DATE_SHIFT_DAYS = 3;
const MVRV_MIN = 0.05, MVRV_MAX = 20; // MVRV has historically stayed roughly within 0.3–8
const DAY = 86400000;

// Normalise any blockchain.com MVRV payload to {metric1, metric2, mvrv:[{x(ms),y}]},
// one point (the last sample) per UTC day.
function normalise(json) {
  const arr = Array.isArray(json?.mvrv) ? json.mvrv : Array.isArray(json?.values) ? json.values : null;
  if (!arr) throw new Error('payload has no mvrv/values array');
  const byDay = new Map();
  for (const p of arr) {
    let x = Number(p?.x), y = Number(p?.y);
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
    if (Math.abs(x) < 1e11) x *= 1000; // seconds -> milliseconds
    const day = Math.floor(x / DAY);
    const prev = byDay.get(day);
    if (!prev || x >= prev.x) byDay.set(day, { x, y });
  }
  const mvrv = [...byDay.values()].sort((a, b) => a.x - b.x);
  return { metric1: 'mvrv', metric2: 'market-price', mvrv };
}

// Throws when `next` is malformed or looks like a broken upstream response compared with `prev`.
function validate(next, prev) {
  const pts = next.mvrv;
  if (next.metric1 !== 'mvrv') throw new Error('metric1 is not mvrv');
  if (!Array.isArray(pts) || pts.length < 100) throw new Error('too few points: ' + (pts || []).length);
  for (let i = 0; i < pts.length; i++) {
    const { x, y } = pts[i];
    if (!Number.isFinite(x) || !Number.isFinite(y)) throw new Error('non-finite point at index ' + i);
    if (y < MVRV_MIN || y > MVRV_MAX) throw new Error(`implausible MVRV ${y} on ${new Date(x).toISOString().slice(0, 10)}`);
    if (i && x <= pts[i - 1].x) throw new Error('timestamps not strictly increasing at index ' + i);
  }
  if (pts.at(-1).x > Date.now() + DAY) throw new Error('latest point is in the future');
  if (prev?.mvrv?.length) {
    const old = prev.mvrv;
    if (pts.length < old.length * MIN_POINT_RETENTION)
      throw new Error(`new file has ${pts.length} points vs ${old.length} before (>5% loss)`);
    if (Math.abs(pts[0].x - old[0].x) > MAX_FIRST_DATE_SHIFT_DAYS * DAY)
      throw new Error('history start moved from ' + new Date(old[0].x).toISOString().slice(0, 10) +
        ' to ' + new Date(pts[0].x).toISOString().slice(0, 10));
    if (pts.at(-1).x < old.at(-1).x - DAY) throw new Error('new file ends before the existing one');
  }
}

function readPrevious() {
  try { return JSON.parse(fs.readFileSync(OUT, 'utf8')); } catch { return null; }
}

async function scrape() {
  const { chromium } = require('playwright');
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({ acceptDownloads: true });
    const page = await context.newPage();
    let captured = null;
    // The page requests 1 year of sampled data; re-issue that request for all-time, unsampled data.
    await page.route('**/api.blockchain.info/charts/mvrv**', async route => {
      const upgraded = route.request().url().replace('timespan=1year', 'timespan=all').replace('sampled=true', 'sampled=false');
      try {
        const res = await page.request.fetch(upgraded);
        const json = JSON.parse(await res.text());
        if (Array.isArray(json.values) && json.values.length > 100) captured = json;
      } catch (e) { console.log('Upgraded request failed: ' + e.message); }
      await route.continue();
    });
    console.log('Navigating to MVRV chart page...');
    await page.goto('https://www.blockchain.com/explorer/charts/mvrv', { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForTimeout(15000);
    if (captured) { console.log('Captured all-time data via request intercept.'); return captured; }

    console.log('Intercept did not fire. Falling back to the ALL + Download JSON buttons...');
    const allBtn = page.locator('button', { hasText: /^All$/i });
    await allBtn.first().waitFor({ state: 'visible', timeout: 30000 });
    await allBtn.first().click();
    await page.waitForTimeout(35000);
    const [download] = await Promise.all([
      page.waitForEvent('download', { timeout: 30000 }),
      page.locator('button', { hasText: /download json/i }).first().click(),
    ]);
    const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'mvrv-')), 'mvrv.json');
    await download.saveAs(file);
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } finally {
    await browser.close();
  }
}

(async () => {
  const prev = readPrevious();
  const checkIdx = process.argv.indexOf('--check');
  const raw = checkIdx > 0 ? JSON.parse(fs.readFileSync(process.argv[checkIdx + 1], 'utf8')) : await scrape();
  const next = normalise(raw);
  validate(next, prev);
  const last = next.mvrv.at(-1);
  console.log(`Validation passed: ${next.mvrv.length} daily points, latest ${new Date(last.x).toISOString().slice(0, 10)} MVRV=${last.y.toFixed(4)}`);
  if (checkIdx > 0) return;
  const tmp = OUT + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(next));
  fs.renameSync(tmp, OUT);
  console.log('Saved ' + OUT);
})().catch(err => {
  console.error('ERROR: ' + err.message + ' — mvrv.json left unchanged.');
  process.exit(1);
});
