const { test, expect } = require('@playwright/test');
const fs = require('fs');

const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8000';

/**
 * Read a test credential or configuration value from process env, then .env.
 * @param {string} key Environment variable name to read.
 * @param {string} fallback Value used when neither process env nor .env has the key.
 * @returns {string} Resolved configuration value.
 */
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

/**
 * Log in to the backend console with the configured admin test account.
 * @param {import('@playwright/test').Page} page Playwright page instance.
 * @returns {Promise<void>} Resolves after the Today Control screen is visible.
 */
async function login(page) {
  await page.goto(`${backendUrl}/console`, { waitUntil: 'domcontentloaded', timeout: 20_000 });
  await expect(page.getByRole('heading', { name: 'Dantabot Control Console' })).toBeVisible();
  await page.locator('#loginUsername').fill(envValue('APP_ADMIN_USERNAME', 'admin'));
  await page.locator('#loginPassword').fill(envValue('APP_ADMIN_PASSWORD', 'test1234'));
  await page.getByRole('button', { name: '로그인' }).click();
  await expect(page.getByRole('heading', { name: 'Today Control' })).toBeVisible();
}

/**
 * Open a console screen from the sidebar and wait for its page heading.
 * @param {import('@playwright/test').Page} page Playwright page instance.
 * @param {string|RegExp} buttonName Accessible name of the sidebar button.
 * @param {string} headingName Expected screen heading.
 * @returns {Promise<void>} Resolves after the target screen is visible.
 */
async function openScreen(page, buttonName, headingName) {
  await page.getByRole('button', { name: buttonName }).click();
  await expect(page.getByRole('heading', { name: headingName })).toBeVisible();
}

test('Phase 3: review-audit today API responds', async ({ request }) => {
  const res = await request.get(`${backendUrl}/api/v1/review-audit/today`, { timeout: 15_000 });
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.ok).toBe(true);
});

test('Phase 3: learning-memory today API responds', async ({ request }) => {
  const res = await request.get(`${backendUrl}/api/v1/learning-memory/today`, { timeout: 15_000 });
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.ok).toBe(true);
});

test('Phase 3: learning-memory active API responds', async ({ request }) => {
  const res = await request.get(`${backendUrl}/api/v1/learning-memory/active`, { timeout: 15_000 });
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.ok).toBe(true);
});

test('Phase 3: review-audit run returns ok', async ({ request }) => {
  const res = await request.post(`${backendUrl}/api/v1/review-audit/run`, { timeout: 30_000 });
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.ok).toBe(true);
});

test('Phase 3: learning-memory build returns ok', async ({ request }) => {
  const res = await request.post(`${backendUrl}/api/v1/learning-memory/build`, { timeout: 30_000 });
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.ok).toBe(true);
});

test('Phase 3: Review & Audit screen has Learning Memory section', async ({ page }) => {
  await login(page);
  await openScreen(page, /Review & Audit/i, 'Review & Audit');
  await expect(page.locator('#ra-learning-memory')).toBeVisible();
  await expect(page.locator('#ra-profile-performance')).toBeVisible();
});

test('Phase 3: KIS System Test has S11 card', async ({ page }) => {
  await login(page);
  await openScreen(page, /KIS System Test/i, 'KIS System Test');
  await expect(page.locator('#test-s11').first()).toBeVisible();
  await expect(page.getByText('Learning Memory Builder').first()).toBeVisible();
});
