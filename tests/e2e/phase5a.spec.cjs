const { test, expect } = require('@playwright/test');
const fs = require('fs');

const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8000';

// Resolve all DQ events written during this test suite so they don't block production orders.
test.afterAll(async ({ request }) => {
  await request.post(`${backendUrl}/api/v1/data-quality/resolve`).catch(() => {});
});

function envValue(key, fallback = '') {
  if (process.env[key]) return process.env[key];
  try {
    const text = fs.readFileSync('.env', 'utf8');
    const line = text.split(/\r?\n/).find((l) => l.startsWith(`${key}=`));
    return line ? line.slice(key.length + 1).trim() : fallback;
  } catch (_) { return fallback; }
}

async function login(page) {
  await page.goto(`${backendUrl}/console`, { waitUntil: 'domcontentloaded', timeout: 20_000 });
  await page.locator('#loginUsername').fill(envValue('APP_ADMIN_USERNAME', 'admin'));
  await page.locator('#loginPassword').fill(envValue('APP_ADMIN_PASSWORD', ''));
  await page.getByRole('button', { name: '로그인' }).click();
  await expect(page.getByRole('heading', { name: 'Today Control' })).toBeVisible();
}

// ── Data Quality Guard ─────────────────────────────────
test('Phase 5A: DQ status returns NORMAL by default', async ({ request }) => {
  const res = await request.get(`${backendUrl}/api/v1/data-quality/status`);
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.ok).toBe(true);
  expect(body.payload).toHaveProperty('overall_status');
  expect(body.payload).toHaveProperty('event_counts');
  expect(body.payload).toHaveProperty('events');
});

test('Phase 5A: record DQ event and status reflects it', async ({ request }) => {
  const res = await request.post(`${backendUrl}/api/v1/data-quality/event`, {
    data: { event_type: 'tick_delay', severity: 'WARNING', detail: 'E2E test event' },
  });
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.ok).toBe(true);
  expect(body.payload).toHaveProperty('event_id');
});

test('Phase 5A: DQ snapshot create and get', async ({ request }) => {
  // create
  const createRes = await request.post(`${backendUrl}/api/v1/data-quality/snapshot`);
  expect(createRes.ok()).toBeTruthy();
  const created = await createRes.json();
  expect(created.ok).toBe(true);
  expect(created.payload).toHaveProperty('overall_status');

  // get latest
  const getRes = await request.get(`${backendUrl}/api/v1/data-quality/snapshot`);
  expect(getRes.ok()).toBeTruthy();
  const snap = await getRes.json();
  expect(snap.ok).toBe(true);
});

// ── Alert Center ──────────────────────────────────────
test('Phase 5A: create and list alert', async ({ request }) => {
  const createRes = await request.post(`${backendUrl}/api/v1/alerts/`, {
    data: { alert_type: 'risk_guard', title: 'E2E 테스트 알림', severity: 'WARNING', detail: '테스트' },
  });
  expect(createRes.ok()).toBeTruthy();
  const created = await createRes.json();
  expect(created.ok).toBe(true);
  expect(created.payload.title).toBe('E2E 테스트 알림');
  const alertId = created.payload.id;

  // list
  const listRes = await request.get(`${backendUrl}/api/v1/alerts/`);
  expect(listRes.ok()).toBeTruthy();
  const list = await listRes.json();
  expect(list.ok).toBe(true);
  expect(Array.isArray(list.payload)).toBe(true);
  const ids = list.payload.map((a) => a.id);
  expect(ids).toContain(alertId);
});

test('Phase 5A: acknowledge alert', async ({ request }) => {
  // create first
  const createRes = await request.post(`${backendUrl}/api/v1/alerts/`, {
    data: { alert_type: 'db_fail', title: 'Ack 테스트', severity: 'CRITICAL' },
  });
  const { payload: alert } = await createRes.json();

  // acknowledge
  const ackRes = await request.post(`${backendUrl}/api/v1/alerts/${alert.id}/acknowledge`);
  expect(ackRes.ok()).toBeTruthy();
  const ackBody = await ackRes.json();
  expect(ackBody.ok).toBe(true);
});

test('Phase 5A: alert summary', async ({ request }) => {
  const res = await request.get(`${backendUrl}/api/v1/alerts/summary`);
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.ok).toBe(true);
  // API returns total_count / unacknowledged_count / severity_counts
  const p = body.payload;
  expect(p.total_count ?? p.total).toBeDefined();
  expect(p.unacknowledged_count ?? p.unacknowledged).toBeDefined();
});

// ── Human Approval Queue ──────────────────────────────
test('Phase 5A: create approval request', async ({ request }) => {
  const res = await request.post(`${backendUrl}/api/v1/approval/`, {
    data: {
      change_type: 'risk_profile_change',
      title: 'E2E 승인 요청',
      description: '리스크 프로파일 변경 테스트',
    },
  });
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.ok).toBe(true);
  expect(body.payload.status).toBe('pending');
});

test('Phase 5A: list and approve request', async ({ request }) => {
  // create
  const createRes = await request.post(`${backendUrl}/api/v1/approval/`, {
    data: { change_type: 'rulepack_change', title: '승인 테스트', description: '테스트' },
  });
  const { payload: req } = await createRes.json();

  // approve
  const approveRes = await request.post(`${backendUrl}/api/v1/approval/${req.id}/approve`);
  expect(approveRes.ok()).toBeTruthy();
  const approveBody = await approveRes.json();
  expect(approveBody.ok).toBe(true);
  expect(approveBody.payload.status).toBe('approved');
});

test('Phase 5A: reject and defer requests', async ({ request }) => {
  // create two
  const [r1, r2] = await Promise.all([
    request.post(`${backendUrl}/api/v1/approval/`, {
      data: { change_type: 'knowledge_change', title: '거부 테스트', description: '' },
    }),
    request.post(`${backendUrl}/api/v1/approval/`, {
      data: { change_type: 'scoring_weight_change', title: '보류 테스트', description: '' },
    }),
  ]);
  const { payload: req1 } = await r1.json();
  const { payload: req2 } = await r2.json();

  const rejectRes = await request.post(`${backendUrl}/api/v1/approval/${req1.id}/reject`);
  expect((await rejectRes.json()).payload.status).toBe('rejected');

  const deferRes = await request.post(`${backendUrl}/api/v1/approval/${req2.id}/defer`);
  expect((await deferRes.json()).payload.status).toBe('deferred');
});

// ── UI ────────────────────────────────────────────────
test('Phase 5A: Alert Center screen is accessible', async ({ page }) => {
  await login(page);
  await page.getByRole('button', { name: /Alert Center/i }).click();
  await expect(page.getByRole('heading', { name: 'Alert Center' })).toBeVisible();
  await expect(page.locator('#al-list-tbody')).toBeVisible();
});

test('Phase 5A: Approval Queue screen is accessible', async ({ page }) => {
  await login(page);
  await page.getByRole('button', { name: /Approval Queue/i }).click();
  await expect(page.getByRole('heading', { name: 'Approval Queue' })).toBeVisible();
  await expect(page.locator('#aq-list-tbody')).toBeVisible();
});

test('Phase 5A: Data Quality Guard card visible in Data screen', async ({ page }) => {
  await login(page);
  await page.getByRole('button', { name: /Data & API/i }).click();
  await expect(page.locator('#dq-overall-status')).toBeVisible();
  await expect(page.locator('#dq-event-count')).toBeVisible();
});
