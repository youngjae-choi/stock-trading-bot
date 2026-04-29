/**
 * 단타봇 API 허브 — E2E 테스트 v2
 */
const { test, expect } = require('@playwright/test');

const API = process.env.BACKEND_URL || 'http://127.0.0.1:8000';

async function apiFetch(request, path) {
  const res = await request.get(`${API}${path}`, { timeout: 20000 });
  return { status: res.status(), body: await res.json() };
}

test.describe('[A] Universe', () => {
  test('거래량 J top30', async ({ request }) => {
    const { body } = await apiFetch(request, '/api/v1/kis/universe/volume-rank?market_code=J&top_n=30');
    expect(body.ok).toBe(true);
    expect(body.payload.items.length).toBeGreaterThan(0);
    console.log(`거래량 J top30: ${body.payload.count}건`);
  });
  test('거래량 STK top30', async ({ request }) => {
    const { body } = await apiFetch(request, '/api/v1/kis/universe/volume-rank?market_code=STK&top_n=30');
    expect(body.ok).toBe(true);
    expect(body.payload.items.length).toBeGreaterThan(0);
    console.log(`거래량 STK top30: ${body.payload.count}건`);
  });
  test('거래량 KSQ top30', async ({ request }) => {
    const { body } = await apiFetch(request, '/api/v1/kis/universe/volume-rank?market_code=KSQ&top_n=30');
    expect(body.ok).toBe(true);
    expect(body.payload.items.length).toBeGreaterThan(0);
    console.log(`거래량 KSQ top30: ${body.payload.count}건`);
  });
  test('거래량 J top60 병합', async ({ request }) => {
    const { body } = await apiFetch(request, '/api/v1/kis/universe/volume-rank?market_code=J&top_n=60');
    expect(body.ok).toBe(true);
    expect(body.payload.items.length).toBeGreaterThan(30);
    console.log(`거래량 J top60: ${body.payload.count}건`);
  });
  test('등락률 J top30', async ({ request }) => {
    const { body } = await apiFetch(request, '/api/v1/kis/universe/price-rank?sort_by=change_rate&market_code=J&top_n=30');
    expect(body.ok).toBe(true);
    expect(body.payload.items.length).toBeGreaterThan(0);
    console.log(`등락률 J top30: ${body.payload.count}건`);
  });
  test('등락률 J top40', async ({ request }) => {
    const { body } = await apiFetch(request, '/api/v1/kis/universe/price-rank?sort_by=change_rate&market_code=J&top_n=40');
    expect(body.ok).toBe(true);
    expect(body.payload.items.length).toBeGreaterThan(30);
    console.log(`등락률 J top40: ${body.payload.count}건`);
  });
  test('등락률 J top50', async ({ request }) => {
    const { body } = await apiFetch(request, '/api/v1/kis/universe/price-rank?sort_by=change_rate&market_code=J&top_n=50');
    expect(body.ok).toBe(true);
    expect(body.payload.items.length).toBeGreaterThan(30);
    console.log(`등락률 J top50: ${body.payload.count}건`);
  });
  test('거래대금 J top30', async ({ request }) => {
    const { body } = await apiFetch(request, '/api/v1/kis/universe/price-rank?sort_by=trade_amount&market_code=J&top_n=30');
    expect(body.ok).toBe(true);
    expect(body.payload.items.length).toBeGreaterThan(0);
    console.log(`거래대금 J top30: ${body.payload.count}건`);
  });
  test('거래대금 J top40', async ({ request }) => {
    const { body } = await apiFetch(request, '/api/v1/kis/universe/price-rank?sort_by=trade_amount&market_code=J&top_n=40');
    expect(body.ok).toBe(true);
    expect(body.payload.items.length).toBeGreaterThan(30);
    console.log(`거래대금 J top40: ${body.payload.count}건`);
  });
});

test.describe('[B] 현재상태', () => {
  test('현재가 005930', async ({ request }) => {
    const { status } = await apiFetch(request, '/api/v1/kis/price/005930');
    expect(status).toBe(200);
  });
  test('호가 005930', async ({ request }) => {
    const { status } = await apiFetch(request, '/api/v1/kis/orderbook/005930');
    expect(status).toBe(200);
  });
  test('분봉 005930', async ({ request }) => {
    const { body } = await apiFetch(request, '/api/v1/kis/chart/intraday/005930');
    expect(body.ok).toBe(true);
  });
});

test.describe('[C] 실시간', () => {
  test('WebSocket 상태 조회', async ({ request }) => {
    const { body } = await apiFetch(request, '/api/v1/kis/realtime/status');
    expect(body.ok).toBe(true);
    console.log(`WS connected=${body.payload?.connected}, cache=${body.payload?.cache_size}`);
  });
  test('최신 체결 캐시 조회', async ({ request }) => {
    const { body } = await apiFetch(request, '/api/v1/kis/realtime/latest?n=10');
    expect(body.ok).toBe(true);
    console.log(`실시간 캐시 items=${body.payload?.items?.length ?? 0}`);
  });
});

test.describe('[D] 주문', () => {
  test('잔고 조회', async ({ request }) => {
    const { status } = await apiFetch(request, '/api/v1/kis/balance');
    expect(status).toBe(200);
  });
});

test.describe('[E] 스윙', () => {
  test('일봉 005930', async ({ request }) => {
    const { body } = await apiFetch(request, '/api/v1/kis/chart/daily/005930?period_code=D');
    expect(body.ok).toBe(true);
    const rows = body.payload?.output || [];
    expect(rows.length).toBeGreaterThan(0);
    console.log(`일봉: ${rows.length}건, 키=${Object.keys(rows[0]).slice(0,5).join(',')}`);
  });
  test('재무 005930', async ({ request }) => {
    const { body } = await apiFetch(request, '/api/v1/kis/fundamental/005930');
    // ok=false여도 200으로 응답해야 함 (미지원 응답 허용)
    expect(body).toHaveProperty('ok');
    console.log(`재무: ok=${body.ok}, error=${body.error || 'none'}`);
  });
});

test.describe('[UI] Console', () => {
  test('정적 콘솔 타이틀 표시', async ({ page }) => {
    await page.goto(`${API}/console`, { waitUntil: 'networkidle', timeout: 20000 });
    await expect(page.getByText('Dantabot Control Console')).toBeVisible({ timeout: 10000 });
  });
});
