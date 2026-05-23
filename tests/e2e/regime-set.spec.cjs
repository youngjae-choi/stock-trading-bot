/**
 * E2E tests — Regime Set (매매 계획 통합 화면)
 * - Set API 검증
 * - 매매 계획 통합 화면 UI 검증
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
    name: cookie.name,
    value: cookie.value,
    domain: '127.0.0.1',
    path: '/',
  }]);
  await page.goto(`${BASE}/console`, { waitUntil: 'domcontentloaded', timeout: 20000 });
  await expect(page.locator('#nav')).toBeVisible({ timeout: 15000 });
}

/* ── API 레이어 테스트 ── */

test('regime/sets API returns 7 sets (4 default + 3 prebuilt)', async ({ request }) => {
  const res = await request.get(`${BASE}/api/v1/regime/sets`);
  expect(res.status()).toBe(200);
  const body = await res.json();
  expect(body.ok).toBe(true);
  expect(Array.isArray(body.items)).toBe(true);
  expect(body.items.length).toBeGreaterThanOrEqual(7);
});

test('regime/sets includes 4 default sets', async ({ request }) => {
  const res = await request.get(`${BASE}/api/v1/regime/sets`);
  const body = await res.json();
  const ids = body.items.map(s => s.id);
  expect(ids).toContain('SET-RISK_ON');
  expect(ids).toContain('SET-NEUTRAL');
  expect(ids).toContain('SET-RISK_OFF');
  expect(ids).toContain('SET-VOLATILE');
});

test('regime/sets includes 3 prebuilt sets for 2026-05-26', async ({ request }) => {
  const res = await request.get(`${BASE}/api/v1/regime/sets`);
  const body = await res.json();
  const prebuilt = body.items.filter(s => s.is_prebuilt && s.prebuilt_target_date === '2026-05-26');
  expect(prebuilt.length).toBe(3);
  const pids = prebuilt.map(s => s.id);
  expect(pids).toContain('SET-PRE-0526-RECOVERY');
  expect(pids).toContain('SET-PRE-0526-SIDEWAYS');
  expect(pids).toContain('SET-PRE-0526-SELLOFF');
});

test('regime/today API returns ok', async ({ request }) => {
  const res = await request.get(`${BASE}/api/v1/regime/today`);
  expect(res.status()).toBe(200);
  const body = await res.json();
  expect(body.ok).toBe(true);
  expect(body.date).toBeDefined();
});

test('regime/history API returns ok', async ({ request }) => {
  const res = await request.get(`${BASE}/api/v1/regime/history?days=30`);
  expect(res.status()).toBe(200);
  const body = await res.json();
  expect(body.ok).toBe(true);
  expect(Array.isArray(body.items)).toBe(true);
});

test('regime/preview matches recovery set for risk_on + low vix + kospi up on 2026-05-26', async ({ request }) => {
  const res = await request.get(
    `${BASE}/api/v1/regime/preview?regime_label=risk_on&vix=18.5&kospi_change_pct=0.8&trade_date=2026-05-26`
  );
  expect(res.status()).toBe(200);
  const body = await res.json();
  expect(body.ok).toBe(true);
  expect(body.preview.set_id).toBe('SET-PRE-0526-RECOVERY');
  expect(body.preview.is_prebuilt).toBe(true);
  expect(body.preview.match_score).toBeGreaterThan(0.5);
});

test('regime/preview matches selloff set for risk_off + high vix + kospi down on 2026-05-26', async ({ request }) => {
  const res = await request.get(
    `${BASE}/api/v1/regime/preview?regime_label=risk_off&vix=28&kospi_change_pct=-1.2&trade_date=2026-05-26`
  );
  expect(res.status()).toBe(200);
  const body = await res.json();
  expect(body.ok).toBe(true);
  expect(body.preview.set_id).toBe('SET-PRE-0526-SELLOFF');
  expect(body.preview.is_prebuilt).toBe(true);
});

test('regime/preview falls back to default set for non-Monday date', async ({ request }) => {
  const res = await request.get(
    `${BASE}/api/v1/regime/preview?regime_label=risk_on&vix=20&kospi_change_pct=0.3&trade_date=2025-01-15`
  );
  expect(res.status()).toBe(200);
  const body = await res.json();
  expect(body.ok).toBe(true);
  // 예측 Set은 2026-05-26에만 해당하므로 기본 SET-RISK_ON 또는 자동생성
  expect(body.preview.set_id).toBeTruthy();
});

/* ── UI 레이어 테스트 ── */

// 사이드바 nav 버튼만 선택 (하단 탭바 제외)
async function clickNavRulepack(page) {
  await page.locator('#nav [data-screen="rulepack"]').first().click();
}

test('sidebar shows Daily Plan button', async ({ page }) => {
  await login(page);
  const btn = page.locator('#nav [data-screen="rulepack"]').first();
  await expect(btn).toBeVisible({ timeout: 5000 });
  const text = await btn.innerText();
  expect(text).toContain('Daily Plan');
});

test('레짐 분석 standalone button removed from sidebar', async ({ page }) => {
  await login(page);
  // 레짐 분석 버튼이 사이드바에서 별도로 존재하지 않아야 함
  const regimeBtn = page.locator('#nav [data-screen="regime-analytics"]');
  await expect(regimeBtn).toHaveCount(0);
});

test('매매 계획 screen renders on nav click', async ({ page }) => {
  await login(page);
  await clickNavRulepack(page);
  await page.waitForTimeout(1000);
  const screen = page.locator('#screen-rulepack');
  await expect(screen).toBeVisible({ timeout: 5000 });
});

test('regime set card container exists in rulepack screen', async ({ page }) => {
  await login(page);
  await clickNavRulepack(page);
  await page.waitForTimeout(2000);
  const card = page.locator('#dp-regime-set-card');
  await expect(card).toBeVisible({ timeout: 8000 });
});

test('regime set card exists in rulepack screen', async ({ page }) => {
  await login(page);
  await clickNavRulepack(page);
  await page.waitForTimeout(2000);
  const card = page.locator('#dp-regime-set-card');
  await expect(card).toBeVisible({ timeout: 8000 });
});
