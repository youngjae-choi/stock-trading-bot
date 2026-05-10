const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

const staticRoot = path.resolve(__dirname, '../../backend/static');

function contentTypeFor(filePath) {
  if (filePath.endsWith('.html')) return 'text/html; charset=utf-8';
  if (filePath.endsWith('.css')) return 'text/css; charset=utf-8';
  if (filePath.endsWith('.js')) return 'application/javascript; charset=utf-8';
  return 'application/octet-stream';
}

function resolveStaticPath(requestPath) {
  const relativePath = requestPath === '/console'
    ? 'console.html'
    : requestPath.replace(/^\/static\//, '');
  const resolved = path.resolve(staticRoot, relativePath);
  if (!resolved.startsWith(staticRoot + path.sep) && resolved !== staticRoot) {
    return null;
  }
  return resolved;
}

test.beforeEach(async ({ page }) => {
  page._statusTruthBrowserErrors = [];
  page.on('console', (message) => {
    if (message.type() === 'error') {
      page._statusTruthBrowserErrors.push(message.text());
    }
  });
  page.on('pageerror', (error) => {
    page._statusTruthBrowserErrors.push(error.message);
  });
  page.on('response', (response) => {
    if (response.url().includes('/static/') && !response.ok()) {
      page._statusTruthBrowserErrors.push(`Failed to load resource ${response.url()} status=${response.status()}`);
    }
  });

  await page.route('http://console.local/**', async (route) => {
    const request = route.request();
    const requestUrl = new URL(request.url());
    if (request.method() !== 'GET') {
      await route.fulfill({ status: 405, contentType: 'text/plain; charset=utf-8', body: 'Method Not Allowed' });
      return;
    }
    if (requestUrl.pathname !== '/console' && !requestUrl.pathname.startsWith('/static/')) {
      await route.fulfill({ status: 404, contentType: 'text/plain; charset=utf-8', body: 'Not Found' });
      return;
    }

    const filePath = resolveStaticPath(decodeURIComponent(requestUrl.pathname));
    if (!filePath || !fs.existsSync(filePath)) {
      await route.fulfill({ status: 404, contentType: 'text/plain; charset=utf-8', body: 'Not Found' });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: contentTypeFor(filePath),
      body: fs.readFileSync(filePath),
    });
  });

  await page.addInitScript(() => {
    window.__statusTruthScenario = 'nulls';

    function kstToday() {
      const parts = new Intl.DateTimeFormat('en-CA', {
        timeZone: 'Asia/Seoul',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
      }).formatToParts(new Date());
      const byType = {};
      parts.forEach((part) => { byType[part.type] = part.value; });
      return `${byType.year}-${byType.month}-${byType.day}`;
    }

    function envelope(payload, result, status) {
      return {
        ok: true,
        source: 'mock',
        live: false,
        status,
        has_result: result != null,
        result,
        trade_date: kstToday(),
        payload,
      };
    }

    window.fetch = async (input) => {
      const url = new URL(String(input), 'http://mock.local');
      const pathName = url.pathname;
      const today = kstToday();
      const scenario = window.__statusTruthScenario;
      const skip = scenario === 'skip';

      const responses = {
        '/api/v1/auth/me': { ok: false, error: 'mock unauthenticated' },
        '/api/v1/settings': { ok: true, payload: { items: [] } },
        '/api/v1/scheduler/status': {
          ok: true,
          payload: {
            last_run: 'mock-s1',
            schedule_skip_today: {
              skip,
              reason: skip ? 'schedule_skip_today=true' : 'schedule_skip_today=false',
              trade_date: today,
            },
          },
        },
        '/api/v1/engine/audit/today': { ok: true, payload: { trade_date: today, runs: [], by_step: {} } },
        '/api/v1/engine/logs': {
          ok: true,
          payload: {
            log_path: '/tmp/mock-server.log',
            exists: true,
            total: 1,
            lines: ['mock backend log line'],
            message: '서버 로그 1줄을 불러왔습니다.',
          },
        },
        '/api/v1/funnel/summary': { ok: true, payload: {} },
        '/api/v1/decision/status': { ok: true, payload: { active: false } },
        '/api/v1/orders/today': { ok: true, payload: { orders: [] } },
        '/api/v1/orders/positions': { ok: true, payload: { positions: [] } },
        '/api/v1/account/balance': { ok: true, payload: { positions: [], stock_eval: 0, pnl_total: 0, pnl_rate: 0 } },
        '/api/v1/trading-monitor/policy-summary': { ok: true, payload: { daily_plan: {} } },
        '/api/v1/trading-monitor/candidates': { ok: true, payload: { candidates: [] } },
        '/api/v1/trading-monitor/positions': { ok: true, payload: { positions: [] } },
        '/api/v1/review-audit/today': { ok: true, payload: null },
        '/api/v1/learning-memory/today': { ok: true, payload: [] },
      };

      const s2Result = scenario === 's2-success'
        ? { id: 'mt-1', trade_date: today, tone: 'neutral', provider: 'mock' }
        : null;
      responses['/api/v1/market-tone/today'] = envelope(
        { market_tone: s2Result, trade_date: today },
        s2Result,
        skip && !s2Result ? 'skipped' : s2Result ? 'success' : 'pending',
      );
      responses['/api/v1/universe-filter/today'] = envelope(
        { universe: null, trade_date: today },
        null,
        skip ? 'skipped' : 'pending',
      );
      responses['/api/v1/screening/today'] = envelope(
        { screening: null, trade_date: today },
        null,
        skip ? 'skipped' : 'pending',
      );
      responses['/api/v1/daily-plan/today'] = envelope(null, null, skip ? 'skipped' : 'pending');

      if (scenario === 'funnel-empty') {
        responses['/api/v1/funnel/summary'] = {
          ok: true,
          payload: {
            trade_date: today,
            total_universe: 2500,
            total_universe_source: 'KRX 기준 universe 값(DB 집계 아님)',
            layer1_raw: 30,
            layer1_count: 0,
            layer1_rejected: 30,
            layer1_rejection_breakdown: [],
            layer2_count: 0,
            signals_count: 0,
            positions_count: 0,
            profile_counts: {},
            has_s3: true,
            has_s4: false,
            has_s5: false,
            empty_reason: 'S3는 실행됐으나 통과 종목 0개라 S4/S5 미생성',
            last_updated_at: `${today}T08:15:32+09:00`,
          },
        };
      }

      if (scenario === 'funnel-candidates') {
        responses['/api/v1/funnel/summary'] = {
          ok: true,
          payload: {
            trade_date: today,
            total_universe: 2500,
            total_universe_source: 'KRX 기준 universe 값(DB 집계 아님)',
            layer1_raw: 30,
            layer1_count: 2,
            layer1_rejected: 28,
            layer1_rejection_breakdown: [],
            layer2_count: 2,
            signals_count: 0,
            positions_count: 0,
            profile_counts: { MID_VOL: 2 },
            has_s3: true,
            has_s4: true,
            has_s5: true,
            empty_reason: '',
            last_updated_at: `${today}T08:40:00+09:00`,
          },
        };
        responses['/api/v1/screening/today'] = envelope(
          {
            screening: {
              output_count: 2,
              candidates: [
                { ticker: 'AAA001', name: 'Ticker Corp', suitability_score: 0.91, confidence: 0.82, reason: 'ticker key', memory_refs: [] },
                { code: 'BBB002', name: 'Code Corp', suitability_score: 0.73, confidence: 0.66, reason: 'code key', memory_refs: ['m1'] },
              ],
            },
            trade_date: today,
          },
          { id: 'screening-1' },
          'success',
        );
        responses['/api/v1/daily-plan/today'] = {
          ok: true,
          payload: {
            symbol_assignments: [
              { ticker: 'AAA001', profile: 'LOW_VOL', reason: 'ticker matched' },
              { code: 'BBB002', profile: 'HIGH_VOL', reason: 'code matched' },
            ],
          },
        };
      }

      if (scenario === 'logs-empty') {
        responses['/api/v1/engine/logs'] = {
          ok: true,
          payload: {
            log_path: '/tmp/mock-empty-server.log',
            exists: true,
            total: 0,
            lines: [],
            message: '서버 로그 파일은 비어 있습니다: /tmp/mock-empty-server.log',
          },
        };
      }

      if (scenario === 'tm-monitoring') {
        responses['/api/v1/account/balance'] = {
          ok: true,
          payload: {
            account_no: 'mock',
            buyable_cash: 1000000,
            deposit: 1000000,
            stock_eval: 70000,
            total_eval: 1070000,
            pnl_total: -16000,
            pnl_rate: -16,
            today_buy_amt: 0,
            today_sell_amt: 0,
            positions: [{ symbol: '005930', name: '삼성전자', qty: 1, avg_price: 100000, current_price: 84000 }],
          },
        };
        responses['/api/v1/trading-monitor/positions'] = {
          ok: true,
          payload: {
            positions: [{
              symbol: '005930',
              name: '삼성전자',
              qty: 1,
              entry_price: 100000,
              market_price: 84000,
              highest_price_since_entry: 100000,
              active_stop_price: 97000,
              monitoring_status: '미감시',
              monitoring_detail: 'KIS 실보유에는 있으나 자동 손절/트레일링 감시 대상이 아님',
              auto_monitoring: false,
              ws_subscribed: false,
              position_manager_registered: false,
              stop_state_source: 'fallback',
              profile_assigned: 'MID_VOL',
            }],
          },
        };
      }

      if (scenario === 'audit-visible') {
        responses['/api/v1/engine/audit/today'] = {
          ok: true,
          payload: {
            trade_date: today,
            runs: [],
            by_step: {
              s3: {
                step: 'S3',
                step_id: 's3',
                trigger_source: 'auto_scheduler',
                display_source: 'auto_scheduler',
                status: 'success',
                message: 'raw=30 filtered=0',
                result_ref_id: 'uf-1',
                started_at_kst: `${today} 08:15:00 KST`,
                finished_at_kst: `${today} 08:15:32 KST`,
              },
            },
          },
        };
      }

      const body = responses[pathName] || { ok: true, payload: {} };
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    };
  });
  await page.goto('http://console.local/console', { waitUntil: 'domcontentloaded' });
});

test('Console shell loads extracted assets without browser runtime errors', async ({ page }) => {
  const expectedScripts = [
    '/static/js/console-state.js',
    '/static/js/console-utils.js',
    '/static/js/console-api.js',
    '/static/js/console-auth.js',
    '/static/js/screens/console-today-orders.js',
    '/static/js/screens/console-positions.js',
    '/static/js/screens/console-trading-monitor.js',
    '/static/js/screens/console-live-decision.js',
    '/static/js/screens/console-diagnostics.js',
    '/static/js/screens/console-execution-risk.js',
    '/static/js/screens/console-alerts.js',
    '/static/js/screens/console-approval.js',
    '/static/js/screens/console-missed-tracking.js',
    '/static/js/screens/console-false-positive.js',
    '/static/js/screens/console-confidence-calibration.js',
    '/static/js/screens/console-settings.js',
    '/static/js/screens/console-funnel-data-health.js',
    '/static/js/screens/console-review.js',
    '/static/js/screens/console-statistics.js',
    '/static/js/screens/console-daily-plan.js',
    '/static/js/screens/console-expert-knowledge.js',
    '/static/js/console-navigation.js',
    '/static/js/console-actions.js',
    '/static/js/console-events.js',
    '/static/js/console-main.js',
  ];

  await expect(page.getByRole('heading', { name: 'Dantabot Control Console' })).toBeVisible();
  await expect(page.locator('link[href="/static/css/console.css"]')).toHaveCount(1);
  await expect(page.locator('script[src="/static/js/console.js"]')).toHaveCount(0);
  await expect(page.locator('[onclick], [onchange]')).toHaveCount(0);
  await expect(page.locator('#loginSubmitBtn')).toHaveAttribute('type', 'submit');
  for (const scriptSrc of expectedScripts) {
    await expect(page.locator(`script[src="${scriptSrc}"]`)).toHaveCount(1);
  }
  await expect(page.locator('.screen')).toHaveCount(18);

  const appDisplay = await page.locator('.app').evaluate((element) => getComputedStyle(element).display);
  expect(appDisplay).toBe('none');

  const missingGlobals = await page.evaluate(() => {
    const expectedFunctions = [
      'showScreen',
      'engineTestLoadTodayResults',
      'engineTestLoadLogs',
      'loadFunnelData',
      'liquidateAll',
      'liveDecisionActivate',
      'engineTestRun',
      'saveRiskSettings',
      'loadAlerts',
      'ackAlert',
      'loadApprovalQueue',
      'approveRequest',
      'rejectRequest',
      'deferRequest',
      'loadMissedTracking',
      'filterMissedTracking',
      'loadFalsePositive',
      'loadConfidenceCalibration',
      'runConfidenceCalibration',
      'loadDailyPlanScreen',
      'generateDailyPlan',
      'bindConsoleActionEvents',
      'bindEvents',
      'init',
      'updateSettingsProfileField',
    ];
    const missing = expectedFunctions.filter((name) => typeof window[name] !== 'function');
    if (typeof window._settingsProfileData === 'undefined') {
      missing.push('_settingsProfileData');
    }
    return missing;
  });
  expect(missingGlobals).toEqual([]);

  const loginClickSubmitsForm = await page.evaluate(() => {
    const form = document.getElementById('loginForm');
    const button = document.getElementById('loginSubmitBtn');
    let submitted = false;
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      event.stopImmediatePropagation();
      submitted = true;
    }, { capture: true, once: true });
    button.click();
    return submitted;
  });
  expect(loginClickSubmitsForm).toBe(true);

  const delegatedActionCalls = await page.evaluate(() => {
    const calls = [];
    const originalShowScreen = window.showScreen;
    const originalFilterMissedTracking = window.filterMissedTracking;

    window.showScreen = (screen) => { calls.push(`showScreen:${screen}`); };
    window.filterMissedTracking = (filter) => { calls.push(`filterMissedTracking:${filter}`); };

    const screenButton = document.createElement('button');
    screenButton.dataset.action = 'showScreen';
    screenButton.dataset.screen = 'alerts';
    document.body.appendChild(screenButton);
    screenButton.click();

    const filterButton = document.createElement('button');
    filterButton.dataset.action = 'filterMissedTracking';
    filterButton.dataset.filter = 'candidate';
    document.body.appendChild(filterButton);
    filterButton.click();

    screenButton.remove();
    filterButton.remove();
    window.showScreen = originalShowScreen;
    window.filterMissedTracking = originalFilterMissedTracking;
    return calls;
  });
  expect(delegatedActionCalls).toEqual(['showScreen:alerts', 'filterMissedTracking:candidate']);

  const severeErrors = page._statusTruthBrowserErrors.filter((message) => (
    /ReferenceError|TypeError/i.test(message)
    || /Failed to load resource.*\/static\//i.test(message)
  ));
  expect(severeErrors).toEqual([]);
});

test('Diagnostics does not mark null GET payloads as complete', async ({ page }) => {
  await page.evaluate(() => engineTestLoadTodayResults());

  await expect(page.locator('#et-badge-s2')).toHaveText('대기');
  await expect(page.locator('#et-badge-s3')).toHaveText('대기');
  await expect(page.locator('#et-badge-s4')).toHaveText('대기');
  await expect(page.locator('#et-badge-s5')).toHaveText('미생성');
  await expect(page.locator('#et-result-s2')).toContainText('"market_tone": null');
  await expect(page.locator('#et-result-s5')).toHaveText('null');
});

test('S2 manual success does not imply S3-S5 completion', async ({ page }) => {
  await page.evaluate(() => { window.__statusTruthScenario = 's2-success'; });
  await page.evaluate(() => engineTestLoadTodayResults());

  await expect(page.locator('#et-badge-s2')).toHaveText('완료');
  await expect(page.locator('#et-badge-s3')).toHaveText('대기');
  await expect(page.locator('#et-badge-s4')).toHaveText('대기');
  await expect(page.locator('#et-badge-s5')).toHaveText('미생성');

  await page.evaluate(() => renderTodayFeed());
  const todayStates = await page.evaluate(() => Array.from(document.querySelectorAll('#today-ops-feed > div'))
    .map((el) => el.textContent.replace(/\s+/g, ' ').trim())
    .filter((text) => text.indexOf('S') >= 0));
  expect(todayStates.find((text) => text.includes('S2 시장톤 분석'))).toContain('완료');
  expect(todayStates.find((text) => text.includes('S3 유니버스 필터'))).toContain('대기');
  expect(todayStates.find((text) => text.includes('S4 하이브리드 스크리닝'))).toContain('대기');
  expect(todayStates.find((text) => text.includes('S5 Daily Plan 생성'))).toContain('미생성');
});

test('schedule skip is shown as skipped instead of complete', async ({ page }) => {
  await page.evaluate(() => { window.__statusTruthScenario = 'skip'; });
  await page.evaluate(() => engineTestLoadTodayResults());

  for (const step of ['s2', 's3', 's4', 's5', 's5v', 's5a', 's6']) {
    await expect(page.locator(`#et-badge-${step}`)).toHaveText('비거래일 스킵');
  }
});

test('Funnel Monitor explains S3 zero pass-through without static rejection numbers', async ({ page }) => {
  await page.evaluate(() => { window.__statusTruthScenario = 'funnel-empty'; });
  await page.evaluate(() => loadFunnelData());

  await expect(page.locator('#funnel-total-source')).toContainText('DB 집계 아님');
  await expect(page.locator('#funnel-layer1-detail')).toContainText('raw 30 / 탈락 30');
  await expect(page.locator('#funnel-empty-reason')).toContainText('S3는 실행됐으나 통과 종목 0개라 S4/S5 미생성');
  await expect(page.locator('#funnel-layer1-reasons-tbody')).toContainText('S3 breakdown 미수집');
  await expect(page.locator('#funnel-layer1-reasons-tbody')).not.toContainText('1,120');
  await expect(page.locator('#funnel-quality-strength-detail')).toContainText('후보 없음: S3 통과 0');
});

test('Funnel candidate table maps ticker and code keys to assignments', async ({ page }) => {
  await page.evaluate(() => { window.__statusTruthScenario = 'funnel-candidates'; });
  await page.evaluate(() => loadFunnelData());

  await expect(page.locator('#funnel-candidates-tbody')).toContainText('AAA001');
  await expect(page.locator('#funnel-candidates-tbody')).toContainText('BBB002');
  await expect(page.locator('#funnel-candidates-tbody')).toContainText('LOW_VOL');
  await expect(page.locator('#funnel-candidates-tbody')).toContainText('HIGH_VOL');
});

test('Diagnostics log panel shows empty log file reason', async ({ page }) => {
  await page.evaluate(() => { window.__statusTruthScenario = 'logs-empty'; });
  await page.evaluate(() => engineTestLoadLogs(''));

  await expect(page.locator('#et-server-log')).toContainText('서버 로그 파일은 비어 있습니다: /tmp/mock-empty-server.log');
});

test('Diagnostics cards display pipeline_run_audit source time and status', async ({ page }) => {
  await page.evaluate(() => { window.__statusTruthScenario = 'audit-visible'; });
  await page.evaluate(() => engineTestLoadTodayResults());

  await expect(page.locator('#et-audit-s3')).toContainText('08:15:32 KST');
  await expect(page.locator('#et-audit-s3')).toContainText('자동 실행 결과를 카드에 표시 중');
  await expect(page.locator('#et-audit-s3')).toContainText('success');
  await expect(page.locator('#et-audit-s3')).toContainText('raw=30 filtered=0');
});


test('Trading Monitor exposes automatic monitoring gaps for held positions', async ({ page }) => {
  await page.evaluate(() => {
    const host = document.createElement('div');
    host.id = 'tm-monitoring-render-host';
    document.body.appendChild(host);
    host.innerHTML = window.renderPositionRow({
      symbol: '005930',
      name: '삼성전자',
      qty: 1,
      entry_price: 100000,
      market_price: 84000,
      highest_price_since_entry: 100000,
      active_stop_price: 97000,
      monitoring_status: '미감시',
      monitoring_detail: 'KIS 실보유에는 있으나 자동 손절/트레일링 감시 대상이 아님',
      auto_monitoring: false,
      ws_subscribed: false,
      position_manager_registered: false,
      stop_state_source: 'fallback',
      timed_liquidation_target: true,
      timed_liquidation_status: '시간청산 대상',
      profile_assigned: 'MID_VOL',
    });
  });

  const host = page.locator('#tm-monitoring-render-host');
  await expect(host.getByText('삼성전자')).toBeVisible();
  await expect(host.getByText('미감시')).toBeVisible();
  await expect(host.getByText('S8등록')).toBeVisible();
  await expect(host.getByText('미구독')).toBeVisible();
  await expect(host.getByText('시간청산 대상')).toBeVisible();
});
