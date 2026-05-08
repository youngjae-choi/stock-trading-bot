# INBOX_CODEX - 2026-05-08 - console.js Stage 2 추가 분리 및 검증

## 요청자

PM 지시를 받은 Sisyphus/Codex

## 담당

Codex CLI

## 목적

`backend/static/js/console.js`를 한 번에 전부 모듈화하지 않고, classic script 전역 구조를 유지한 채 공통부와 낮은 위험 화면부터 추가 분리한다.

작업 후 안전 검증과 targeted Playwright 테스트까지 수행하고 결과를 OUTBOX에 보고한다.

## 반드시 먼저 읽을 문서

문서 우선순위와 읽기 순서는 `DOC_HIERARCHY.md`를 따른다.

필수:

- `ONBOARDING.md`
- `AGENTS.md`
- `CODEX.md`
- `FEATURE_TEMPLATE.md`
- `UI_BASELINE.md`
- `ERROR_HANDLING.md`
- `IMPLEMENTATION_RULES.md`
- `TEST_RULES.md`
- `docs/agent-comm/OUTBOX_ORACLE_20260507_1920_console_split_audit.md`
- `docs/agent-comm/OUTBOX_EXECUTOR_20260507_1930_console_split_stage1.md`
- `docs/agent-comm/OUTBOX_ORACLE_20260507_1950_console_split_stage1_review.md`

## 배경

Stage 1에서 `console.html`의 CSS와 JS는 각각 아래 파일로 분리되었다.

- `backend/static/css/console.css`
- `backend/static/js/console.js`

Oracle 리뷰 결론:

- Stage 1은 배포 가능하다.
- 추가 분리 시 classic script 로드 순서와 전역 함수 노출 계약을 먼저 고정해야 한다.
- `showScreen()`의 screen별 loader 흐름을 기준으로 의존성 그래프를 만든 뒤 작은 단위로 분리해야 한다.
- 바로 ES module/IIFE로 바꾸면 inline handler와 전역 함수 의존성이 깨질 위험이 크다.

## 금지 사항

- git commit 금지.
- 사용자 변경사항 되돌리지 말 것.
- 서버 재시작 금지.
- `type="module"` 사용 금지.
- ES module import/export 사용 금지.
- IIFE로 전역 함수 은닉 금지.
- 기능 변경 금지. 이번 작업은 구조 분리다.
- API endpoint 변경 금지.
- inline handler 제거 금지. 이벤트 위임 전환은 별도 작업으로 남긴다.
- S1~S11 실행 금지.
- 주문/청산/decision activate/emergency halt/resume/settings save/API POST 호출 금지.
- 외부 LLM/KIS 호출 금지.

## 구현 범위

### 1. script load order 고정

`backend/static/console.html`의 body 끝 script 로드를 여러 classic script로 나눈다.

권장 순서:

```html
<script src="/static/js/console-state.js"></script>
<script src="/static/js/console-utils.js"></script>
<script src="/static/js/console-api.js"></script>
<script src="/static/js/console-auth.js"></script>
<script src="/static/js/console-navigation.js"></script>
<script src="/static/js/screens/console-alerts.js"></script>
<script src="/static/js/screens/console-approval.js"></script>
<script src="/static/js/screens/console-missed-tracking.js"></script>
<script src="/static/js/screens/console-false-positive.js"></script>
<script src="/static/js/screens/console-confidence-calibration.js"></script>
<script src="/static/js/console-main.js"></script>
```

파일명은 코드베이스 상황에 맞게 조정 가능하지만, classic script 순서는 반드시 명확해야 한다.

### 2. 공통부 분리

`backend/static/js/console.js`에서 아래 성격의 코드를 별도 파일로 이동한다.

- 전역 DOM ref / 상태 / 상수: `console-state.js`
- 공통 formatting/time/theme/helper: `console-utils.js`
- 공통 `fetchJson` 및 API helper: `console-api.js`
- login/MFA/logout/auth/bootstrap 일부: `console-auth.js`
- `showScreen()` 및 nav/mobile menu 관련 코드: `console-navigation.js`

주의:

- top-level `var`/`function` 기반 classic global 동작을 유지한다.
- inline handler가 호출하는 함수는 계속 `window`에서 접근 가능해야 한다.
- `const`/`let`으로 바꾸며 전역 노출 계약을 깨지 않는다.

### 3. 낮은 위험 screen 분리

아래 low-risk screen부터 별도 파일로 이동한다.

- Alert Center: `loadAlerts`, `ackAlert`
- Approval Queue: `loadApprovalQueue`, `approveRequest`, `rejectRequest`, `deferRequest`
- Missed Entries: `loadMissedTracking`, `filterMissedTracking`
- False Positive: `loadFalsePositive`
- Confidence Calibration: `loadConfidenceCalibration`, `runConfidenceCalibration`

주의:

- trading/live/positions/diagnostics/settings/expert-knowledge/daily-plan은 이번 범위에서 분리하지 않는다.
- 특히 `engineTestRun`, `liveDecisionActivate`, `liveDecisionDeactivate`, `liquidateAll`, settings save 계열은 건드리지 않는다.

### 4. 잔여 파일

나머지 코드는 `backend/static/js/console-main.js`에 둔다.

기존 `backend/static/js/console.js`는 다음 중 하나로 처리한다.

- 완전히 비우거나 삭제하지 말고, 혼동 방지를 위해 더 이상 로드하지 않는 legacy 파일로 남긴다.
- 또는 코드베이스 관례상 삭제가 안전하면 삭제하되, OUTBOX에 삭제 이유와 검증 결과를 명확히 적는다.

권장: 이번 Stage에서는 `console.js`를 삭제하지 말고 로드 대상에서만 제외한다. 단, 중복 로드되면 함수 재정의/부작용 위험이 있으므로 HTML에서 기존 `console.js` 로드는 제거한다.

## 구현 전 확인

수정 전에 아래를 정적으로 확인하고 OUTBOX에 요약한다.

- 현재 `console.html` script 태그.
- `console.js` 내 주요 함수 위치.
- inline `onclick/onchange` 및 동적 handler가 요구하는 주요 전역 함수.
- `showScreen()`이 호출하는 loader 함수.

## 필수 검증

### 정적 검증

- `node --check` 대상:
  - 새로 만든 모든 `backend/static/js/**/*.js`
  - 잔여 `backend/static/js/console-main.js`
  - 필요 시 기존 `backend/static/js/console.js`
- `.venv/bin/python -m compileall -q backend`
- `git diff --check`

### Playwright smoke

기존 `tests/e2e/status-truth.spec.cjs`를 필요한 범위에서 조정해도 된다.

검증 조건:

- `/console` 또는 안전한 static server/mock 방식 사용.
- `/static/js/...` asset load failure 없음.
- `.screen` 18개 유지.
- 주요 전역 함수가 `window`에서 접근 가능.
- low-risk screen loader 함수가 `window`에서 접근 가능.
- `ReferenceError`/`TypeError` 없음.
- S1~S11 실행/주문/청산/decision activate/settings save/approval approve류 POST 버튼 클릭 금지.

실행 권장:

```bash
node --check backend/static/js/console-state.js
node --check backend/static/js/console-utils.js
node --check backend/static/js/console-api.js
node --check backend/static/js/console-auth.js
node --check backend/static/js/console-navigation.js
node --check backend/static/js/screens/console-alerts.js
node --check backend/static/js/screens/console-approval.js
node --check backend/static/js/screens/console-missed-tracking.js
node --check backend/static/js/screens/console-false-positive.js
node --check backend/static/js/screens/console-confidence-calibration.js
node --check backend/static/js/console-main.js
.venv/bin/python -m compileall -q backend
git diff --check
npx playwright test --config=playwright.config.cjs tests/e2e/status-truth.spec.cjs --workers=1
```

파일명이 달라지면 실제 파일명 기준으로 실행한다.

## OUTBOX 작성

작업 완료 후 아래 파일을 작성한다.

`docs/agent-comm/OUTBOX_CODEX_20260508_console_js_split_stage2.md`

포함 항목:

- 변경 파일 목록.
- 구현 전 확인 요약.
- 분리 후 script load order.
- 어떤 함수/영역을 어떤 파일로 옮겼는지.
- 기존 기능 영향 범위.
- 전역 함수/window 계약 확인 결과.
- 테스트 결과.
- 실행하지 않은 위험 테스트와 이유.
- 남은 위험.
- 다음 추천 작업.

## 완료 기준

- classic script 전역 구조가 유지된다.
- `console.html`이 새 JS 파일들을 올바른 순서로 로드한다.
- low-risk screen 함수들이 분리됐다.
- 주요 inline handler 함수가 `window`에서 접근 가능하다.
- 필수 정적 검증이 통과했다.
- targeted Playwright가 통과했다.
- OUTBOX에 결과가 기록됐다.
