# INBOX_EXECUTOR_phase3_e2e (Oracle 역할)

## 역할
너는 Oracle이다. Phase 3 구현을 검증하는 Playwright E2E 테스트를 작성하라.
완료 후 `docs/agent-comm/OUTBOX_EXECUTOR_phase3_e2e.md`에 결과를 작성하라.

백엔드 서버는 http://127.0.0.1:8000 에서 실행 중이다.
로그인 정보: username=admin, password=test1234

---

## 작업 1 — 기존 테스트 파일 확인

`tests/e2e/phase1-phase2.spec.cjs` 파일을 참고해 패턴을 파악한다.
로그인 helper 함수, openScreen helper 함수를 재사용한다.

---

## 작업 2 — phase3.spec.cjs 신규 작성

파일: `tests/e2e/phase3.spec.cjs`

### 테스트 시나리오 7개

#### 시나리오 1: Review & Audit API — review-audit/today 응답 형식
```javascript
test('Phase 3: review-audit today API responds', async ({ request }) => {
  const res = await request.get(`${backendUrl}/api/v1/review-audit/today`);
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.ok).toBe(true);
});
```

#### 시나리오 2: Learning Memory API — learning-memory/today 응답 형식
```javascript
test('Phase 3: learning-memory today API responds', async ({ request }) => {
  const res = await request.get(`${backendUrl}/api/v1/learning-memory/today`);
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.ok).toBe(true);
});
```

#### 시나리오 3: Learning Memory active 엔드포인트
```javascript
test('Phase 3: learning-memory active API responds', async ({ request }) => {
  const res = await request.get(`${backendUrl}/api/v1/learning-memory/active`);
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.ok).toBe(true);
});
```

#### 시나리오 4: S10 Review & Audit 수동 실행
```javascript
test('Phase 3: review-audit run returns ok', async ({ request }) => {
  const res = await request.post(`${backendUrl}/api/v1/review-audit/run`);
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.ok).toBe(true);
});
```

#### 시나리오 5: S11 Learning Memory 수동 실행
```javascript
test('Phase 3: learning-memory build returns ok', async ({ request }) => {
  const res = await request.post(`${backendUrl}/api/v1/learning-memory/build`);
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.ok).toBe(true);
});
```

#### 시나리오 6: UI — Review & Audit 화면에 Learning Memory 섹션 존재
```javascript
test('Phase 3: Review & Audit screen has Learning Memory section', async ({ page }) => {
  await login(page);
  await openScreen(page, /Review/i, 'Review');   // 버튼/heading 이름은 실제 HTML에서 확인
  await expect(page.locator('#ra-learning-memory')).toBeVisible();
  await expect(page.locator('#ra-profile-performance')).toBeVisible();
});
```
→ 버튼/heading 이름은 실제 console.html을 grep해서 정확히 확인한 뒤 사용할 것.

#### 시나리오 7: UI — KIS System Test에 S11 카드 존재
```javascript
test('Phase 3: KIS System Test has S11 card', async ({ page }) => {
  await login(page);
  await openScreen(page, /KIS System Test/i, 'KIS System Test');
  await expect(page.locator('#test-s11').first()).toBeVisible();
  await expect(page.getByText('Learning Memory Builder').first()).toBeVisible();
});
```

---

## 작업 3 — 테스트 실행

```bash
export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh" && nvm use 22 && \
npx playwright test tests/e2e/phase3.spec.cjs --reporter=list
```

실패한 테스트가 있으면 원인을 분석하고 수정 후 재실행한다.
수정 범위: 테스트 파일(phase3.spec.cjs)만. 애플리케이션 코드는 수정하지 않는다.

---

## OUTBOX 작성 형식

```markdown
# OUTBOX_EXECUTOR_phase3_e2e

## 결과 요약
## 완료 체크리스트
## 테스트 결과 (PASS/FAIL 목록)
## 발견된 버그 또는 특이사항
```
