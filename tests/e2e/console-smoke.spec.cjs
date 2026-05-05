const { test, expect } = require('@playwright/test');
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

async function login(page, url) {
  await page.goto(`${url}/console`, { waitUntil: 'domcontentloaded', timeout: 20_000 });
  await expect(page.getByRole('heading', { name: 'Dantabot Control Console' })).toBeVisible();
  await page.locator('#loginUsername').fill(envValue('APP_ADMIN_USERNAME', 'admin'));
  await page.locator('#loginPassword').fill(envValue('APP_ADMIN_PASSWORD'));
  await page.getByRole('button', { name: '로그인' }).click();
  await expect(page.getByRole('heading', { name: "Today's" })).toBeVisible();
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
  await page.getByRole('button', { name: /Data & API/i }).click();
  await expect(page.getByRole('heading', { name: 'Data & API' })).toBeVisible();
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
