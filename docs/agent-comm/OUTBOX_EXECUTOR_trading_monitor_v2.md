# OUTBOX_EXECUTOR_trading_monitor_v2 — Trading Monitor 전면 재설계 결과

## 작업 상태

- 코드 구현: 완료
- 정적 완료 기준: 통과
- JS 문법 검사: 통과
- Playwright E2E: 환경 권한 문제로 실패

## 변경 파일

- `backend/static/console.html`
- `docs/agent-comm/OUTBOX_EXECUTOR_trading_monitor_v2.md`

## 구현 요약

### Task 1 — `screen-trading` 교체

- Trading Monitor 화면을 계좌 정보, 오늘 매매 조건, 매수 종목 모니터링, 매도 종목 모니터링 구조로 재구성했다.
- 기존 Trading Monitor 내부의 Decision Engine 상세 카드, 오늘 매수 신호 테이블, 실시간 포지션 감시 테이블, KIS 보유종목 테이블을 제거했다.
- 상단 `page-head` 우측에 Decision Engine 토글(`#tm-de-toggle`)과 새로고침 버튼을 배치했다.

### Task 2 — JS 함수 교체/추가

- `_tmApproachBar()`, `_buyColor()`, `_sellColor()`를 추가했다.
- `loadTradingMonitor()`를 교체해 다음 순서로 갱신한다.
  - Decision Engine 상태
  - 오늘 RulePack 조건
  - S4 스크리닝 후보 매수 접근률
  - 계좌 정보와 보유 포지션 매도 접근률
- `toggleDecisionEngine()`을 추가했다.
- `showScreen()`에 Trading Monitor 진입 시 10초 자동갱신 카운터를 시작하고, 다른 화면 이동 시 `_tmRefreshInterval`을 정리하도록 추가했다.

### Task 3 — 오늘 주문내역 이동

- `#today-orders-card`를 Today Control 하단에 추가했다.
- 기존 `loadTodayOrders()`가 `#tm-orders-tbody`를 갱신하도록 연결했다.
- Today Control 진입 및 `loadConsoleData()` 실행 시 오늘 주문내역도 갱신되도록 보강했다.

### Task 4 — 탭 관련 제거

- `showTradingTab` 정의 없음 확인.
- `trading-tab-btn`, `trading-tab-buy`, `trading-tab-sell` 참조 없음 확인.
- 제거된 Trading Monitor 테이블의 죽은 JS 참조(`#tm-monitor-tbody`, `#tm-holdings-tbody`)도 정리했다.

## 검증 결과

### INBOX 완료 기준

```text
tm-buy-list exists: OK
tm-sell-list exists: OK
tm-de-toggle exists: OK
tm-buy-conditions exists: OK
tm-risk-conditions exists: OK
_tmApproachBar exists: OK
loadTradingMonitor exists: OK
toggleDecisionEngine exists: OK
_tmRefreshInterval exists: OK
tab buttons removed: OK
showTradingTab removed: OK
today-orders-card in screen-today: OK
```

### 추가 검증

- `node --check /tmp/console-script.js`: 통과
- `rg "showTradingTab|trading-tab-btn|trading-tab-buy|trading-tab-sell|tm-engine-active|tm-engine-ws|tm-signals-tbody|tm-monitor-tbody|tm-holdings-tbody" backend/static/console.html`: 매칭 없음

### E2E 결과

`npm run test:e2e`를 실행했으나 실패했다.

- 실패 원인 1: Playwright request가 `127.0.0.1:8000` 접속 시 `connect EPERM` 발생
- 실패 원인 2: Chromium 실행 중 `sandbox_host_linux.cc:41 ... Operation not permitted` 발생
- 로그 위치:
  - `logs/oracle-playwright-setup-try2-summary.txt`
  - `logs/oracle-playwright-setup-try2-test.log`

이번 실패는 수정한 HTML/JS 문법 오류가 아니라 현재 실행 환경의 로컬 네트워크/브라우저 sandbox 권한 문제로 판단된다.

## 잔여 확인 필요

- 실제 브라우저에서 Trading Monitor 화면 진입 후 10초 자동갱신 카운터 동작 확인 필요
- 백엔드 실행 환경에서 `/api/v1/decision/status`, `/api/v1/bot/rulepack/today`, `/api/v1/screening/today`, `/api/v1/account/balance`, `/api/v1/orders/today` 응답 형태 최종 확인 필요
