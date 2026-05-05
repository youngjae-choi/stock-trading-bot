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

async function openScreen(page, buttonName, headingName) {
  await page.getByRole('button', { name: buttonName }).click();
  await expect(page.getByRole('heading', { name: headingName })).toBeVisible({ timeout: 8_000 });
}

// ── S3 Context Preview ─────────────────────────────────
test('Phase 4A: S3 context-preview API responds with ok', async ({ request }) => {
  const res = await request.get(`${backendUrl}/api/v1/pipeline/S3/context-preview`);
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.ok).toBe(true);
  expect(body.payload).toHaveProperty('scope', 'S3_UNIVERSE_FILTER');
  expect(body.payload).toHaveProperty('memories');
  expect(body.payload).toHaveProperty('count');
});

// ── S4 Context Preview ─────────────────────────────────
test('Phase 4A: S4 context-preview API responds with ok', async ({ request }) => {
  const res = await request.get(`${backendUrl}/api/v1/pipeline/S4/context-preview`);
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.ok).toBe(true);
  expect(body.payload).toHaveProperty('scope', 'S4_HYBRID_SCREENING');
  expect(body.payload).toHaveProperty('memories');
});

// ── S5 Context Preview ─────────────────────────────────
test('Phase 4A: S5 context-preview API responds with ok and overrides_preview', async ({ request }) => {
  const res = await request.get(`${backendUrl}/api/v1/pipeline/S5/context-preview`);
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.ok).toBe(true);
  expect(body.payload).toHaveProperty('scope', 'S5_DAILY_PLAN');
  expect(body.payload).toHaveProperty('overrides_preview');
});

// ── daily-plan today includes used_learning_memory_ids ─
test('Phase 4A: daily-plan today includes used_learning_memory_ids field', async ({ request }) => {
  const res = await request.get(`${backendUrl}/api/v1/daily-plan/today`);
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.ok).toBe(true);
  // used_learning_memory_ids 필드가 존재해야 함 (빈 배열이어도 OK)
  expect(body.payload).toHaveProperty('used_learning_memory_ids');
  expect(Array.isArray(body.payload.used_learning_memory_ids)).toBe(true);
});

// ── Funnel Monitor UI — 메모리 카운트 카드 존재 ────────
test('Phase 4A: Funnel Monitor has memory count cards', async ({ page }) => {
  await login(page);
  await openScreen(page, /Funnel Monitor/i, 'Funnel Monitor');
  await expect(page.locator('#funnel-mem-s3')).toBeVisible();
  await expect(page.locator('#funnel-mem-s4')).toBeVisible();
  await expect(page.locator('#funnel-mem-s5')).toBeVisible();
});

// ── Funnel Monitor UI — Memory refs 컬럼 존재 ─────────
test('Phase 4A: Funnel Monitor candidate table has Memory refs column', async ({ page }) => {
  await login(page);
  await openScreen(page, /Funnel Monitor/i, 'Funnel Monitor');
  await expect(page.getByText('Memory refs').first()).toBeVisible();
});
