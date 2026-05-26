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

async function login(page, url) {
  const [name, value] = createSessionCookie().split('=');
  await page.context().addCookies([{ name, value, url }]);
  await page.goto(`${url}/console`, { waitUntil: 'domcontentloaded', timeout: 20_000 });
  await expect(page.getByRole('heading', { name: 'Today Control' })).toBeVisible();
}

test.describe('Phase 3 UI changes — count labels and L/M/H/T placement', () => {
  const url = process.env.BACKEND_URL || 'http://127.0.0.1:8000';

  test('Today Control: L/M/H/T 분포가 fp-signals 안에 있고 fp-positions는 분포 없음', async ({ page }) => {
    await login(page, url);

    // fp-signals 카드 안에 L/M/H/T 카운트들이 모두 있어야 함
    const signalsCard = page.locator('.funnel-step', { has: page.locator('#fp-signals') });
    await expect(signalsCard.locator('#tc-low-vol-count')).toBeVisible();
    await expect(signalsCard.locator('#tc-mid-vol-count')).toBeVisible();
    await expect(signalsCard.locator('#tc-high-vol-count')).toBeVisible();
    await expect(signalsCard.locator('#tc-theme-spike-count')).toBeVisible();

    // fp-positions 카드 안에는 L/M/H/T 분포가 없어야 함
    const positionsCard = page.locator('.funnel-step', { has: page.locator('#fp-positions') });
    await expect(positionsCard.locator('#tc-low-vol-count')).toHaveCount(0);
    await expect(positionsCard.locator('#tc-mid-vol-count')).toHaveCount(0);
  });

  test('Funnel Monitor: 카드 타이틀이 "오늘 BUY 신호 (원본)"으로 변경됨', async ({ page }) => {
    await login(page, url);

    // Funnel Monitor 화면으로 이동
    await page.evaluate(() => {
      const btn = document.querySelector('[data-screen="funnel"]');
      if (btn) btn.click();
    });

    // 새 라벨 텍스트 존재 확인
    const funnelCandidatesCard = page.locator('.card.compact', { has: page.locator('#funnel-candidates') });
    await expect(funnelCandidatesCard.locator('.card-title')).toContainText('오늘 BUY 신호');
    await expect(funnelCandidatesCard.locator('.card-title')).toContainText('원본');

    // ⓘ 아이콘 또는 title 속성 (툴팁) 존재 확인
    const titleEl = funnelCandidatesCard.locator('.card-title');
    const titleAttr = await titleEl.getAttribute('title');
    expect(titleAttr).toBeTruthy();
    expect(titleAttr).toContain('Daily Plan');

    // 설명 텍스트도 새 문구
    await expect(funnelCandidatesCard.locator('#funnel-candidates-detail')).toContainText('Daily Plan');
  });
});
