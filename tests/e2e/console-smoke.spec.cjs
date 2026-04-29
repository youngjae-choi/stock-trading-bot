const { test, expect } = require('@playwright/test');

test('fastapi console root serves html shell', async ({ request }) => {
  const url = process.env.BACKEND_URL || 'http://127.0.0.1:8000';
  const response = await request.get(`${url}/`, { timeout: 15_000 });

  expect(response.ok()).toBeTruthy();

  const html = await response.text();
  expect(html).toContain('Dantabot Control Console');
  expect(html).toContain('id="haltBtn"');
  expect(html).toContain('API Logs');
});

test('fastapi console page can call halt api', async ({ page }) => {
  const url = process.env.BACKEND_URL || 'http://127.0.0.1:8000';

  page.on('dialog', async (dialog) => {
    await dialog.accept();
  });

  await page.goto(`${url}/console`, { waitUntil: 'domcontentloaded', timeout: 20_000 });
  await expect(page.getByText('Dantabot Control Console')).toBeVisible();
  const haltButton = page.locator('#haltBtn');
  await page.getByRole('button', { name: /API Logs/i }).click();
  await expect(page.getByRole('heading', { name: 'API Logs' })).toBeVisible();
  await expect(page.locator('#apiLogsTableBody')).toContainText('운영 개요 조회');
  await expect(page.locator('#apiLogsTableBody')).toContainText('API 로그 조회');
  await expect(page.locator('#apiLogsTableBody')).toContainText('운영 화면에서 엔진 상태와 리스크 상태를 한 번에 확인');

  if (await haltButton.isDisabled()) {
    await expect(haltButton).toHaveText('중단됨');
    return;
  }

  await haltButton.click();
  await expect(haltButton).toHaveText('중단됨');
});
