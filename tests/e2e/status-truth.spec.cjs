const { test, expect } = require('@playwright/test');
const path = require('path');

const consolePath = 'file://' + path.resolve(__dirname, '../../backend/static/console.html');

test.beforeEach(async ({ page }) => {
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
        '/api/v1/funnel/summary': { ok: true, payload: {} },
        '/api/v1/decision/status': { ok: true, payload: { active: false } },
        '/api/v1/orders/today': { ok: true, payload: { orders: [] } },
        '/api/v1/orders/positions': { ok: true, payload: { positions: [] } },
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

      const body = responses[pathName] || { ok: true, payload: {} };
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    };
  });
  await page.goto(consolePath);
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
