const { test, expect } = require('@playwright/test');
const fs = require('fs');

const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8000';

function envValue(key, fallback = '') {
  if (process.env[key]) return process.env[key];
  try {
    const text = fs.readFileSync('.env', 'utf8');
    const line = text.split(/\r?\n/).find((l) => l.startsWith(`${key}=`));
    return line ? line.slice(key.length + 1).trim() : fallback;
  } catch (_) { return fallback; }
}

async function login(page) {
  await page.goto(`${backendUrl}/console`, { waitUntil: 'domcontentloaded', timeout: 20_000 });
  await page.locator('#loginUsername').fill(envValue('APP_ADMIN_USERNAME', 'admin'));
  await page.locator('#loginPassword').fill(envValue('APP_ADMIN_PASSWORD', ''));
  await page.getByRole('button', { name: '로그인' }).click();
  await expect(page.getByRole('heading', { name: 'Today Control' })).toBeVisible();
}

// ── Shadow Trading ─────────────────────────────────────
test('Phase 5B: create shadow trade via POST', async ({ request }) => {
  // KST date (UTC+9)
  const kstDate = new Date(Date.now() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
  const res = await request.post(`${backendUrl}/api/v1/shadow-trading/`, {
    data: {
      trade_date: kstDate,
      symbol: '005930',
      symbol_name: '삼성전자',
      missed_stage: 'S4_excluded',
      entry_price: 75000,
      entry_time: new Date().toISOString(),
    },
  });
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.ok).toBe(true);
  expect(body.payload.symbol).toBe('005930');
  expect(body.payload.status).toBe('active');
});

test('Phase 5B: get today shadow trades', async ({ request }) => {
  const res = await request.get(`${backendUrl}/api/v1/shadow-trading/today`);
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.ok).toBe(true);
  expect(Array.isArray(body.payload)).toBe(true);
  // 앞서 생성한 삼성전자 포함 확인
  const symbols = body.payload.map((t) => t.symbol);
  expect(symbols).toContain('005930');
});

test('Phase 5B: shadow trading summary', async ({ request }) => {
  const res = await request.get(`${backendUrl}/api/v1/shadow-trading/summary`);
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.ok).toBe(true);
  expect(body.payload).toBeDefined();
});

// ── Missed Opportunity ────────────────────────────────
test('Phase 5B: get today missed opportunities', async ({ request }) => {
  const res = await request.get(`${backendUrl}/api/v1/missed-opportunity/today`);
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.ok).toBe(true);
  expect(Array.isArray(body.payload)).toBe(true);
});

test('Phase 5B: get improvement candidates', async ({ request }) => {
  const res = await request.get(`${backendUrl}/api/v1/missed-opportunity/candidates`);
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.ok).toBe(true);
  expect(Array.isArray(body.payload)).toBe(true);
});

// ── False Positive ────────────────────────────────────
test('Phase 5B: get today false positives', async ({ request }) => {
  const res = await request.get(`${backendUrl}/api/v1/false-positive/today`);
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.ok).toBe(true);
  expect(Array.isArray(body.payload)).toBe(true);
});

// ── Confidence Calibration ────────────────────────────
test('Phase 5B: run confidence calibration', async ({ request }) => {
  const res = await request.post(`${backendUrl}/api/v1/confidence-calibration/run`);
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.ok).toBe(true);
});

test('Phase 5B: get today calibration', async ({ request }) => {
  const res = await request.get(`${backendUrl}/api/v1/confidence-calibration/today`);
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.ok).toBe(true);
  expect(Array.isArray(body.payload)).toBe(true);
});

// ── UI ────────────────────────────────────────────────
test('Phase 5B: Shadow Trading screen is accessible', async ({ page }) => {
  await login(page);
  await page.getByRole('button', { name: /Shadow Trading/i }).click();
  await expect(page.getByRole('heading', { name: 'Shadow Trading' })).toBeVisible();
  await expect(page.locator('#st-list-tbody')).toBeVisible();
});

test('Phase 5B: Missed Opportunity screen is accessible', async ({ page }) => {
  await login(page);
  await page.getByRole('button', { name: /Missed Opportunity/i }).click();
  await expect(page.getByRole('heading', { name: 'Missed Opportunity' })).toBeVisible();
  await expect(page.locator('#mo-all-tbody')).toBeVisible();
});

test('Phase 5B: False Positive screen is accessible', async ({ page }) => {
  await login(page);
  await page.getByRole('button', { name: /False Positive/i }).click();
  await expect(page.getByRole('heading', { name: 'False Positive' })).toBeVisible();
  await expect(page.locator('#fp-list-tbody')).toBeVisible();
});

test('Phase 5B: Confidence Calibration screen is accessible', async ({ page }) => {
  await login(page);
  await page.getByRole('button', { name: /Confidence Cal/i }).click();
  await expect(page.getByRole('heading', { name: 'Confidence Calibration' })).toBeVisible();
  await expect(page.locator('#cc-list-tbody')).toBeVisible();
});
