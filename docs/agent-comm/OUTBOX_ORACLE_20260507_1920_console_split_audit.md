# OUTBOX_ORACLE - 2026-05-07 19:20 KST - console.html 분리 사전 감사

## 감사 범위와 준수 사항

- 대상: `backend/static/console.html` 7065줄.
- 정적 읽기/분석만 수행했다.
- 수행하지 않음: 서버 재시작, git commit, S1~S11 실행, 주문/청산/decision activate/API POST 호출, 외부 LLM/KIS 호출.
- 확인한 근거:
  - `/static` mount 존재: `backend/main.py:135`
  - `/console`은 `backend/static/console.html`을 FileResponse로 반환: `backend/api/routes/console.py:32-38`
  - 현재 inline script 문법: `new Function(<script>)` 기준 OK

## console.html 라인 기준 구조

| 구역 | 라인 | 내용 |
|---|---:|---|
| head/style | 1-819 | 메타, 타이틀, 전체 CSS 변수/레이아웃/카드/테이블/반응형/배지 스타일 |
| login | 823-854 | 로그인 폼, MFA 패널 |
| header | 857-886 | 브랜드, 모바일 메뉴, theme/logout/halt 버튼 |
| sidebar/nav | 889-916 | 좌측 메뉴. 현재 nav에는 `live`, `positions`, `risk` 버튼 없음 |
| main wrapper | 918-2472 | 화면별 `<section class="screen">` 전체 |
| script 시작/전역 | 2482-2571 | DOM ref, 상태 변수, OPS_STEPS, SCHEDULED_OPERATIONS |
| navigation | 2573-2697 | `showScreen`, 화면 진입 시 data load/timer 제어 |
| utils/schedule | 2699-2869 | theme, time/date, pipeline read state helpers |
| today/overview/API logs render | 2873-3369 | Today feed, overview, data health, api logs 렌더 |
| common API/auth/control | 3370-3670 | `fetchJson`, login/MFA/auth/logout, halt/resume, console bootstrap |
| event/theme bind | 3671-3798 | form/nav/mobile/theme/halt 이벤트 바인딩 |
| diagnostics | 3799-4043 | settings map, S1~S11 상태 조회, diagnostic card/log helpers, `engineTestRun` |
| settings scheduler/guardrail | 4044-4339 | schedulerKeys, exitOverrideKeys, risk/settings 저장, guardrail |
| positions/today/account | 4344-4589 | positions timer, common DOM setters, orders/account loaders, `liquidateAll` |
| trading/live | 4590-5122 | Trading Monitor, EventSource, candidate/position render, decision activate/deactivate |
| data health/funnel helpers | 5123-5259 | data health, provider status, funnel memory/quality helpers |
| funnel/risk | 5260-5397 | funnel data, execution risk |
| review/audit/learning memory | 5398-5855 | review summary, review audit modal, S10/S11 actions |
| statistics | 5856-6042 | trade history filters/table/detail |
| daily plan | 6043-6247 | plan status/screen, advanced menu, dry-run placeholder handlers |
| data/settings test helpers | 6253-6346 | Data & API screen, profile/plan validation helper calls |
| settings profiles | 6348-6410 | risk profile pack load/render/save |
| expert knowledge PDF | 6413-6553 | PDF upload/analyze/apply/reset/history |
| expert knowledge CRUD | 6554-6680 | list, submit, approve, reject |
| DQ/alerts/approval | 6681-6801 | DQ status, alerts, approval queue actions |
| missed/fp/confidence | 6806-7024 | missed tracking merge/filter/render, false-positive, confidence calibration |
| boot/init | 7029-7063 | settings init, auth check, saved screen restore, interval, DOMContentLoaded |

## screen section 라인 기준

| screen id | 라인 | 비고 |
|---|---:|---|
| `screen-today` | 919-1045 | 기본 active |
| `screen-trading` | 1047-1150 | nav 노출 |
| `screen-rulepack` | 1152-1282 | Daily Plan |
| `screen-funnel` | 1284-1380 | Funnel Monitor |
| `screen-expert-knowledge` | 1382-1433 | Knowledge |
| `screen-alerts` | 1435-1466 | Alert Center |
| `screen-approval` | 1468-1490 | nav/mobile에서 display:none |
| `screen-shadow-trading` | 1492-1542 | Missed Entries |
| `screen-false-positive` | 1544-1566 | False Positive |
| `screen-confidence-cal` | 1568-1593 | nav/mobile에서 display:none |
| `screen-live` | 1595-1637 | 현재 nav 없음, legacy 가능성 |
| `screen-positions` | 1639-1737 | 현재 nav 없음, legacy 가능성 |
| `screen-risk` | 1739-1779 | 현재 nav 없음, legacy 가능성 |
| `screen-data` | 1781-1940 | System Status |
| `screen-review` | 1942-2034 | Trade Review |
| `screen-statistics` | 2036-2090 | Trade History |
| `screen-engine-test` | 2092-2300 | S1~S11 실행 버튼 포함, 테스트 클릭 금지 |
| `screen-settings` | 2302-2472 | Settings |

## Findings / 주의점

1. 가장 안전한 1차 분리는 CSS 추출과 "전체 script 단일 파일 추출"이다. 바로 ES module/screen module로 전환하면 inline handler와 전역 함수 의존성이 깨질 가능성이 크다.
2. 외부 자산 경로는 `/static/css/console.css`, `/static/js/...`가 맞다. FastAPI가 이미 `backend/static`을 `/static`에 mount한다. 단, 기존 `tests/e2e/status-truth.spec.cjs`는 `file://.../backend/static/console.html`을 열기 때문에 `/static/js/...` 분리 후에는 이 테스트가 그대로는 JS를 못 읽는다.
3. 첫 분리 단계에서는 `<script src="/static/js/console.js"></script>`를 body 맨 아래에 두고 `type="module"`을 쓰지 않는 것이 안전하다. `type="module"`은 top-level function을 `window`에 자동 노출하지 않는다.
4. `showScreen()`은 screen별 loader를 직접 호출한다. `boot.js` 또는 init script는 반드시 모든 screen script 로드 후 마지막에 실행해야 한다.
5. `showScreen()`은 `stopTradingMonitorStream`, `_positionsTimer`, `liveRefreshTimer`, `load*` 함수들에 의존한다. screen 파일을 나누더라도 이 함수/변수는 호출 시점 전에 전역에 있어야 한다.
6. 동적 HTML 템플릿에도 inline `onclick/onchange`가 있다. HTML 본문만 검색해서는 부족하며, JS 문자열 안 handler까지 window 노출 대상이다.
7. `_settingsProfileData`는 동적 `onchange` 문자열에서 직접 접근한다. 모듈화 시 전역 노출 또는 이벤트 위임으로 교체해야 한다.
8. `generateDailyPlan()`은 암묵적 전역 `event.target`을 사용한다. strict/module 환경에서는 깨질 수 있으므로 함수 추출 단계에서 `event` 또는 `button` 인자를 명시하도록 별도 수정이 필요하다.
9. `loadMissedTracking()` 내부에 지역 `fetchJson` 함수가 있어 전역 `fetchJson`과 이름이 겹친다. 파일 분리 시 의도치 않은 import/export 대상으로 오해하지 말 것.
10. `engineTestRun()`은 S1~S11 POST 실행 경로를 포함한다. 분리 검증에서 버튼 클릭 금지. 상태 조회용 `engineTestLoadTodayResults()`는 GET/mock 기반으로만 검증한다.
11. `liveDecisionActivate`, `liveDecisionDeactivate`, `liquidateAll`, `emergencyHalt`, `emergencyResume`, settings save, approval/alert approve류는 POST/PUT 부작용이 있다. smoke test는 route mock 또는 정적 문법 검사 중심으로 구성한다.

## 권장 분리 순서

1. Stage 0 - 기준선 고정
   - `console.html` 내부 `<script>`를 `new Function()`으로 문법 확인.
   - 화면 section start line과 inline handler 목록을 저장.
   - 기존 E2E 중 실제 POST를 수행하는 테스트는 분리 검증용으로 쓰지 않는다.

2. Stage 1 - CSS만 추출
   - `backend/static/css/console.css` 생성.
   - `<style>...</style>`을 `<link rel="stylesheet" href="/static/css/console.css">`로 교체.
   - inline `style=""`은 이 단계에서 건드리지 않는다.

3. Stage 2 - JS 전체 단일 파일 추출
   - `backend/static/js/console.js` 생성.
   - 기존 `<script>...</script>` 내용을 그대로 이동.
   - HTML 하단에 `<script src="/static/js/console.js"></script>` 추가.
   - 이 단계까지는 기능 변경 없는 no-op refactor로 봐야 한다.

4. Stage 3 - 공통 파일 분리, classic script 유지
   - script order를 고정한다.
   - `state.js` -> `utils.js` -> `api.js` -> `auth.js` -> `navigation.js` -> screen scripts -> `boot.js`
   - 아직 ES module/IIFE 금지. inline handler가 많으므로 classic global script로 유지한다.

5. Stage 4 - 낮은 위험 screen부터 분리
   - 1순위: `alerts.js`, `approval.js`, `missed.js`, `false-positive.js`, `confidence-calibration.js`
   - 2순위: `statistics.js`, `review.js`, `funnel.js`, `daily-plan.js`, `data-health.js`
   - 3순위: `settings.js`, `expert-knowledge.js`
   - 마지막: `trading-monitor.js`, `positions.js`, `live.js`, `diagnostics.js`

6. Stage 5 - inline handler 제거는 별도 작업
   - 파일 분리와 동시에 이벤트 위임/모듈화까지 하지 않는다.
   - 분리 안정화 후 `data-action` 기반 이벤트 바인딩으로 바꾸면 `window.*` 노출을 줄일 수 있다.

## 추천 파일 구조

```text
backend/static/
  console.html
  css/
    console.css
  js/
    state.js
    utils.js
    api.js
    auth.js
    navigation.js
    boot.js
    screens/
      today.js
      trading-monitor.js
      daily-plan.js
      funnel.js
      expert-knowledge.js
      alerts.js
      approval.js
      missed-tracking.js
      false-positive.js
      confidence-calibration.js
      live.js
      positions.js
      risk.js
      data-health.js
      review-audit.js
      statistics.js
      diagnostics.js
      settings.js
```

권장 HTML 로드 순서:

```html
<script src="/static/js/state.js"></script>
<script src="/static/js/utils.js"></script>
<script src="/static/js/api.js"></script>
<script src="/static/js/auth.js"></script>
<script src="/static/js/navigation.js"></script>
<script src="/static/js/screens/today.js"></script>
...
<script src="/static/js/boot.js"></script>
```

## 전역 의존성 목록

### 주요 전역 상태/상수

- API/DOM: `API_BASE`, `screens`, `navButtons`, `mobileMenu`, `loginForm`, `loginUsername`, `loginPassword`, `loginStatus`, `loginSubmitBtn`, `mfaPanel`, `mfaMethodField`, `mfaMethodSelect`, `mfaStartBtn`, `mfaSetupBox`, `mfaCodeField`, `mfaCode`, `mfaVerifyBtn`, `themeBtn`, `logoutBtn`, `haltBtn`
- Today/overview DOM refs: `engineDot`, `engineText`, `restDot`, `restStatusText`, `socketDot`, `socketStatusText`, `modeMetric`, `modeDetail`, `pnlMetric`, `pnlDetail`, `positionsMetric`, `positionsDetail`, `phaseText`, `nextJobMetric`, `nextJobText`, `lastUpdate`, `todayOpsFeed`, `funnelProgress`, `kisTokenStatus`, `kisTokenDetail`, `rulepackStatus`, `rulepackDetail`, `websocketStatus`, `websocketDetail`, `riskStatus`, `riskDetail`, `consoleFooterNote`, `apiLogsCount`, `apiLogsMetric`, `apiLogsLastUpdate`, `apiLogsMode`, `apiLogsNote`, `apiLogsTableBody`
- App state: `isHalted`, `currentUser`, `mfaState`, `overviewData`, `OPS_STEPS`, `SCHEDULED_OPERATIONS`, `timeline`, `sampleLogs`
- Timers/streams: `_positionsTimer`, `liveRefreshTimer`, `tmEventSource`, `tmRealtimeRefreshTimer`, `tmLastRealtimeRefresh`, `window._tmRefreshInterval`
- Screen state: `_raCurrentReport`, `stAllItems`, `stFilter`, `_settingsProfileData`, `_ekCurrentAnalysisId`, `_missedTrackingAll`, `_missedFilter`
- Config arrays: `schedulerKeys`, `exitOverrideKeys`

### HTML inline handler / 동적 inline handler가 요구하는 window 함수

- Navigation/common: `showScreen`
- Today/trading/positions/live: `refreshTodayControl`, `toggleDecisionEngine`, `loadTradingMonitor`, `loadAccountBalance`, `loadPositionMonitoring`, `liquidateAll`, `liveDecisionActivate`, `liveDecisionDeactivate`, `loadLiveData`, `toggleCandidateDetail`
- Daily Plan: `loadDailyPlanScreen`, `showDpContext`, `toggleDpAdvanced`, `runDailyPlanDryRun`, `manualRerunS5`, `revalidateDailyPlan`, `deactivateDailyPlan`, `rollbackDailyPlan`, `toggleDpJson`
- Funnel/data/risk: `loadFunnelData`, `loadExecutionRisk`, `loadDataAndApi`, `loadDataApiLogs`
- Expert Knowledge: `ekUploadPdf`, `ekApplyStrategy`, `ekReset`, `approveKnowledge`, `rejectKnowledge`
- Alerts/approval/missed/fp/calibration: `loadAlerts`, `ackAlert`, `loadApprovalQueue`, `approveRequest`, `rejectRequest`, `deferRequest`, `loadMissedTracking`, `filterMissedTracking`, `loadFalsePositive`, `loadConfidenceCalibration`, `runConfidenceCalibration`
- Review/statistics: `loadReviewByDate`, `loadReviewAuditScreen`, `runReviewAudit`, `openReviewDetailModal`, `closeReviewDetailModal`, `loadAllOrders`, `setStatsFilter`, `loadStatisticsDetail`
- Diagnostics/settings: `engineTestClearAll`, `engineTestLoadLogs`, `engineTestRun`, `engineTestClearLog`, `saveRiskSettings`, `saveRiskProfilePack`, `saveSchedulerSetting`, `saveExitOverrideSetting`, `saveGuardrail`
- Dynamic onchange variable access: `_settingsProfileData`

## Executor 작업 지시 초안

1. 수정 전 `backend/static/console.html`의 `<style>`, `<script>`, screen section line map을 재확인한다.
2. 1차 PR/작업은 CSS 추출 + 전체 JS 단일 파일 추출까지만 한다. screen별 JS 분리는 별도 후속 작업으로 남긴다.
3. `type="module"`을 쓰지 않는다. classic script로 기존 전역 함수 동작을 보존한다.
4. `/static/...` 경로를 사용한다. 백엔드 라우트 추가는 필요 없다.
5. `console.html`에는 링크/script 태그와 기존 HTML 구조만 남긴다. HTML section 자체 이동은 Stage 2까지 금지한다.
6. 함수 본문 수정, 이벤트 방식 변경, API endpoint 변경, inline style 정리는 이번 no-op 분리 범위에서 제외한다.
7. 분리 후 `window`에서 inline handler 함수가 보이는지 브라우저/Playwright에서 확인한다.
8. S1~S11 버튼, `liquidateAll`, `liveDecisionActivate`, emergency halt/resume, settings save류 POST 버튼은 수동/자동 테스트에서 클릭하지 않는다.

## 테스트 계획

### 정적 검증

1. HTML shell 검증
   - `console.html`에 `<link rel="stylesheet" href="/static/css/console.css">` 포함.
   - script src들이 의도한 순서로 포함.
   - 기존 screen id 18개가 모두 남아 있음.

2. JS 문법 검증
   - 각 JS 파일을 `node --check`로 확인.
   - classic browser script라 Node에서 `document/window` 참조 실행은 하지 말고 문법만 확인.

3. handler 누락 검증
   - `onclick|onchange` 문자열에서 호출되는 함수명이 `window`에 존재하는지 Playwright에서 검사.
   - `_settingsProfileData`도 window 접근 가능해야 한다.

### Playwright smoke 권장

기존 서버가 이미 떠 있는 경우에만 사용한다. 서버 재시작 금지 상황에서는 `file://` 테스트 대신 `/console` 접근 테스트 또는 Playwright route mock 기반 테스트를 사용한다.

1. `/console` 진입
   - 로그인 화면 제목 표시.
   - CSS 적용 확인: `.app`, `.sidebar`, `.screen` computed style이 빈 값이 아님.
   - console error에 `Failed to load resource /static/...`가 없어야 함.

2. 인증 우회/mock smoke
   - `GET /api/v1/auth/me`를 mock 성공으로 처리하거나 기존 로그인 계정 사용.
   - Today's, Trading Monitor, Daily Plan, Funnel Monitor, Knowledge, Alert Center, Missed Entries, False Positive, Trade Review, Trade History, System Status, System Diagnostics, Settings 화면으로 이동.
   - 화면 전환 후 `.screen.active` id가 기대값인지 확인.

3. POST 금지 화면 검증
   - Diagnostics는 `engineTestLoadTodayResults()`만 mock GET으로 확인하고 `engineTestRun()` 버튼은 클릭하지 않는다.
   - Positions/Live/Trading에서 청산/활성화 버튼 클릭 금지.
   - Settings 저장 버튼 클릭 금지.

4. no-op refactor 기준
   - 분리 전후 `/console`의 visible text 주요 heading 목록 동일.
   - nav button 수와 `data-screen` 값 동일.
   - screen id 목록 동일.
   - inline handler 함수 목록 동일.
   - 초기 load에서 ReferenceError/TypeError 없음.

### 기존 테스트 조정 필요

- `tests/e2e/status-truth.spec.cjs`는 현재 `file://`로 HTML을 열고 window.fetch를 mock한다. `/static/js/...` 분리 후에는 file URL에서 외부 JS/CSS가 로드되지 않을 수 있다.
- 이 테스트는 다음 중 하나로 조정해야 한다.
  - 이미 실행 중인 `BACKEND_URL/console`을 사용하고 API를 `page.route('**/api/v1/**')`로 mock.
  - 또는 테스트 전용 static server/fixture로 `/static/...` 요청을 처리.
- `tests/e2e/console-smoke.spec.cjs`는 halt API POST를 포함한다. console split no-op 검증용으로는 부적절하므로 별도 non-mutating smoke spec을 추가하는 편이 안전하다.
