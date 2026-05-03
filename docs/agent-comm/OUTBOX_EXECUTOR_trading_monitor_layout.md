# OUTBOX_EXECUTOR_trading_monitor_layout

## 처리 상태

완료.

## 변경 파일

- `backend/static/console.html`

## 구현 요약

- `screen-trading` 탭 기반 UI를 제거하고, 상단 계좌 정보 + RulePack 조건 / 하단 매수 후보 + 보유 포지션 모니터링 2열 레이아웃으로 교체했다.
- `loadTradingMonitor()`가 Decision Engine 상태, 오늘 매수 신호, 오늘 RulePack 조건, 계좌/포지션/주문 데이터를 함께 갱신하도록 수정했다.
- `showTradingTab()` 함수와 Trading Monitor 탭 버튼 참조를 제거했다.
- `loadAccountBalance()`에서 `tm-holdings-count`와 `tm-pnl-today`를 갱신하도록 추가했다.
- 새 Trading Monitor의 포지션/주문 테이블 컬럼 수에 맞게 `loadPositionMonitoring()`과 `loadTodayOrders()`의 Trading Monitor 렌더링을 기존 화면 렌더링과 분리했다.

## 검증 결과

```bash
grep -c "trading-tab-btn" backend/static/console.html
# 0
```

```bash
python3 - <<'PY'
content = open('backend/static/console.html').read()
checks = [
  ('tm-account-no', 'tm-account-no'),
  ('tm-buy-conditions', 'tm-buy-conditions'),
  ('tm-risk-conditions', 'tm-risk-conditions'),
  ('tm-engine-active', 'tm-engine-active'),
  ('tm-signals-tbody', 'tm-signals-tbody'),
  ('tm-monitor-tbody', 'tm-monitor-tbody'),
  ('tm-holdings-tbody', 'tm-holdings-tbody'),
  ('tm-orders-tbody', 'tm-orders-tbody'),
]
for name, pattern in checks:
  print(f'{name}: {"OK" if pattern in content else "MISSING"}')
PY
# tm-account-no: OK
# tm-buy-conditions: OK
# tm-risk-conditions: OK
# tm-engine-active: OK
# tm-signals-tbody: OK
# tm-monitor-tbody: OK
# tm-holdings-tbody: OK
# tm-orders-tbody: OK
```

```bash
python3 - <<'PY'
content = open('backend/static/console.html').read()
print('showTradingTab removed:', 'showTradingTab' not in content)
PY
# showTradingTab removed: True
```

```bash
node -e "const fs=require('fs'); const html=fs.readFileSync('backend/static/console.html','utf8'); const scripts=[...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/gi)].map(m=>m[1]); for (const [i,s] of scripts.entries()) { new Function(s); console.log('script '+(i+1)+': OK'); }"
# script 1: OK
```

```bash
git diff --check -- backend/static/console.html docs/agent-comm/OUTBOX_EXECUTOR_trading_monitor_layout.md
# FAIL: 작업 시작 전부터 같은 파일 diff에 포함된 선행 변경 구간에서 trailing whitespace 다수 감지
```

## 잔여 리스크 / 확인 필요

- 브라우저 수동 확인과 실제 API 응답 기반 화면 확인은 수행하지 못했다.
- 작업 시작 시 이미 `backend/static/console.html`을 포함한 다수 파일에 선행 변경이 있었다. 이번 작업은 요청 범위인 Trading Monitor 레이아웃과 관련 JS만 수정했다.
