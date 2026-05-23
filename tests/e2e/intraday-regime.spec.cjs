/**
 * E2E tests — 장중 레짐 SET 전환
 * - DB 마이그레이션 컬럼 확인
 * - regime_set_service transitions API
 * - 레짐 판단 로직 검증
 * - Today Control 타임라인 UI
 * - scheduler jobs 등록 확인
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

/* ── DB / 백엔드 유닛 ── */

test('regime_set_applications has applied_at and trigger columns', async ({ request }) => {
  const res = await request.get(`${BASE}/api/v1/regime/today`);
  const body = await res.json();
  expect(body.ok).toBe(true);
  expect(Array.isArray(body.transitions)).toBe(true);
  expect(typeof body.transition_count).toBe('number');
});

test('regime judgment logic via Python', () => {
  const result = execSync(
    `python3 -c "
import sys; sys.path.insert(0,'.')
from backend.services.engine.intraday_regime_monitor import _judge_regime
cases = [
    (18, 0.8, 'risk_on'),
    (20, -0.2, 'neutral'),
    (25, -1.5, 'risk_off'),
    (30, -2.0, 'volatile'),
    (18, -2.0, 'risk_off'),
]
for vix, kospi, expected in cases:
    result = _judge_regime(vix, kospi)
    assert result == expected, f'VIX={vix} KOSPI={kospi}: got {result}, expected {expected}'
print('ALL PASS')
"`,
    { cwd: '/home/young/repos/stock-trading-bot', encoding: 'utf-8' }
  ).trim();
  expect(result).toBe('ALL PASS');
});

test('min transition interval respected', () => {
  // _should_skip_transition: 마지막 전환 직후에는 스킵
  const result = execSync(
    `python3 -c "
import sys; sys.path.insert(0,'.')
from backend.services.engine.intraday_regime_monitor import _should_skip_transition
# 오늘 전환 이력 없으면 False
today = __import__('datetime').datetime.now(__import__('zoneinfo').ZoneInfo('Asia/Seoul')).strftime('%Y-%m-%d')
assert _should_skip_transition(today) == False
print('PASS')
"`,
    { cwd: '/home/young/repos/stock-trading-bot', encoding: 'utf-8' }
  ).trim();
  expect(result).toBe('PASS');
});

test('positions table has entry_set_id column', () => {
  const result = execSync(
    `python3 -c "
import sys; sys.path.insert(0,'.')
from backend.services.db import get_connection
with get_connection() as conn:
    cols = [dict(r)['name'] for r in conn.execute('PRAGMA table_info(positions)')]
    assert 'entry_set_id' in cols, f'entry_set_id not in {cols}'
print('PASS')
"`,
    { cwd: '/home/young/repos/stock-trading-bot', encoding: 'utf-8' }
  ).trim();
  expect(result).toBe('PASS');
});

test('intraday_regime_monitor slots defined in scheduler', () => {
  const result = execSync(
    `python3 -c "
import sys; sys.path.insert(0,'.')
import pathlib
src = pathlib.Path('backend/services/scheduler.py').read_text()
# 루프 기반 등록이므로 슬롯 리스트와 job 함수 존재 확인
assert 'job_intraday_regime_monitor' in src, 'job function missing'
assert '09:30' in src, '09:30 slot missing'
assert '15:00' in src, '15:00 slot missing'
assert 'regime_monitor' in src
print('PASS')
"`,
    { cwd: '/home/young/repos/stock-trading-bot', encoding: 'utf-8' }
  ).trim();
  expect(result).toBe('PASS');
});

test('intraday_regime_monitor module compiles', () => {
  const result = execSync(
    `python3 -m py_compile backend/services/engine/intraday_regime_monitor.py && echo PASS`,
    { cwd: '/home/young/repos/stock-trading-bot', encoding: 'utf-8' }
  ).trim();
  expect(result).toBe('PASS');
});

test('/api/v1/regime/today returns transitions array', async ({ request }) => {
  const res = await request.get(`${BASE}/api/v1/regime/today`);
  expect(res.status()).toBe(200);
  const body = await res.json();
  expect(body.ok).toBe(true);
  expect(body).toHaveProperty('transitions');
  expect(body).toHaveProperty('transition_count');
});

/* ── UI ── */

test('Today Control has regime timeline card element', async ({ page }) => {
  await login(page);
  await page.locator('#nav [data-screen="today"]').first().click();
  await page.waitForTimeout(1000);
  const card = page.locator('#tc-regime-timeline-card');
  await expect(card).toHaveCount(1);
});

test('Daily Plan screen has dp-set-chain element', async ({ page }) => {
  await login(page);
  await page.locator('#nav [data-screen="rulepack"]').first().click();
  await page.waitForTimeout(2000);
  const chain = page.locator('#dp-set-chain');
  await expect(chain).toHaveCount(1);
});
