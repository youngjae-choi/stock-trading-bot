# OUTBOX_EXECUTOR_ui_restructure_stage1

## 처리 상태

완료.

## 변경 파일

- `backend/static/console.html`
- `docs/agent-comm/OUTBOX_EXECUTOR_ui_restructure_stage1.md`

## 구현 요약

1. 파란색 백엔드 상태 배너 제거
   - `apiStateBanner` HTML 제거
   - `.api-banner` CSS 전체 제거
   - `apiStateBanner` JS 변수, `setApiBanner()` 함수, 호출부 제거

2. 메뉴 구조 변경
   - 사이드바와 모바일 메뉴에 `Trading Monitor` 추가
   - 메뉴에서 `Live Decisions`, `Positions & Exit`, `Execution & Risk` 제거
   - 기존 `screen-live`, `screen-positions`, `screen-risk` 섹션은 삭제하지 않음

3. Trading Monitor 신규 화면 추가
   - `screen-today` 뒤, `screen-rulepack` 앞에 `screen-trading` 추가
   - `매수 대기` 탭: Decision Engine 상태와 오늘 매수 신호 표시
   - `보유 종목` 탭: 계좌 정보, 보유 종목, 포지션 감시, 주문내역 표시

4. Funnel Monitor 문구 수정
   - 고정 숫자 표현을 제거하고, 매일 달라지는 숫자임을 안내하도록 변경

5. JS 연결
   - `showTradingTab(tab)` 추가
   - `loadTradingMonitor()` 추가
   - `showScreen("trading")` 진입 시 `loadTradingMonitor()` 호출
   - `loadAccountBalance()`, `loadPositionMonitoring()`, `loadTodayOrders()`가 기존 `positions-*`와 신규 `tm-*` 요소를 함께 갱신하도록 수정
   - Decision Engine 수동 활성화/비활성화 후 Trading Monitor도 함께 갱신

## 검증 결과

### 지시서 완료 기준 검사

```text
Trading Monitor screen exists: OK
Trading Monitor in nav: OK
Execution Risk NOT in nav: OK
apiStateBanner removed: OK
tm-signals-tbody exists: OK
tm-monitor-tbody exists: OK
showTradingTab function: OK
loadTradingMonitor function: OK
Funnel desc fixed: OK
```

### 추가 정적 검증

```text
inline script syntax: OK
```

## 미실행 / 확인 필요

- 실제 브라우저 E2E는 실행하지 못함.
- 사유: 현재 샌드박스 환경에서 `uvicorn backend.main:app` 실행 시 `127.0.0.1:8000`, `127.0.0.1:8001` 모두 바인딩 실패.
- 백엔드 서버가 정상 기동되는 로컬 환경에서 Trading Monitor 탭 전환, 매수 대기 데이터 로드, 보유 종목 데이터 로드를 브라우저로 최종 확인 필요.

## 잔여 리스크

- `backend/static/console.html`은 작업 전부터 다른 변경사항이 많은 dirty 상태였음. 이번 작업은 지시 범위인 UI 1단계 구조 변경에 필요한 부분만 수정함.
- 신규 Trading Monitor는 기존 API 함수와 endpoint를 재사용하므로, 실제 표시 품질은 `/api/v1/decision/*`, `/api/v1/account/balance`, `/api/v1/orders/*` 응답 형태에 의존함.
