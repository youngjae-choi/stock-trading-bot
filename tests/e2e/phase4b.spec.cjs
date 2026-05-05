const { test, expect } = require('@playwright/test');
const fs = require('fs');

const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8000';

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

// ── Expert Knowledge CRUD API ──────────────────────────
test('Phase 4B: create expert knowledge item', async ({ request }) => {
  const res = await request.post(`${backendUrl}/api/v1/expert-knowledge/`, {
    data: { title: 'E2E 테스트 지식', content: '테스트 내용', scope: 'ALL', category: 'general', priority: 5 },
  });
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.ok).toBe(true);
  expect(body.payload.status).toBe('pending');
  expect(body.payload.title).toBe('E2E 테스트 지식');
});

test('Phase 4B: list expert knowledge items', async ({ request }) => {
  const res = await request.get(`${backendUrl}/api/v1/expert-knowledge/`);
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.ok).toBe(true);
  expect(Array.isArray(body.payload)).toBe(true);
});

test('Phase 4B: approve and get active knowledge', async ({ request }) => {
  // 1. 새 항목 생성
  const createRes = await request.post(`${backendUrl}/api/v1/expert-knowledge/`, {
    data: { title: '승인 테스트', content: '승인 후 active 확인', scope: 'S4_HYBRID_SCREENING', category: 'timing', priority: 2 },
  });
  const created = await createRes.json();
  const itemId = created.payload.id;

  // 2. 승인
  const approveRes = await request.post(`${backendUrl}/api/v1/expert-knowledge/${itemId}/approve`);
  expect(approveRes.ok()).toBeTruthy();
  const approved = await approveRes.json();
  expect(approved.ok).toBe(true);
  expect(approved.payload.status).toBe('approved');

  // 3. active 목록에서 확인
  const activeRes = await request.get(`${backendUrl}/api/v1/expert-knowledge/active/S4_HYBRID_SCREENING`);
  expect(activeRes.ok()).toBeTruthy();
  const activeBody = await activeRes.json();
  expect(activeBody.ok).toBe(true);
  const ids = (activeBody.payload || []).map(k => k.id);
  expect(ids).toContain(itemId);
});

// ── Context Preview includes knowledge ────────────────
test('Phase 4B: S4 context-preview includes knowledge_items', async ({ request }) => {
  const res = await request.get(`${backendUrl}/api/v1/pipeline/S4/context-preview`);
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.ok).toBe(true);
  expect(body.payload).toHaveProperty('knowledge_items');
  expect(body.payload).toHaveProperty('knowledge_count');
});

test('Phase 4B: S5 context-preview includes knowledge_items', async ({ request }) => {
  const res = await request.get(`${backendUrl}/api/v1/pipeline/S5/context-preview`);
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.ok).toBe(true);
  expect(body.payload).toHaveProperty('knowledge_items');
});

// ── UI — Expert Knowledge 화면 ─────────────────────────
test('Phase 4B: Expert Knowledge screen is accessible', async ({ page }) => {
  await login(page);
  await page.getByRole('button', { name: /Expert Knowledge/i }).click();
  await expect(page.getByRole('heading', { name: 'Expert Knowledge' })).toBeVisible();
  await expect(page.locator('#ek-list-tbody')).toBeVisible();
  await expect(page.locator('#ek-title')).toBeVisible();
});
