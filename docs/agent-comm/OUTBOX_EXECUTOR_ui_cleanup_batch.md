# OUTBOX_EXECUTOR_ui_cleanup_batch

## 결과 요약

`backend/static/console.html` 에서 "RulePack 생성" 관련 구시대 문구를 모두 제거하고 Daily Trading Plan 중심으로 UI를 정리 완료.

## 완료 체크리스트

- [x] 변경 1 — 문구 교체
  - brand-sub: `AI RulePack 기반 자동매매 운영 관제` → `AI 기반 단타 자동매매 운영 관제`
  - modeDetail 초기값 + JS 할당: `RulePack 적용 완료` → `Daily Plan 활성`
  - scheduleItems 배열: `"RulePack 생성"` → `"S5 Daily Plan 자동 생성"`
  - kisTokenDetail 초기값: `RulePack 적용 상태` → `Auto Engine 상태`
  - Data&API RulePack h4: `<h4>RulePack</h4>` → `<h4>Rule Composition</h4>`
  - rulepackDetail 초기값: `오늘 활성 RulePack` → `오늘 활성 Rule Composition`
  - Review&Audit page-desc: RulePack 반영 문구 → Learning Memory 저장 문구
  - review h4: `<h4>RulePack</h4>` → `<h4>Daily Plan</h4>`
  - S5 테스트 카드 설명: `LLM → daily_trading_plan` → `Scheduler → daily_trading_plans (자동 파이프라인)`
  - Settings 포지션별 청산 안내: `RulePack 값` → `Risk Profile 값`
  - Settings 리스크 안내: `RulePack의 위험 한도` → `Risk Profile Pack의 위험 한도`

- [x] 변경 2 — 버튼 교체
  - Daily Plan 화면 상단 버튼을 `새로고침` + `Context 보기` + `고급 작업 ▾` 드롭다운으로 교체
  - JS 함수 추가: `toggleDpAdvanced`, `showDpContext`, `runDailyPlanDryRun`, `manualRerunS5`, `revalidateDailyPlan`, `deactivateDailyPlan`, `rollbackDailyPlan` (Phase 2 alert 스텁)
  - 드롭다운 외부 클릭 닫기 이벤트 리스너 추가

- [x] 변경 3 — Daily Plan 상태 색상 뱃지
  - `loadDailyPlanScreen()` 내 `dp-plan-status`를 span 뱃지로 변경 (statusColors/statusLabel 맵 포함)
  - `dp-created-at`을 `생성: {creationMode} · {createdBy}` 형식으로 변경

- [x] 변경 4 — KIS Test S5-V 카드 추가
  - S5 카드 이후 S5-V 카드 삽입 (Daily Plan Validation, 08:50 KST)
  - S5 테스트 버튼 문구: `Daily Plan 생성 실행` → `S5 Daily Plan 생성 테스트`

- [x] 변경 5 — Settings 스케줄러 확장
  - `S5 RulePack` → `S5 Daily Plan 자동 생성`
  - 신규 항목 추가: `schedule_s5v_time` (08:50), `schedule_s5a_time` (08:55), `schedule_s10_time` (16:00), `schedule_s11_time` (16:30)
  - 기존 `schedule_close_time`, `schedule_backup_time`, `schedule_usmarket_time` 유지

- [x] 변경 6 — S5 API endpoint 수정
  - `"/api/v1/rulepack-gen/run"` → `"/api/v1/daily-plan/generate"`

- [x] 변경 7 — bootstrap 호출 정리
  - `rulepackBadge` 등 4개 HTML 요소 부재 확인 → bootstrap 호출 블록만 제거
  - `fetchJson("/api/v1/bot/rulepack/today")` 및 `rulepackResult` 처리 블록 제거
  - `loadConsoleData()` results 인덱스 조정 (dataHealth: results[2] → results[1])
  - 사용 안 하는 JS 변수 4개(`rulepackBadge`, `rulepackSummary`, `rulepackChanges`, `rulepackJson`) var 선언 제거
  - `renderRulepack()` 함수 보존 (rulepackStatus/rulepackDetail 요소는 여전히 존재하여 renderOverview에서 사용)

## 검증 결과

1. `grep -n "RulePack 생성\|rulepack-gen"` → **0건** ✓
2. `grep -n "schedule_s5_time"` → `"S5 Daily Plan 자동 생성"` 포함 확인 ✓
3. JS 문법 검사 (`node -e ...`) → **JS syntax OK** ✓

## 특이사항

- `generateDailyPlan()` 함수는 KIS System Test S5 버튼에서 여전히 호출되므로 삭제하지 않음.
- `renderRulepack()` 내부에서 참조하는 `rulepackBadge` 등은 null-safe 조건문(`if (rulepackBadge)`)으로 감싸져 있으므로 런타임 오류 없음.
- 고급 작업 드롭다운 함수들은 Phase 2 스텁(alert)으로 구현.
