# OUTBOX_CODEX - 2026-05-08 - console.js Stage 2 추가 분리

## 변경 파일 목록

- `backend/static/console.html`
- `backend/static/js/console-state.js`
- `backend/static/js/console-utils.js`
- `backend/static/js/console-api.js`
- `backend/static/js/console-auth.js`
- `backend/static/js/console-navigation.js`
- `backend/static/js/screens/console-alerts.js`
- `backend/static/js/screens/console-approval.js`
- `backend/static/js/screens/console-missed-tracking.js`
- `backend/static/js/screens/console-false-positive.js`
- `backend/static/js/screens/console-confidence-calibration.js`
- `backend/static/js/console-main.js`
- `tests/e2e/status-truth.spec.cjs`
- `docs/agent-comm/OUTBOX_CODEX_20260508_console_js_split_stage2.md`

참고: 기존 `backend/static/js/console.js`는 삭제하지 않고 legacy 파일로 남겼다. `console.html`에서는 더 이상 로드하지 않는다.

## 구현 전 확인 요약

- 기존 `console.html` script 태그는 body 끝의 `/static/js/console.js` 단일 classic script 1개였다.
- `console.js` 주요 위치:
  - 전역 DOM/state/상수: 1-89
  - `showScreen()` loader 흐름: 90-215
  - formatting/time/theme/helper 및 Today/overview 보조: 217-887
  - `fetchJson()`: 888-903
  - login/MFA/logout/bootstrap/control 일부: 905-1188
  - low-risk screens: alerts 4227-4276, approval 4278-4321, missed tracking 4323-4486, false-positive 4488-4510, confidence calibration 4512-4541
- inline `onclick/onchange`는 `showScreen`, `loadAlerts`, `ackAlert`, `loadApprovalQueue`, `approveRequest`, `rejectRequest`, `deferRequest`, `loadMissedTracking`, `filterMissedTracking`, `loadFalsePositive`, `loadConfidenceCalibration`, `runConfidenceCalibration` 등 top-level classic globals를 요구한다.
- `showScreen()` loader 호출 확인:
  - `alerts` -> `loadAlerts()`
  - `approval` -> `loadApprovalQueue()`
  - `shadow-trading` -> `loadMissedTracking()`
  - `false-positive` -> `loadFalsePositive()`
  - `confidence-cal` -> `loadConfidenceCalibration()`
  - 그 외 trading/live/positions/settings/diagnostics 등 기존 loader 호출은 `console-main.js`에 남겼다.

## 분리 후 script load order

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

`type="module"` 및 ES module import/export는 사용하지 않았다.

## 이동한 함수/영역

- `console-state.js`: `API_BASE`, DOM ref, 앱 상태, `OPS_STEPS`, `SCHEDULED_OPERATIONS`, `timeline`, `sampleLogs`.
- `console-utils.js`: theme/time/pipeline read-state helpers, Today/overview/API log/data-health rendering helpers, halt/resume UI state helper, `showToast`.
- `console-api.js`: 공통 `fetchJson`.
- `console-auth.js`: `showLogin`, MFA panel/login/logout/auth check, `loadConsoleData`, emergency halt/resume API wrapper.
- `console-navigation.js`: `showScreen`, 새 `bindNavigationEvents`.
- `screens/console-alerts.js`: `loadAlerts`, `ackAlert`.
- `screens/console-approval.js`: `loadApprovalQueue`, `approveRequest`, `rejectRequest`, `deferRequest`.
- `screens/console-missed-tracking.js`: `_missedTrackingAll`, `_missedFilter`, `getPayloadRows`, `loadMissedTracking`, `filterMissedTracking`, `renderMissedTracking`, legacy aliases `loadShadowTrading`, `loadMissedOpportunity`.
- `screens/console-false-positive.js`: `loadFalsePositive`.
- `screens/console-confidence-calibration.js`: `loadConfidenceCalibration`, `runConfidenceCalibration`.
- `console-main.js`: 나머지 diagnostics/settings/trading/live/positions/data/review/statistics/daily-plan/expert-knowledge/init 로직.

## 기존 기능 영향 범위

- HTML screen section 18개는 유지했다.
- classic script top-level `var`/`function` 전역 구조를 유지했다.
- API endpoint, inline handler, 이벤트 방식, trading/live/positions/settings/diagnostics 실행 로직은 기능 변경하지 않았다.
- `bindEvents()`의 nav/mobile 부분만 `bindNavigationEvents()` 호출로 분리했으며 동작은 동일하게 유지했다.
- `tests/e2e/status-truth.spec.cjs`는 로컬 서버 listen 없이 Playwright route fulfill로 `/console` 및 `/static/*`를 제공하도록 바꿨다. 이는 현재 샌드박스의 `127.0.0.1` listen 제한을 피하기 위한 테스트 하네스 변경이다.

## 전역 함수/window 계약 확인 결과

- 정적 확인: low-risk screen loader/action 함수는 모두 top-level `function` 선언으로 분리되어 classic script에서 `window` 접근 가능해야 한다.
- 추가 Node VM smoke 통과:
  - 11개 script를 HTML 순서대로 실행.
  - `showScreen`, `bindNavigationEvents`, `fetchJson`, `showLogin`, `checkAuth`, `loadConsoleData`, low-risk screen 함수, `engineTestRun`, `saveRiskSettings`, `liquidateAll`, `liveDecisionActivate` 등 21개 주요 함수 존재 확인.
  - `_missedTrackingAll` 전역 배열 확인.

## 테스트 결과

PASS:

- `node --check backend/static/js/console-state.js`
- `node --check backend/static/js/console-utils.js`
- `node --check backend/static/js/console-api.js`
- `node --check backend/static/js/console-auth.js`
- `node --check backend/static/js/console-navigation.js`
- `node --check backend/static/js/screens/console-alerts.js`
- `node --check backend/static/js/screens/console-approval.js`
- `node --check backend/static/js/screens/console-missed-tracking.js`
- `node --check backend/static/js/screens/console-false-positive.js`
- `node --check backend/static/js/screens/console-confidence-calibration.js`
- `node --check backend/static/js/console-main.js`
- `node --check backend/static/js/console.js`
- `node --check tests/e2e/status-truth.spec.cjs`
- `.venv/bin/python -m compileall -q backend`
- `git diff --check`
- 추가 Node VM classic-global smoke: `classic global smoke ok: 21 functions`

Playwright:

- 1차 실행 실패: 기존 test internal static server가 `listen EPERM: operation not permitted 127.0.0.1`로 실패.
- 테스트 하네스를 route fulfill 방식으로 수정 후 재실행.
- 2차 실행 실패: Chromium launch 단계에서 `FATAL:content/browser/sandbox_host_linux.cc:41 ... shutdown: Operation not permitted`로 브라우저 프로세스가 시작되지 않음.
- Firefox 대체 실행도 시도했으나 브라우저 바이너리 미설치로 실패.
- 상위 Codex 세션에서 동일 명령을 재실행해 PASS 확인:
  - `npx playwright test --config=playwright.config.cjs tests/e2e/status-truth.spec.cjs --workers=1`
  - 8 passed

따라서 CLI 내부 샌드박스에서는 브라우저 실행 단계가 막혔지만, 상위 실행 환경에서는 targeted Playwright smoke가 통과했다.

## 실행하지 않은 위험 테스트와 이유

- S1~S11 실행 버튼 클릭 금지: 엔진 실행/주문/청산/후처리 POST 가능성이 있어 지시대로 미실행.
- 주문/청산/decision activate/emergency halt/resume/settings save/API POST 클릭 금지: 운영 상태 변경 위험이 있어 미실행.
- approval approve/reject/defer 버튼 클릭 금지: 승인 상태 변경 POST라 미실행.
- 외부 LLM/KIS 호출 금지: 이번 작업은 static 구조 분리이며 외부 연동 검증 범위가 아님.
- 서버 재시작 금지: 지시대로 미실행.

## 남은 위험

- `console-utils.js`와 `console-main.js`는 아직 크다. Stage 2 범위 밖인 trading/live/positions/settings/diagnostics/daily-plan 분리는 후속 작업으로 남았다.
- legacy `console.js`는 로드되지 않지만 파일로 남아 있으므로, 다음 단계에서 혼동 방지를 위해 README/OUTBOX 또는 파일 상단 legacy 주석 보강을 검토할 수 있다.
- 기존 inline handler와 동적 HTML handler 의존성은 유지했다. 이벤트 위임 전환은 별도 Stage가 필요하다.

## 다음 추천 작업

1. Stage 3로 statistics/review/funnel/data-health 같은 중위험 이하 화면을 같은 classic script 방식으로 추가 분리한다.
2. `_settingsProfileData` 동적 onchange 접근과 `generateDailyPlan()`의 암묵적 `event` 의존성을 별도 안정화 작업으로 정리한다.
3. legacy `console.js`의 보존/삭제 정책을 정해 혼동 가능성을 줄인다.
