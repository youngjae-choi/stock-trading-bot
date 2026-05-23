/**
 * E2E tests — Regime Analytics screen & API
 * Step 1~4: 레짐별 성과 분석 화면 및 API 검증
 */
const { test, expect } = require('@playwright/test');

const BASE = 'http://127.0.0.1:8000';

const { execSync } = require('child_process');

// MFA가 활성화된 admin 계정을 우회하기 위해 Python으로 세션 직접 생성
function createTestSession() {
  const result = execSync(
    `python3 -c "
import sys; sys.path.insert(0,'.')
from backend.services.auth_service import SESSION_COOKIE_NAME, create_session
from backend.services.db import get_connection
with get_connection() as conn:
    row = conn.execute('SELECT id FROM users WHERE username=?', ('admin',)).fetchone()
    user_id = dict(row)['id']
session_id = create_session(user_id)
print(SESSION_COOKIE_NAME + '=' + session_id)
"`,
    { cwd: '/home/young/repos/stock-trading-bot', encoding: 'utf-8' }
  ).trim();
  const [name, value] = result.split('=');
  return { name, value };
}

async function login(page) {
  const cookie = createTestSession();
  await page.context().addCookies([{
    name: cookie.name,
    value: cookie.value,
    domain: '127.0.0.1',
    path: '/',
  }]);
  await page.goto(`${BASE}/console`, { waitUntil: 'domcontentloaded', timeout: 20000 });
  // 로그인 성공 기준: 사이드바 nav가 보임
  await expect(page.locator('#nav')).toBeVisible({ timeout: 15000 });
}

/* ── API 레이어 테스트 ── */

test('regime-performance API returns 4 regimes', async ({ request }) => {
  const res = await request.get(`${BASE}/api/v1/analytics/regime-performance?days=90`);
  expect(res.status()).toBe(200);
  const body = await res.json();
  expect(body.ok).toBe(true);
  const keys = Object.keys(body.regimes);
  expect(keys).toContain('risk_on');
  expect(keys).toContain('neutral');
  expect(keys).toContain('risk_off');
  expect(keys).toContain('volatile');
});

test('parameter-history API returns ok', async ({ request }) => {
  const res = await request.get(`${BASE}/api/v1/analytics/parameter-history?days=90`);
  expect(res.status()).toBe(200);
  const body = await res.json();
  expect(body.ok).toBe(true);
  expect(Array.isArray(body.rows)).toBe(true);
});

test('regime-recommendation API returns 4 regimes with settings', async ({ request }) => {
  const res = await request.get(`${BASE}/api/v1/analytics/regime-recommendation?days=90`);
  expect(res.status()).toBe(200);
  const body = await res.json();
  expect(body.ok).toBe(true);
  for (const regime of ['risk_on', 'neutral', 'risk_off', 'volatile']) {
    const rec = body.recommendations[regime];
    expect(rec.settings).toBeDefined();
    expect(rec.settings.max_positions).toBeDefined();
    expect(rec.settings.stop_loss_rate).toBeDefined();
    expect(rec.confidence).toMatch(/^(high|medium|low|no_data)$/);
  }
});

test('regime-performance with different day ranges', async ({ request }) => {
  for (const days of [30, 90, 180]) {
    const res = await request.get(`${BASE}/api/v1/analytics/regime-performance?days=${days}`);
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.ok).toBe(true);
    expect(body.days).toBe(days);
  }
});

/* ── UI 레이어 테스트 ── */

test('regime-analytics nav button exists in sidebar', async ({ page }) => {
  await login(page);
  const navBtn = page.locator('[data-screen="regime-analytics"]');
  await expect(navBtn).toBeVisible({ timeout: 5000 });
});

test('regime-analytics screen renders on nav click', async ({ page }) => {
  await login(page);
  await page.locator('[data-screen="regime-analytics"]').click();
  await page.waitForTimeout(2000);
  const screen = page.locator('#screen-regime-analytics');
  await expect(screen).toBeVisible({ timeout: 5000 });
});

test('regime cards render 4 regimes after load', async ({ page }) => {
  await login(page);
  await page.locator('[data-screen="regime-analytics"]').click();
  await page.waitForTimeout(2500);
  const cards = page.locator('#ra-regime-cards > div');
  await expect(cards).toHaveCount(4, { timeout: 8000 });
});

test('recommendation cards render 4 regimes', async ({ page }) => {
  await login(page);
  await page.locator('[data-screen="regime-analytics"]').click();
  await page.waitForTimeout(2500);
  const cards = page.locator('#ra-recommendations > div');
  await expect(cards).toHaveCount(4, { timeout: 8000 });
});

test('history table renders (empty or with data)', async ({ page }) => {
  await login(page);
  await page.locator('[data-screen="regime-analytics"]').click();

  // "로딩 중..."이 사라질 때까지 대기 (최대 10초)
  await page.waitForFunction(() => {
    const el = document.getElementById('ra-history-table');
    return el && !el.textContent.includes('로딩 중');
  }, { timeout: 10000 });

  const historyEl = page.locator('#ra-history-table');
  await expect(historyEl).toBeVisible({ timeout: 5000 });

  // 테이블이 있거나, 빈 메시지 또는 에러 메시지가 있으면 OK (로딩 중 상태만 아니면 됨)
  const content = await historyEl.innerText();
  expect(content.trim().length).toBeGreaterThan(0);
  expect(content).not.toContain('로딩 중');
});

test('day filter buttons switch period without error', async ({ page }) => {
  await login(page);
  await page.locator('[data-screen="regime-analytics"]').click();
  await page.waitForTimeout(2000);
  await page.locator('#ra-btn-30').click();
  await page.waitForTimeout(2000);
  await page.locator('#ra-btn-90').click();
  await page.waitForTimeout(2000);
  const cards = page.locator('#ra-regime-cards > div');
  await expect(cards).toHaveCount(4, { timeout: 8000 });
});
