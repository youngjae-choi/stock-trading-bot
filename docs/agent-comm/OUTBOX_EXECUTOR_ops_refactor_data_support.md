# OUTBOX_EXECUTOR_ops_refactor_data_support

## 작업일
- 2026-05-05

## 역할
- Executor(Codex)

## 변경 파일
- `backend/services/engine/order_executor.py`
- `backend/api/routes/orders.py`
- `backend/api/routes/account.py`
- `backend/api/routes/trading_monitor.py`

## 작업 결과

### 1. 최근 주문 API 추가
- `order_executor.get_recent_orders(limit: int = 5)` 추가.
- `limit`은 1~100 범위로 방어 처리.
- `trading_orders.created_at DESC` 기준으로 최신 주문 조회.
- `_ensure_orders_table()` 재사용 및 `created_at` 인덱스 추가.
- `GET /api/v1/orders/recent?limit=5` 추가.
- 응답 형식:
  - `ok`
  - `payload.orders`
  - `payload.count`
  - `payload.limit`
- START/SUCCESS/FAIL 로그 추가.

### 2. 계좌 payload 보강
- `_build_balance_payload()`에 `buyable_cash`, `available_cash` 추가.
- KIS `output2` 후보 필드 fallback 순서:
  - `nass_amt`
  - `ord_psbl_cash`
  - `dnca_tot_amt`
  - 최종 fallback: 기존 `deposit`
- 기존 필드 유지:
  - `deposit`
  - `total_eval`
  - `purchase_total`
  - `pnl_total`
  - `positions`
- position 항목에 `purchase_amount` 추가.
- `purchase_amount`는 KIS 원본 후보 `pchs_amt`, `evlu_amt`를 우선 확인하고, 값이 없으면 `avg_price * qty`로 계산.

### 3. Trading Monitor positions 보강
- `GET /api/v1/trading-monitor/positions` 각 position에 `purchase_amount` 추가.
- fallback 계산은 `entry_price * qty`.
- 가격/금액 필드는 숫자 타입으로 유지.
- 기존 응답 구조 `{ok, payload: {positions, count}}` 유지.
- START/SUCCESS 로그 추가.
- `trading_orders` 테이블이 아직 생성되지 않은 초기 상태에서도 `_latest_submitted_orders()`가 빈 dict로 동작하도록 방어.

### 4. policy-summary API 추가
- `GET /api/v1/trading-monitor/policy-summary` 추가.
- 오늘 데이터 소스:
  - `market_tone_results`
  - `hybrid_screening_results`
  - `daily_trading_plans`
  - S4가 생성한 active `rulepacks.machine_rules.entry_rules`
- 테이블 없음/데이터 없음/파싱 실패 시 500 대신 `ok: true`와 보수적 fallback payload 반환.
- 자연어 필드 추가:
  - `buy_condition_text`
  - `sell_condition_text`
  - `cash_usage_text`
  - `market_tone.cash_usage_hint`
- Settings 값을 직접 읽지 않고 오늘 AI 산출물과 Daily Plan 중심으로 구성.

## 검증 결과

### py_compile
명령:
```bash
.venv/bin/python -m py_compile backend/api/routes/orders.py backend/api/routes/account.py backend/api/routes/trading_monitor.py backend/services/engine/order_executor.py
```

결과:
- 통과

### 직접 호출 검증
서버 프로세스 확인 결과, 실행 중인 uvicorn/gunicorn/FastAPI 서버를 찾지 못했다.
따라서 인증 쿠키 기반 HTTP 호출은 수행하지 못했고, 외부 KIS 호출이 필요 없는 route 함수를 직접 호출했다.

명령:
```bash
.venv/bin/python - <<'PY'
import asyncio
from backend.api.routes.orders import get_recent_orders_api
from backend.api.routes.trading_monitor import get_policy_summary

async def main():
    recent = await get_recent_orders_api(5)
    policy = get_policy_summary()
    print('recent_ok=', recent.get('ok'), 'count=', recent.get('payload', {}).get('count'), 'limit=', recent.get('payload', {}).get('limit'))
    print('policy_ok=', policy.get('ok'), 'status=', policy.get('payload', {}).get('daily_plan', {}).get('status'))

asyncio.run(main())
PY
```

결과:
```text
recent_ok= True count= 5 limit= 5
policy_ok= True status= none
```

### API 확인 상태
- `GET /api/v1/orders/recent?limit=5`: route 직접 호출 성공.
- `GET /api/v1/trading-monitor/policy-summary`: route 직접 호출 성공.
- `GET /api/v1/account/balance`: 확인 필요. KIS 설정/인증 쿠키/서버 실행 필요.
- `GET /api/v1/trading-monitor/positions`: 확인 필요. KIS 잔고 조회/인증 쿠키/서버 실행 필요.

## 완료 체크리스트
- [x] 최근 주문 API 추가
- [x] 계좌 `buyable_cash`/`purchase_amount` 보강
- [x] Trading Monitor position `purchase_amount` 보강
- [x] policy-summary API 추가
- [x] py_compile 통과
- [x] 가능한 API 호출 검증 기록

## 주의 사항
- git commit은 수행하지 않았다.
- `backend/static/console.html`은 수정하지 않았다. 현재 워크트리에는 해당 파일 변경이 이미 존재하지만 이번 Executor 작업 범위에서는 건드리지 않았다.
- 실제 서버 + 인증 쿠키 + KIS 연동 환경에서 `account/balance`, `trading-monitor/positions` HTTP 응답 최종 확인이 필요하다.
