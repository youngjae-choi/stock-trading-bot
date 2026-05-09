const { test, expect } = require('@playwright/test');
const { execFileSync } = require('child_process');
const fs = require('fs');

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

function createSessionCookie() {
  const script = `
import os
from backend.services.auth_service import SESSION_COOKIE_NAME, authenticate_user, create_session
username = os.environ.get('E2E_USERNAME', 'admin')
password = os.environ.get('E2E_PASSWORD', '')
user = authenticate_user(username, password)
if user is None:
    raise SystemExit('INVALID_E2E_CREDENTIALS')
print(f"{SESSION_COOKIE_NAME}={create_session(user['id'])}")
`;
  return execFileSync('python', ['-c', script], {
    cwd: process.cwd(),
    env: {
      ...process.env,
      E2E_USERNAME: envValue('APP_ADMIN_USERNAME', 'admin'),
      E2E_PASSWORD: envValue('APP_ADMIN_PASSWORD'),
    },
    encoding: 'utf8',
  }).trim();
}

async function login(page, url) {
  const [name, value] = createSessionCookie().split('=');
  await page.context().addCookies([{ name, value, url }]);
  await page.goto(`${url}/console`, { waitUntil: 'domcontentloaded', timeout: 20_000 });
  await expect(page.getByRole('heading', { name: 'Today Control' })).toBeVisible();
}

test('fastapi console root serves html shell', async ({ request }) => {
  const url = process.env.BACKEND_URL || 'http://127.0.0.1:8000';
  const response = await request.get(`${url}/`, { timeout: 15_000 });

  expect(response.ok()).toBeTruthy();

  const html = await response.text();
  expect(html).toContain('Dantabot Control Console');
  expect(html).toContain('id="loginForm"');
  expect(html).toContain('id="haltBtn"');
});

test('fastapi console page can call halt api', async ({ page }) => {
  const url = process.env.BACKEND_URL || 'http://127.0.0.1:8000';

  page.on('dialog', async (dialog) => {
    await dialog.accept();
  });

  await login(page, url);
  const haltButton = page.locator('#haltBtn');
  await page.getByRole('button', { name: /System Status/i }).click();
  await expect(page.getByRole('heading', { name: 'System Status' })).toBeVisible();
  const dataScreen = page.locator('#screen-data');
  await expect(dataScreen.getByText('Base RulePack', { exact: true })).toBeVisible();
  await expect(dataScreen.getByText('Risk Profile Pack', { exact: true })).toBeVisible();
  await expect(dataScreen.getByText('Daily Plan', { exact: true })).toBeVisible();

  // Already halted: button shows "운영재개"
  if ((await haltButton.textContent())?.trim() === '운영재개') {
    return;
  }

  await haltButton.click();
  await expect(haltButton).toHaveText('운영재개');
});
