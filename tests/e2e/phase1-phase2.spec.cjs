const { test, expect } = require('@playwright/test');
const fs = require('fs');

const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8000';

function envValue(key, fallback = '') {
  if (process.env[key]) return process.env[key];
  try {
    const text = fs.readFileSync('.env', 'utf8');
    const line = text.split(/\r?\n/).find((item) => item.startsWith(`${key}=`));
    return line ? line.slice(key.length + 1).trim() : fallback;
  } catch (_error) {
    return fallback;
  }
}

async function login(page) {
  await page.goto(`${backendUrl}/console`, { waitUntil: 'domcontentloaded', timeout: 20_000 });
  await expect(page.getByRole('heading', { name: 'Dantabot Control Console' })).toBeVisible();
  await page.locator('#loginUsername').fill(envValue('APP_ADMIN_USERNAME', 'admin'));
  await page.locator('#loginPassword').fill(envValue('APP_ADMIN_PASSWORD'));
  await page.getByRole('button', { name: '로그인' }).click();
  await expect(page.getByRole('heading', { name: 'Today Control' })).toBeVisible();
}

async function openScreen(page, buttonName, headingName) {
  await page.getByRole('button', { name: buttonName }).click();
  await expect(page.getByRole('heading', { name: headingName })).toBeVisible();
}

function isKstMarketHours(date = new Date()) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Seoul',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(date);
  const hour = Number(parts.find((part) => part.type === 'hour').value);
  const minute = Number(parts.find((part) => part.type === 'minute').value);
  const minutes = hour * 60 + minute;
  return minutes >= 9 * 60 && minutes <= 15 * 60 + 30;
}

test('Phase 1: console html no longer contains removed RulePack generation labels', async ({ request }) => {
  const response = await request.get(`${backendUrl}/console`, { timeout: 15_000 });
  expect(response.ok()).toBeTruthy();

  const html = await response.text();
  expect(html).not.toContain('RulePack 생성');
  expect(html).not.toContain('rulepack-gen');
  expect(html).not.toContain('S5 RulePack');
});

test('Phase 1: Daily Plan & RulePack screen exposes refresh and advanced actions', async ({ page }) => {
  await login(page);
  await openScreen(page, /Daily Plan & RulePack/i, 'Daily Plan & RulePack');

  await expect(page.getByRole('button', { name: 'Daily Plan 생성', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '새로고침', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: /고급 작업/ })).toBeVisible();

  await page.getByRole('button', { name: /고급 작업/ }).click();
  await expect(page.locator('#dp-advanced-menu')).toBeVisible();
  await expect(page.locator('#dp-advanced-menu')).toContainText('S5 수동 재실행');
});

test('Phase 1: KIS System Test includes S5-V validation card', async ({ page }) => {
  await login(page);
  await openScreen(page, /KIS System Test/i, 'KIS System Test');

  await expect(page.getByText('S5-V').first()).toBeVisible();
  await expect(page.getByText('Daily Plan Validation')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Daily Plan 검증 실행' })).toBeVisible();
});

test('Phase 1: Settings includes expanded scheduler items', async ({ page }) => {
  await login(page);
  await openScreen(page, /Settings/i, 'Settings');

  await expect(page.getByText('S5 Daily Plan 자동 생성')).toBeVisible();
  await expect(page.getByText('S5-V Daily Plan 자동 검증')).toBeVisible();
  await expect(page.getByText('S10 Review & Audit')).toBeVisible();
  await expect(page.getByText('S11 Learning Memory Builder')).toBeVisible();
});

test('Phase 2: daily plan today API returns expected payload shape', async ({ request }) => {
  const response = await request.get(`${backendUrl}/api/v1/daily-plan/today`, { timeout: 15_000 });
  expect(response.ok()).toBeTruthy();

  const body = await response.json();
  expect(body.ok).toBe(true);
  expect(body).toHaveProperty('payload');

  if (body.payload !== null) {
    expect(body.payload).toHaveProperty('id');
    expect(body.payload).toHaveProperty('status');
    expect(body.payload).toHaveProperty('creation_mode');
    expect(body.payload).toHaveProperty('created_by');
  }
});

test('Phase 2: manual daily plan generation is blocked only during KST market hours', async ({ request }) => {
  const response = await request.post(`${backendUrl}/api/v1/daily-plan/generate`, { timeout: 30_000 });

  if (isKstMarketHours()) {
    expect(response.status()).toBe(403);
    return;
  }

  expect(response.status()).not.toBe(403);
  expect([200, 500]).toContain(response.status());
});

test('Phase 2: wrong admin password is rejected', async ({ request }) => {
  const response = await request.post(`${backendUrl}/api/v1/auth/login`, {
    data: {
      username: 'admin',
      password: 'wrongpassword',
    },
    timeout: 15_000,
  });

  expect(response.status()).toBe(401);
});
