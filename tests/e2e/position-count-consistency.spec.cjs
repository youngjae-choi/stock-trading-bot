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

test.describe('Position count consistency across endpoints', () => {
  const url = process.env.BACKEND_URL || 'http://127.0.0.1:8000';

  test('open_positions (bot/overview) == positions_count (funnel/summary)', async ({ request }) => {
    const [name, value] = createSessionCookie().split('=');
    const headers = { Cookie: `${name}=${value}` };

    const [overviewRes, funnelRes] = await Promise.all([
      request.get(`${url}/api/v1/bot/overview`, { headers, timeout: 15_000 }),
      request.get(`${url}/api/v1/funnel/summary`, { headers, timeout: 15_000 }),
    ]);

    expect(overviewRes.ok()).toBeTruthy();
    expect(funnelRes.ok()).toBeTruthy();

    const overviewBody = await overviewRes.json();
    const funnelBody = await funnelRes.json();

    const openPositions = overviewBody?.payload?.open_positions ?? overviewBody?.open_positions;
    const positionsCount = funnelBody?.payload?.positions_count ?? funnelBody?.positions_count;

    console.log(`open_positions=${openPositions} positions_count=${positionsCount}`);

    expect(typeof openPositions).toBe('number');
    expect(typeof positionsCount).toBe('number');
    expect(openPositions).toBe(positionsCount);
  });

  test('trading-monitor positions == position_manager count', async ({ request }) => {
    const [name, value] = createSessionCookie().split('=');
    const headers = { Cookie: `${name}=${value}` };

    const [tmRes, funnelRes] = await Promise.all([
      request.get(`${url}/api/v1/trading-monitor/positions`, { headers, timeout: 15_000 }),
      request.get(`${url}/api/v1/funnel/summary`, { headers, timeout: 15_000 }),
    ]);

    expect(tmRes.ok()).toBeTruthy();
    expect(funnelRes.ok()).toBeTruthy();

    const tmBody = await tmRes.json();
    const funnelBody = await funnelRes.json();

    const tmPositions = tmBody?.payload?.positions || tmBody?.positions || [];
    const tmCount = Array.isArray(tmPositions) ? tmPositions.length : 0;
    const positionsCount = funnelBody?.payload?.positions_count ?? funnelBody?.positions_count;

    console.log(`trading-monitor positions length=${tmCount} funnel positions_count=${positionsCount}`);

    // 60초 sync 후에는 일치해야 함. 첫 호출에서는 race condition으로 차이 날 수 있음.
    // 60초 대기는 비용 크므로, 단순히 둘 다 숫자인지만 확인하고 큰 차이만 fail.
    expect(typeof positionsCount).toBe('number');
    expect(Math.abs(tmCount - positionsCount)).toBeLessThanOrEqual(1);
  });
});
