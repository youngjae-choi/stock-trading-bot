import { expect, test } from '@playwright/test';
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

async function login(request) {
  const response = await request.post(`${backendUrl}/api/v1/auth/login`, {
    data: {
      username: envValue('APP_ADMIN_USERNAME', 'admin'),
      password: envValue('APP_ADMIN_PASSWORD'),
    },
  });
  expect(response.ok()).toBeTruthy();
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
  expect(await rootResponse.text()).toContain('Dantabot Control Console');
  expect(await consoleResponse.text()).toContain('Dantabot Control Console');
});

test('bot console api endpoints respond with current payloads', async ({ request }) => {
  await login(request);
  const overviewResponse = await request.get(`${backendUrl}/api/v1/bot/overview`);
  const rulepackResponse = await request.get(`${backendUrl}/api/v1/bot/rulepack/today`);
  const dataHealthResponse = await request.get(`${backendUrl}/api/v1/bot/data-health`);
  const haltResponse = await request.post(`${backendUrl}/api/v1/bot/control/halt`);
  const apiLogsResponse = await request.get(`${backendUrl}/api/v1/bot/api-logs`);

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
  expect(overview.payload.health).toEqual(expect.any(Object));
  expect(rulepack.payload.status).toBe('mock');
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
        && entry.result_summary === '성공 mock 운영 개요와 오늘 상태 요약을 반환',
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
  await login(request);
  const settingsResponse = await request.get(`${backendUrl}/api/v1/settings`);
  expect(settingsResponse.ok()).toBeTruthy();
  const settingsPayload = await settingsResponse.json();
  expect(Array.isArray(settingsPayload.payload.items)).toBeTruthy();

  const updateResponse = await request.put(`${backendUrl}/api/v1/settings/risk.max_positions`, {
    data: { value: 5, value_type: 'number', description: '최대 보유 종목' },
  });
  expect(updateResponse.ok()).toBeTruthy();

  const orderResponse = await request.post(`${backendUrl}/api/v1/trading-data/orders`, {
    data: { symbol: '005930', side: 'buy', quantity: 1, order_type: 'market', status: 'created' },
  });
  expect(orderResponse.ok()).toBeTruthy();

  const ordersResponse = await request.get(`${backendUrl}/api/v1/trading-data/orders`);
  expect(ordersResponse.ok()).toBeTruthy();
  const ordersPayload = await ordersResponse.json();
  expect(ordersPayload.payload.items.some((entry: { symbol: string }) => entry.symbol === '005930')).toBeTruthy();
});
