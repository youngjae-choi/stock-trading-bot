# OUTBOX_EXECUTOR_design_v2_ui

## 결과: 완료

모든 13개 검증 항목 통과. JS 문법 오류 없음.

---

## 수행한 작업 목록

### HTML 변경

1. **API Logs 제거** — `data-screen="api-logs"` nav 버튼 이미 제거됨 확인, `screen-api-logs` 섹션 이미 없음 확인.

2. **Data & API 화면** — Rule System 카드 추가 (`da-rule-system`, `da-base-id`, `da-profile-id`, `da-plan-id`, `da-assignments-n`). Telegram 상태 카드 추가 (`da-telegram-status`, `da-telegram-detail`). API 호출 로그 테이블 추가 (`da-api-logs-tbody`). 새로고침 버튼을 `loadDataAndApi()`로 변경.

3. **Review & Audit 화면** — Risk Profile별 성과 카드 4개 추가 (`review-pnl-low`, `review-pnl-mid`, `review-pnl-high`, `review-pnl-spike`, `review-cnt-*`).

4. **KIS System Test 화면** — S5 카드 제목 "RulePack 자동 생성" → "Daily Trading Plan 생성". S5/S6/S8 설명 텍스트 갱신. S5 버튼 → "Daily Plan 생성 실행" (`generateDailyPlan()`). 추가 테스트 버튼 3개 삽입 (Risk Profile Pack 검증, Daily Plan 검증, Rule Composition 미리보기).

5. **Settings 화면** — `override_take_profit_rate` 항목을 `disabled: true` + "사용 안 함" 표시로 변경. Default Exit Policy 카드 추가. Risk Profile Pack 관리 테이블 추가 (`settings-profiles-tbody`, `settings-profile-ver`).

6. **Today Control / Funnel 화면** — 이전 작업에서 이미 완료된 항목들 확인 (tc-* 카드, tc-theme-spike-count, fn-*-count 등).

### JS 추가/수정

7. **`loadTradingMonitor()`** — 전면 교체. 계좌 정보 + 오늘 적용 정책(Base/Pack/Plan) 로드. `loadTradingCandidates()` + `loadTradingPositions()` 호출.

8. **신규 함수** — `loadTradingCandidates()`, `renderCandidateRow()`, `toggleCandidateDetail()`, `loadTradingPositions()`, `renderPositionRow()`.

9. **`loadTodayPlanStatus()`** — `/api/v1/daily-plan/today`, `/api/v1/rule/base`, `/api/v1/rule/profiles` 호출해 Today Control 카드 갱신.

10. **`loadDailyPlanScreen()`** — Daily Plan + Risk Profile Pack 전체 화면 렌더링.

11. **`generateDailyPlan()`**, **`toggleDpJson()`** — Daily Plan 생성 및 JSON 토글.

12. **`loadDataAndApi()`** — 기존 `loadDataHealth()` + Rule System + Telegram + API 로그 통합 로드.

13. **`loadDataApiLogs()`** — `/api/v1/logs/api` 호출해 당일 로그 테이블 렌더링.

14. **`testRiskProfilePack()`**, **`testDailyPlanValidate()`**, **`testRuleComposition()`** — KIS System Test 추가 버튼 JS.

15. **`loadSettingsProfiles()`**, **`renderSettingsProfilesTable()`**, **`saveRiskProfilePack()`** — Risk Profile Pack 편집 UI.

16. **`showScreen()`** 수정 — `today` → `loadTodayPlanStatus()`, `data` → `loadDataAndApi()`, `rulepack` → `loadDailyPlanScreen()` 추가.

17. **`loadFunnelData()`** — Daily Plan 조회해 `fn-low/mid/high/spike-count` 갱신 코드 추가.

18. **`renderOrdersTable()`** — Risk Profile + 청산 사유 컬럼 추가 (colspan 7→9).

19. **`initSettingsUI()`** — `loadSettingsProfiles()` 호출 추가.

---

## 검증 결과

```
OK: api-logs nav removed
OK: api-logs screen removed
OK: renderCandidateRow
OK: renderPositionRow
OK: toggleCandidateDetail
OK: da-rule-system
OK: da-api-logs-tbody
OK: settings-profiles-tbody
OK: loadTodayPlanStatus
OK: loadDailyPlanScreen
OK: saveRiskProfilePack
OK: fn-low-count
OK: tc-theme-spike-count
PASS: JS syntax ok
```

---

## 파일

- 수정 파일: `backend/static/console.html` (3944줄 → 4563줄)
