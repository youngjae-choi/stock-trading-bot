# OUTBOX_EXECUTOR_ui_overhaul — 콘솔 UI 전면 점검 및 Statistics 페이지 추가

## 작업 결과: ✅ 완료

---

## 완료 기준 검증

```
HTML OK
Statistics 화면 [screen-statistics]: OK
Statistics 이력 테이블 [st-history-tbody]: OK
Statistics 상세 패널 [st-detail-card]: OK
LLM Provider 테이블 [llmProvidersTableBody]: OK
Funnel 후보 테이블 id [funnel-candidates-tbody]: OK
Risk 주문 테이블 id [risk-orders-tbody]: OK
Review 이력 테이블 id [review-history-tbody]: OK
S10 테스트 카드 [et-card-s10]: OK
loadDataHealth 함수 [loadDataHealth]: OK
loadFunnelData 함수 [loadFunnelData]: OK
loadStatistics 함수 [loadStatistics]: OK
loadStatisticsDetail 함수 [loadStatisticsDetail]: OK
```

---

## 변경 내역 (backend/static/console.html)

### Task 1 — Today Control 버튼 수정 ✅
- `시스템 점검` + `로그 다운로드` 버튼 2개 → `새로고침` 버튼 1개 (`onclick="loadConsoleData()"`)

### Task 2 — Data & API 화면 전면 교체 ✅
- 버튼: `데이터 재점검` → `새로고침` (`onclick="loadDataHealth()"`)
- 4개 metric 카드: PostgreSQL/Telegram 카드 제거, LLM Router/SQLite DB 카드로 교체 (id: `dh-kisRest`, `dh-kisWs`, `dh-llm`, `dh-db`)
- `데이터 품질 체크` 테이블 → `LLM Provider 상태` 테이블로 교체 (id: `llmProvidersTableBody`)
- `loadDataHealth()` 함수 추가: `/api/v1/bot/data-health` + `/api/v1/market-tone/providers` 연결
- `showScreen()` 함수에 `data` 탭 진입 시 자동 로드 추가

### Task 3 — Funnel Monitor 실 데이터 연결 ✅
- page-head에 `새로고침` 버튼 추가 (`onclick="loadFunnelData()"`)
- 4개 metric 카드에 id 추가: `funnel-total`, `funnel-layer1`, `funnel-layer2`, `funnel-candidates`
- 후보 테이블 tbody에 id 추가: `funnel-candidates-tbody`, mock 데이터 제거
- `loadFunnelData()` 함수 추가: `/api/v1/bot/overview` + `/api/v1/screening/today` 연결
- `showScreen()` 함수에 `funnel` 탭 진입 시 자동 로드 추가

### Task 4 — Execution & Risk 실 데이터 연결 ✅
- page-head에 `새로고침` 버튼 추가 (`onclick="loadExecutionRisk()"`)
- 4개 metric 카드 id 추가: `risk-pnl`, `risk-orders-count`, `risk-blocked-count`
- 주문 실행 로그 tbody id 추가: `risk-orders-tbody`, mock 3행 → placeholder로 교체
- 주문 차단 로그 카드: 3개 mock log-item → 서버 로그 안내 메시지로 교체
- `loadExecutionRisk()` 함수 추가: `/api/v1/orders/today` 연결
- `showScreen()` 함수에 `risk` 탭 진입 시 자동 로드 추가

### Task 5 — Review & Audit 실 데이터 연결 ✅
- 버튼: `AI 복기 생성` + `CSV 다운로드` → `일일 요약 생성 (S10)` + `새로고침`
- 4개 metric 카드: 룰 준수율/학습 후보 → 매매일수/총 주문수로 교체 (id: `review-pnl`, `review-winrate`, `review-trade-days`, `review-total-orders`)
- AI 복기 요약 영역: 잘된점/개선할점/놓친기회 → 가장 최근 거래일 요약/시장 톤/RulePack으로 교체
- 자동학습 Rule Suggestions 카드 → 일별 거래 이력 테이블로 교체 (id: `review-history-tbody`)
- Pattern Memory 카드 전체 제거
- `loadReviewData()`, `runDailySummary()` 함수 추가: `/api/v1/trades/history?limit=30`, `/api/v1/trades/run-summary` 연결
- `showScreen()` 함수에 `review` 탭 진입 시 자동 로드 추가

### Task 6 — Statistics 화면 신규 추가 ✅
- 사이드바 nav에 `Statistics` 버튼 추가 (`data-screen="statistics"`)
- mobile select에 `<option value="statistics">Statistics</option>` 추가
- `screen-review` 닫힘 바로 다음에 `screen-statistics` 섹션 삽입:
  - 기간 필터 버튼 (전체/이번달/지난달) + 날짜 직접 선택
  - 5개 summary metric 카드 (매매일수, 총 주문수, 수익일 비율, 누적 손익, 일 평균 손익)
  - 일별 거래 이력 테이블 (id: `st-history-tbody`) — 행 클릭 시 상세 조회
  - 상세 패널 (id: `st-detail-card`) — 주문 내역 + 매수 신호 테이블
- JS 함수 추가: `setStatsFilter()`, `filterStItems()`, `loadStatistics()`, `renderStatsSummary()`, `loadStatisticsDetail()`
- `showScreen()` 함수에 `statistics` 탭 진입 시 자동 로드 추가

### Task 7 — KIS System Test S10 추가 ✅
- S9 카드 다음에 S10 카드 삽입: "일일 요약 + DB 백업" (`onclick="engineTestRun('s10')"`)
- `STEP_URLS`에 `s10: "/api/v1/trades/run-summary"` 추가
- `engineTestClearAll()` 배열에 `"s10"` 추가

---

## 파일 라인 수 변화
- 변경 전: 3071줄
- 변경 후: 약 3,470줄 (Statistics 섹션 + JS 함수 추가)
