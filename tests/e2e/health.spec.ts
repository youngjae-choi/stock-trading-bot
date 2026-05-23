import { expect, test } from '@playwright/test';
import { execFileSync } from 'child_process';
import fs from 'fs';

const backendUrl = process.env.BACKEND_URL ?? 'http://127.0.0.1:8000';

function envValue(key: string, fallback = ''): string {
  if (process.env[key]) return process.env[key] as string;
  try {
    const text = fs.readFileSync('.env', 'utf8');
    const line = text.split(/\r?\n/).find((item) => item.startsWith(`${key}=`));
    return line ? line.slice(key.length + 1).trim() : fallback;
  } catch (_error) {
    return fallback;
  }
}

function createAuthHeaders(): { Cookie: string } {
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
  const cookie = execFileSync('python', ['-c', script], {
    cwd: process.cwd(),
    env: {
      ...process.env,
      E2E_USERNAME: envValue('APP_ADMIN_USERNAME', 'admin'),
      E2E_PASSWORD: envValue('APP_ADMIN_PASSWORD'),
    },
    encoding: 'utf8',
  }).trim();
  return { Cookie: cookie };
}

function runPythonCheck(script: string): string {
  return execFileSync('python', ['-c', script], {
    cwd: process.cwd(),
    env: process.env,
    encoding: 'utf8',
  }).trim();
}

test('backend health endpoint responds', async ({ request }) => {
  const response = await request.get(`${backendUrl}/health`);

  expect(response.ok()).toBeTruthy();
  const payload = await response.json();
  expect(payload.status).toBe('healthy');
  expect(payload.database.ok).toBeTruthy();
  expect(payload.kis_rate_limit.profile).toEqual(expect.any(String));
  expect(payload.kis_rate_limit.requests_per_second).toEqual(expect.any(Number));
  expect(payload.kis_rate_limit.applied_requests_per_second).toEqual(expect.any(Number));
  expect(payload.kis_rate_limit.limiter_matches_policy).toEqual(expect.any(Boolean));
  expect(payload.kis_rate_limit.limiter.configured_requests_per_second).toEqual(expect.any(Number));
  expect(payload.kis_rate_limit.limiter.delay_seconds).toEqual(expect.any(Number));
  expect(payload.kis_rate_limit.limiter.last_rate_limited_at).toEqual(expect.any(Number));
  expect(
    payload.kis_rate_limit.policy_limit_per_second === null
      || typeof payload.kis_rate_limit.policy_limit_per_second === 'number',
  ).toBeTruthy();
});

test('backend console routes respond with html', async ({ request }) => {
  const rootResponse = await request.get(`${backendUrl}/`);
  const consoleResponse = await request.get(`${backendUrl}/console`);

  expect(rootResponse.ok()).toBeTruthy();
  expect(consoleResponse.ok()).toBeTruthy();
  expect(await rootResponse.text()).toContain('Kairos Control Console');
  expect(await consoleResponse.text()).toContain('Kairos Control Console');
});

test('closed trading day S2 skips market tone analysis', async () => {
  const output = runPythonCheck(`
import asyncio
from backend.services import scheduler

calls = []

async def fake_refresh(actor=''):
    calls.append(('refresh', actor))
    scheduler._set_schedule_skip_today(skip=True, description='e2e closed day', actor='e2e_closed_day')
    return {'status': 'closed', 'reason': 'e2e', 'date': scheduler._today_kst_compact()}

original_refresh = scheduler.refresh_trading_day_skip_flag
scheduler.refresh_trading_day_skip_flag = fake_refresh
try:
    asyncio.run(scheduler.job_market_tone_analysis())
finally:
    scheduler.refresh_trading_day_skip_flag = original_refresh
    scheduler._set_schedule_skip_today(skip=False, description='e2e cleanup', actor='e2e_cleanup')

assert calls == [('refresh', 'scheduler_s2')], calls
print('S2_CLOSED_DAY_SKIP_OK')
`);
  expect(output).toContain('S2_CLOSED_DAY_SKIP_OK');
});

test('skipped day data basis stays on previous pipeline date', async () => {
  const output = runPythonCheck(`
from backend.services import console_state, scheduler

original_has = console_state._has_pipeline_data_for_date
original_latest = console_state._latest_pipeline_data_date
scheduler._set_schedule_skip_today(skip=True, description='e2e data basis', actor='e2e_data_basis')
console_state._has_pipeline_data_for_date = lambda trade_date: True
console_state._latest_pipeline_data_date = lambda today, include_today=True: '2026-05-08' if include_today is False else today
try:
    basis = console_state._build_data_basis('2026-05-09')
finally:
    console_state._has_pipeline_data_for_date = original_has
    console_state._latest_pipeline_data_date = original_latest
    scheduler._set_schedule_skip_today(skip=False, description='e2e cleanup', actor='e2e_cleanup')

assert basis['display_date'] == '2026-05-08', basis
assert basis['is_today'] is False, basis
print('DATA_BASIS_PRIOR_DAY_OK')
`);
  expect(output).toContain('DATA_BASIS_PRIOR_DAY_OK');
});

test('bot console api endpoints respond with current payloads', async ({ request }) => {
  const headers = createAuthHeaders();
  const overviewResponse = await request.get(`${backendUrl}/api/v1/bot/overview`, { headers });
  const rulepackResponse = await request.get(`${backendUrl}/api/v1/bot/rulepack/today`, { headers });
  const dataHealthResponse = await request.get(`${backendUrl}/api/v1/bot/data-health`, { headers });
  const haltResponse = await request.post(`${backendUrl}/api/v1/bot/control/halt`, { headers });
  const apiLogsResponse = await request.get(`${backendUrl}/api/v1/bot/api-logs`, { headers });

  expect(overviewResponse.ok()).toBeTruthy();
  expect(rulepackResponse.ok()).toBeTruthy();
  expect(dataHealthResponse.ok()).toBeTruthy();
  expect(haltResponse.ok()).toBeTruthy();
  expect(apiLogsResponse.ok()).toBeTruthy();

  const overview = await overviewResponse.json();
  const rulepack = await rulepackResponse.json();
  const dataHealth = await dataHealthResponse.json();
  const halt = await haltResponse.json();
  const apiLogs = await apiLogsResponse.json();

  expect(overview.ok).toBeTruthy();
  expect(overview.source).toBe('backend');
  expect(overview.live).toBeTruthy();
  expect(overview.payload.trade_date).toEqual(expect.any(String));
  expect(overview.payload.data_basis.display_date).toEqual(expect.any(String));
  expect(overview.payload.health).toEqual(expect.any(Object));
  expect(rulepack.payload.status ?? rulepack.payload.rulepack?.status).toEqual(expect.any(String));
  expect(dataHealth.payload.note).toEqual(expect.any(String));
  expect(halt.payload.halted).toBeTruthy();
  expect(apiLogs.source).toBe('backend');
  expect(apiLogs.live).toBeFalsy();
  expect(Array.isArray(apiLogs.payload.items)).toBeTruthy();
  expect(apiLogs.payload.items.length).toBeGreaterThan(0);
  expect(apiLogs.payload.items[0]).toMatchObject({
    endpoint: expect.any(String),
    method: expect.any(String),
    status: expect.any(String),
    source: expect.any(String),
    timestamp: expect.any(String),
    called_at: expect.any(String),
    message: expect.any(String),
    feature_name: expect.any(String),
    purpose: expect.any(String),
    api_name_or_path: expect.any(String),
    result_summary: expect.any(String),
  });
  expect(
    apiLogs.payload.items.some(
      (entry: { endpoint: string; feature_name?: string; purpose?: string; result_summary?: string }) =>
        entry.endpoint === '/api/v1/bot/overview'
        && entry.feature_name === '운영 개요 조회'
        && entry.purpose === '운영 화면에서 엔진 상태와 리스크 상태를 한 번에 확인'
        && entry.result_summary === '성공 실 DB 기반 운영 개요 반환',
    ),
  ).toBeTruthy();
  expect(
    apiLogs.payload.items.some(
      (entry: { endpoint: string; feature_name?: string; api_name_or_path?: string }) =>
        entry.endpoint === '/api/v1/bot/control/halt'
        && entry.feature_name === '긴급정지 실행'
        && entry.api_name_or_path === 'POST /api/v1/bot/control/halt',
    ),
  ).toBeTruthy();
});

test('settings and trading data persist through authenticated APIs', async ({ request }) => {
  const headers = createAuthHeaders();
  const settingsResponse = await request.get(`${backendUrl}/api/v1/settings`, { headers });
  expect(settingsResponse.ok()).toBeTruthy();
  const settingsPayload = await settingsResponse.json();
  expect(Array.isArray(settingsPayload.payload.items)).toBeTruthy();

  const updateResponse = await request.put(`${backendUrl}/api/v1/settings/risk.max_positions`, {
    headers,
    data: { value: 5, value_type: 'number', description: '최대 보유 종목' },
  });
  expect(updateResponse.ok()).toBeTruthy();

  const orderResponse = await request.post(`${backendUrl}/api/v1/trading-data/orders`, {
    headers,
    data: { symbol: '005930', side: 'buy', quantity: 1, order_type: 'market', status: 'created' },
  });
  expect(orderResponse.ok()).toBeTruthy();

  const ordersResponse = await request.get(`${backendUrl}/api/v1/trading-data/orders`, { headers });
  expect(ordersResponse.ok()).toBeTruthy();
  const ordersPayload = await ordersResponse.json();
  expect(ordersPayload.payload.items.some((entry: { symbol: string }) => entry.symbol === '005930')).toBeTruthy();
});
