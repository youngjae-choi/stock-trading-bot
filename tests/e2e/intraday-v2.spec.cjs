/**
 * E2E tests — Intraday Reselection v2 integration.
 * - API response envelopes for empty future-date data.
 * - system_settings seed values.
 * - SQLite schema for v2 audit tables.
 * - Scheduler slot registration.
 * - Funnel Monitor v2 cards and kill switch behavior.
 */
const { test, expect } = require('@playwright/test');
const { execSync } = require('child_process');

const BASE = 'http://127.0.0.1:8000';
const ROOT = '/home/young/repos/stock-trading-bot';
const SCREENSHOT_MAIN = 'tests/e2e/img/funnel_intraday_v2_main.png';
const SCREENSHOT_KILL_SWITCH = 'tests/e2e/img/funnel_intraday_v2_killswitch.png';

let sessionCookie;

/**
 * Run a shell command and return stdout.
 *
 * @param {string} command Shell command to execute.
 * @returns {string} Trimmed stdout.
 */
function runShell(command) {
  try {
    return execSync(command, { cwd: ROOT, encoding: 'utf-8' }).trim();
  } catch (error) {
    if (error && error.status === 0 && error.stdout) {
      return String(error.stdout).trim();
    }
    throw error;
  }
}

/**
 * Create a console-authenticated test session for the admin user.
 *
 * @returns {{name: string, value: string}} Cookie name and value.
 */
function createTestSession() {
  const result = runShell(
    `python3 -c "
import sys; sys.path.insert(0,'.')
from backend.services.auth_service import SESSION_COOKIE_NAME, create_session
from backend.services.db import get_connection
with get_connection() as conn:
    row = conn.execute('SELECT id FROM users WHERE username=?', ('admin',)).fetchone()
    user_id = dict(row)['id']
session_id = create_session(user_id)
print(SESSION_COOKIE_NAME + '=' + session_id)
"`
  ).trim();
  const [name, value] = result.split('=');
  return { name, value };
}

/**
 * Return the shared session cookie, creating it once per spec process.
 *
 * @returns {{name: string, value: string}} Cookie name and value.
 */
function getSessionCookie() {
  if (!sessionCookie) {
    sessionCookie = createTestSession();
  }
  return sessionCookie;
}

/**
 * Return the Cookie header required by authenticated API endpoints.
 *
 * @returns {string} HTTP Cookie header value.
 */
function cookieHeader() {
  const cookie = getSessionCookie();
  return `${cookie.name}=${cookie.value}`;
}

/**
 * Open the console with an authenticated browser context.
 *
 * @param {import('@playwright/test').Page} page Browser page fixture.
 */
async function login(page) {
  const cookie = getSessionCookie();
  await page.context().addCookies([{
    name: cookie.name,
    value: cookie.value,
    domain: '127.0.0.1',
    path: '/',
  }]);
  await page.goto(`${BASE}/static/console.html`, { waitUntil: 'domcontentloaded', timeout: 20000 });
  await expect(page.locator('#nav')).toBeVisible({ timeout: 15000 });
}

/**
 * Fetch all settings as a key-indexed object.
 *
 * @param {import('@playwright/test').APIRequestContext} request Playwright request fixture.
 * @returns {Promise<Record<string, any>>} Settings map keyed by setting key.
 */
async function getSettingsMap(request) {
  const res = await request.get(`${BASE}/api/v1/settings`, {
    headers: { Cookie: cookieHeader() },
  });
  expect(res.status()).toBe(200);
  const body = await res.json();
  expect(body.ok).toBe(true);
  expect(Array.isArray(body.payload.items)).toBe(true);

  const map = {};
  for (const item of body.payload.items) {
    map[item.key] = item;
  }
  return map;
}

/**
 * Persist one setting through the same API used by the console UI.
 *
 * @param {import('@playwright/test').APIRequestContext} request Playwright request fixture.
 * @param {string} key Setting key.
 * @param {any} value Setting value.
 * @param {string} valueType Persisted setting type.
 */
async function setSetting(request, key, value, valueType = 'bool') {
  const res = await request.post(`${BASE}/api/v1/settings`, {
    headers: {
      Cookie: cookieHeader(),
      'Content-Type': 'application/json',
    },
    data: {
      key,
      value,
      value_type: valueType,
      description: 'E2E intraday v2 cleanup',
    },
  });
  expect(res.status()).toBe(200);
  const body = await res.json();
  expect(body.ok).toBe(true);
}

test.afterAll(async ({ playwright }) => {
  const api = await playwright.request.newContext();
  try {
    await setSetting(api, 'intraday_refresh.master_enabled', true, 'bool');
  } catch (error) {
    console.warn(`WARN: intraday v2 cleanup could not confirm master_enabled restore: ${error.message}`);
  } finally {
    await api.dispose();
  }
});

test.describe('intraday reselection v2', () => {
  test('Scenario 1: API response structure supports empty future-date data', async ({ request }) => {
    const reselection = await request.get(`${BASE}/api/v1/trading-monitor/reselection-stats?trade_date=2099-01-01`);
    expect(reselection.status()).toBe(200);
    const reselectionBody = await reselection.json();
    expect(reselectionBody.ok).toBe(true);
    expect(reselectionBody.payload).toBeTruthy();
    expect(Array.isArray(reselectionBody.payload.slots)).toBe(true);

    const replacement = await request.get(`${BASE}/api/v1/trading-monitor/replacement-signals?trade_date=2099-01-01`);
    expect(replacement.status()).toBe(200);
    const replacementBody = await replacement.json();
    expect(replacementBody.ok).toBe(true);
    expect(replacementBody.payload).toBeTruthy();
    expect(Array.isArray(replacementBody.payload.signals)).toBe(true);
  });

  test('Scenario 2: system_settings contains all intraday v2 defaults', async ({ request }) => {
    const settings = await getSettingsMap(request);
    const expected = {
      'intraday_refresh.master_enabled': true,
      'intraday_refresh.lunch_slots_enabled': true,
      'intraday_refresh.sector_rotation_enabled': true,
      'intraday_refresh.sector_rotation_threshold': 3.0,
      'intraday_refresh.replacement_signal_enabled': true,
      'intraday_refresh.replacement_score_gap': 0.15,
      'intraday_refresh.max_replacement_per_symbol': 1,
      'intraday_refresh.max_replacement_per_day': 5,
    };

    for (const [key, value] of Object.entries(expected)) {
      expect(settings[key], `${key} should exist`).toBeTruthy();
      expect(settings[key].value).toBe(value);
    }
  });

  test('Scenario 3: DB tables for replacement signals and sector rotation exist', () => {
    const result = runShell(
      `python3 -c "
import sys; sys.path.insert(0,'.')
from backend.services.db import initialize_database, get_connection
initialize_database()
required = {
    'replacement_signals': [
        'id', 'trade_date', 'slot', 'current_symbol', 'current_score',
        'current_pnl_pct', 'new_symbol', 'new_score', 'score_gap', 'reason', 'created_at'
    ],
    'sector_rotation_log': [
        'id', 'trade_date', 'slot', 'top_sectors', 'bottom_sectors', 'gap_pct', 'triggered'
    ],
}
with get_connection() as conn:
    for table, columns in required.items():
        actual = [dict(row)['name'] for row in conn.execute(f'PRAGMA table_info({table})')]
        missing = [column for column in columns if column not in actual]
        assert not missing, f'{table} missing columns: {missing}; actual={actual}'
        if table == 'replacement_signals':
            assert len(actual) >= 11, f'{table} expected at least 11 columns, got {len(actual)}'
print('PASS')
"`
    ).trim();

    expect(result).toBe('PASS');
  });

  test('Scenario 4: Scheduler has all five intraday refresh slots registered', async ({ request }) => {
    const res = await request.get(`${BASE}/api/v1/scheduler/status`, {
      headers: { Cookie: cookieHeader() },
    });
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.ok).toBe(true);
    expect(Array.isArray(body.payload.jobs)).toBe(true);

    const jobIds = body.payload.jobs.map(job => job.id);
    for (const id of [
      'job_intraday_refresh_0930',
      'job_intraday_refresh_1030',
      'job_intraday_refresh_1130',
      'job_intraday_refresh_1300',
      'job_intraday_refresh_1400',
    ]) {
      expect(jobIds).toContain(id);
    }
  });

  test('Scenario 5: Funnel Monitor renders intraday v2 card anchors', async ({ page }) => {
    await login(page);
    await page.locator('#nav [data-screen="funnel"]').first().click();
    await expect(page.locator('#screen-funnel')).toBeVisible({ timeout: 10000 });
    await expect(page.locator('#tc-kill-switch-list input.kill-switch-toggle').first()).toBeVisible({ timeout: 10000 });

    await expect(page.locator('#tc-intraday-reselection-card')).toHaveCount(1);
    await expect(page.locator('#tc-replacement-signal-card')).toHaveCount(1);
    await expect(page.locator('#tc-kill-switch-card')).toHaveCount(1);

    const killSwitchDisplay = await page.locator('#tc-kill-switch-card').evaluate(el => getComputedStyle(el).display);
    expect(killSwitchDisplay).not.toBe('none');
    await page.screenshot({ path: SCREENSHOT_MAIN, fullPage: true });
  });

  test('Scenario 6: Kill Switch master toggle disables and re-enables sub toggles', async ({ page, request }) => {
    await setSetting(request, 'intraday_refresh.master_enabled', true, 'bool');
    await login(page);
    await page.locator('#nav [data-screen="funnel"]').first().click();
    await expect(page.locator('#screen-funnel')).toBeVisible({ timeout: 10000 });

    const master = page.locator('input.kill-switch-toggle[data-kskey="intraday_refresh.master_enabled"]');
    const subToggles = page.locator('input.kill-switch-toggle:not([data-kskey="intraday_refresh.master_enabled"])');
    await expect(master).toBeVisible({ timeout: 10000 });
    await expect(master).toBeChecked();

    await master.click();
    await expect(master).not.toBeChecked({ timeout: 10000 });

    let settings = await getSettingsMap(request);
    expect(settings['intraday_refresh.master_enabled'].value).toBe(false);
    await expect(subToggles.first()).toBeDisabled({ timeout: 10000 });
    const disabledCount = await subToggles.evaluateAll(inputs => inputs.filter(input => input.disabled).length);
    const totalSubToggles = await subToggles.count();
    expect(disabledCount).toBe(totalSubToggles);

    await master.click();
    await expect(master).toBeChecked({ timeout: 10000 });

    settings = await getSettingsMap(request);
    expect(settings['intraday_refresh.master_enabled'].value).toBe(true);
    await expect(subToggles.first()).toBeEnabled({ timeout: 10000 });
    const enabledCount = await subToggles.evaluateAll(inputs => inputs.filter(input => !input.disabled).length);
    expect(enabledCount).toBe(totalSubToggles);

    await page.screenshot({ path: SCREENSHOT_KILL_SWITCH, fullPage: true });
  });
});
