# INBOX_EXECUTOR_engine_test_s6 — Oracle: Phase 1+2 Playwright 테스트

## 역할
너는 Oracle이다. 수석 아키텍트로서 Phase 1, 2 변경사항을 Playwright E2E 테스트로 검증한다.

## 작업 디렉토리
`/home/young/repos/stock-trading-bot`

---

## 배경

### Phase 1 완료 사항 (UI)
- "RulePack 생성" 문구 전체 제거
- Daily Plan & RulePack 화면 버튼 → 새로고침 + Context 보기 + 고급 작업 ▾ 드롭다운
- KIS System Test에 S5-V 카드 추가
- Settings 스케줄러 항목 확장 (S5-V, S5-A, S10, S11)
- S5 API endpoint: rulepack-gen/run → daily-plan/generate
- `/api/v1/bot/rulepack/today` bootstrap 호출 제거

### Phase 2 완료 사항 (Backend)
- `daily_trading_plans` 테이블 컬럼 6개 추가 (creation_mode, created_by, s3_result_id, s4_result_id, validated_at, superseded_at)
- S5 자동 파이프라인: generated → validated → active (자동 검증+활성화)
- 장중(09:00~15:30 KST) 수동 재실행 차단 `POST /api/v1/daily-plan/generate`
- `order_preflight_checks` 테이블 신규
- `order_preflight.py` 신규 (Pre-Flight Check 서비스)
- `order_executor.py`: rulepack_store 제거 → rule_cache + Pre-Flight 연동
- 패스워드 체크 복원 (DEV bypass 제거)

---

## 작업 1 — 기존 테스트 수정

`tests/e2e/console-smoke.spec.cjs` 가 Phase 1에서 제거된 요소를 테스트하고 있다. 아래 항목을 수정한다:

```
expect(html).toContain('API Logs');          # 제거됨 → 삭제
page.getByRole('button', { name: /API Logs/i }).click()  # 제거됨 → 수정
expect(page.getByRole('heading', { name: 'API Logs' })).toBeVisible()  # 제거됨 → 수정
```

수정 방향:
- `API Logs` 버튼 클릭 → `Data & API` 버튼 클릭으로 교체
- `API Logs` heading → 해당 화면의 실제 heading으로 교체
- `API Logs` 포함 여부 체크 → 삭제
- apiLogsTableBody 텍스트 체크 → Data & API 화면의 실제 요소로 교체 (없으면 삭제)

---

## 작업 2 — Phase 1+2 전용 테스트 파일 신규 작성

`tests/e2e/phase1-phase2.spec.cjs` 를 새로 작성한다.

아래 시나리오를 포함한다:

### 시나리오 1 — RulePack 문구 완전 제거 확인
```
GET /console HTML에 "RulePack 생성" 문자열이 없어야 한다
GET /console HTML에 "rulepack-gen" 문자열이 없어야 한다
GET /console HTML에 "S5 RulePack" 문자열이 없어야 한다 (Settings 라벨)
```

### 시나리오 2 — Daily Plan & RulePack 화면 버튼 확인
로그인 후 Daily Plan & RulePack 메뉴 클릭:
- "Daily Plan 생성" 버튼이 없어야 한다
- "새로고침" 버튼이 있어야 한다
- "고급 작업" 버튼이 있어야 한다
- "고급 작업" 클릭 시 드롭다운 메뉴가 나타나야 한다
- 드롭다운에 "S5 수동 재실행" 텍스트가 있어야 한다

### 시나리오 3 — KIS System Test S5-V 카드 확인
로그인 후 KIS System Test 메뉴 클릭:
- "S5-V" 텍스트가 있어야 한다
- "Daily Plan Validation" 텍스트가 있어야 한다
- "Daily Plan 검증 실행" 버튼이 있어야 한다

### 시나리오 4 — Settings 스케줄러 항목 확인
로그인 후 Settings 메뉴 클릭:
- "S5 Daily Plan 자동 생성" 텍스트가 있어야 한다
- "S5-V Daily Plan 자동 검증" 텍스트가 있어야 한다
- "S10 Review & Audit" 텍스트가 있어야 한다
- "S11 Learning Memory Builder" 텍스트가 있어야 한다

### 시나리오 5 — Daily Plan API 응답 구조 확인
```
GET /api/v1/daily-plan/today
응답: { ok: true, payload: null | { id, status, creation_mode, created_by, ... } }
payload가 있으면 creation_mode, created_by 필드가 존재해야 한다
```

### 시나리오 6 — 장중 수동 재실행 차단 API 테스트
```
POST /api/v1/daily-plan/generate
현재 시각이 09:00~15:30 KST 범위이면 403 반환 확인
현재 시각이 범위 밖이면 200 또는 500(LLM 없음) 반환 확인 (403이 아니면 OK)
```

### 시나리오 7 — 패스워드 체크 복원 확인
```
POST /api/v1/auth/login  body: { username: "admin", password: "wrongpassword" }
응답: 401 (이전에는 DEV bypass로 200이 반환되었음)
```

---

## 작업 3 — 테스트 실행

백엔드 서버가 실행 중인지 확인:
```bash
curl -s http://127.0.0.1:8000/health | head -c 100
```

서버가 실행 중이면 테스트 실행:
```bash
npx playwright test tests/e2e/console-smoke.spec.cjs tests/e2e/phase1-phase2.spec.cjs --reporter=list
```

서버가 실행 중이 아니면:
- 테스트 파일만 작성하고 실행은 생략
- OUTBOX에 "서버 미실행 — 테스트 파일만 작성, 실행 필요" 라고 명시

---

## 완료 후

`docs/agent-comm/OUTBOX_EXECUTOR_engine_test_s6.md` 에 결과 작성.

형식:
```
# OUTBOX_EXECUTOR_engine_test_s6
## 결과 요약
## 완료 체크리스트
- [x] 작업 1 — 기존 테스트 수정
- [x] 작업 2 — phase1-phase2.spec.cjs 작성
- [x] 작업 3 — 테스트 실행 결과
## 테스트 결과
(pass/fail 목록)
## 발견된 버그
(없으면 "없음")
## 특이사항
```
