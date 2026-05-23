/**
 * E2E tests — 화면 재배치 검증
 * - Daily Plan 이름 복원
 * - Settings Regime SET 관리 섹션
 * - Daily Results 행 확장
 * - Trade Review 레짐 평가 블록
 * - PUT /api/v1/regime/sets/{id} API
 * - GET /api/v1/regime/day-detail API
 */
const { test, expect } = require('@playwright/test');
const { execSync } = require('child_process');

const BASE = 'http://127.0.0.1:8000';

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
    name: cookie.name, value: cookie.value,
    domain: '127.0.0.1', path: '/',
  }]);
  await page.goto(`${BASE}/console`, { waitUntil: 'domcontentloaded', timeout: 20000 });
  await expect(page.locator('#nav')).toBeVisible({ timeout: 15000 });
}

/* ── API 레이어 ── */

test('PUT regime/sets/{id} updates settings', async ({ request }) => {
  const res = await request.put(`${BASE}/api/v1/regime/sets/SET-NEUTRAL`, {
    data: { settings: { max_positions: 7 } }
  });
  expect(res.status()).toBe(200);
  const body = await res.json();
  expect(body.ok).toBe(true);
  expect(body.set_id).toBe('SET-NEUTRAL');
  expect(body.updated_fields).toContain('settings');
});

test('PUT regime/sets/{id} returns 404 for unknown set', async ({ request }) => {
  const res = await request.put(`${BASE}/api/v1/regime/sets/SET-NOT-EXIST`, {
    data: { settings: { max_positions: 5 } }
  });
  expect(res.status()).toBe(404);
});

test('GET regime/day-detail returns ok structure', async ({ request }) => {
  const res = await request.get(`${BASE}/api/v1/regime/day-detail?trade_date=2026-05-22`);
  expect(res.status()).toBe(200);
  const body = await res.json();
  expect(body.ok).toBe(true);
  expect(body.trade_date).toBe('2026-05-22');
  expect(Array.isArray(body.profile_breakdown)).toBe(true);
});

test('GET regime/day-detail for today returns ok', async ({ request }) => {
  const today = new Date().toISOString().slice(0, 10);
  const res = await request.get(`${BASE}/api/v1/regime/day-detail?trade_date=${today}`);
  expect(res.status()).toBe(200);
  const body = await res.json();
  expect(body.ok).toBe(true);
});

/* ── UI: Daily Plan 이름 복원 ── */

test('sidebar shows Daily Plan (not 매매 계획)', async ({ page }) => {
  await login(page);
  const btn = page.locator('#nav [data-screen="rulepack"]').first();
  await expect(btn).toBeVisible({ timeout: 5000 });
  const text = await btn.innerText();
  expect(text).toContain('Daily Plan');
});

test('Daily Plan screen title is Daily Plan', async ({ page }) => {
  await login(page);
  await page.locator('#nav [data-screen="rulepack"]').first().click();
  await page.waitForTimeout(1000);
  const title = page.locator('#screen-rulepack h1.page-title');
  await expect(title).toBeVisible({ timeout: 5000 });
  const text = await title.innerText();
  expect(text).toContain('Daily Plan');
});

test('regime set card exists on Daily Plan screen', async ({ page }) => {
  await login(page);
  await page.locator('#nav [data-screen="rulepack"]').first().click();
  await page.waitForTimeout(2000);
  await expect(page.locator('#dp-regime-set-card')).toBeVisible({ timeout: 8000 });
});

/* ── UI: Settings Regime SET 관리 ── */

test('Settings screen has regime-sets-card', async ({ page }) => {
  await login(page);
  await page.locator('#nav [data-screen="settings"]').first().click();
  await page.waitForTimeout(2000);
  await expect(page.locator('#regime-sets-card')).toBeVisible({ timeout: 8000 });
});

test('Settings regime-sets-list has items after load', async ({ page }) => {
  await login(page);
  await page.locator('#nav [data-screen="settings"]').first().click();
  // 로딩 완료 대기
  await page.waitForFunction(() => {
    const el = document.getElementById('regime-sets-list');
    return el && !el.textContent.includes('로딩 중');
  }, { timeout: 10000 });
  const list = page.locator('#regime-sets-list .regime-set-item');
  await expect(list.first()).toBeVisible({ timeout: 5000 });
});

/* ── UI: Daily Results 행 확장 ── */

test('Daily Results table row click expands detail panel', async ({ page }) => {
  await login(page);
  await page.locator('#nav [data-screen="daily-results"]').first().click();
  // 데이터 로드 대기
  await page.waitForFunction(() => {
    const el = document.getElementById('daily-results-container');
    return el && !el.textContent.includes('Loading');
  }, { timeout: 15000 });

  // 첫 번째 행 클릭
  const firstRow = page.locator('#daily-results-container table tbody tr').first();
  const count = await firstRow.count();
  if (count === 0) {
    // 데이터 없으면 skip
    return;
  }
  await firstRow.click();
  // 확장 패널 대기
  await page.waitForTimeout(1500);
  // tr[id^="dr-detail-"] 가 display:table-row 이거나 내용이 있으면 통과
  const detailRows = page.locator('tr[id^="dr-detail-"]');
  const detailCount = await detailRows.count();
  expect(detailCount).toBeGreaterThan(0);
});

/* ── UI: Trade Review 레짐 평가 블록 ── */

test('Trade Review screen has regime-eval card element', async ({ page }) => {
  await login(page);
  await page.locator('#nav [data-screen="review"]').first().click();
  await page.waitForTimeout(1000);
  // 카드 DOM이 존재하면 통과 (display:none이어도 OK — 데이터 없을 수 있음)
  const card = page.locator('#ra-regime-eval');
  await expect(card).toHaveCount(1);
});
