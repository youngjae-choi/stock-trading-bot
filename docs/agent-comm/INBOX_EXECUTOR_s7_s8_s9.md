# INBOX_EXECUTOR_s7_s8_s9 — Order Execution + Position Manager + 당일 청산

## 개요

S7, S8, S9를 한번에 구현한다.

- **S7**: `trading_signals` 테이블 `pending` 신호 → KIS 주문 발행 → `trading_orders` 저장
- **S8**: Position Manager — WS tick으로 보유 포지션 손절/익절 실시간 감시 → 매도 주문
- **S9**: 15:20 당일 청산 — 전량 시장가 매도

---

## 참조 파일 (읽기 전용)

- `backend/services/kis/domestic/service.py` — `order_cash()`, `get_balance()` 패턴
- `backend/services/engine/decision_engine.py` — `DecisionEngine` 구조, `get_today_signals()` 패턴
- `backend/services/engine/rulepack_store.py` — `get_active_rulepack_for_date()`
- `backend/services/kis/realtime_ws import realtime_ws_manager` — tick 콜백 패턴
- `backend/services/db.py` — `get_connection()` 패턴
- `backend/services/settings_store.py` — `get_setting()` 패턴
- `backend/config.py` — `settings.KIS_CANO`, `settings.KIS_ACNT_PRDT_CD`
- `backend/services/scheduler.py` — job 등록 패턴
- `backend/main.py` — router 등록 패턴

---

## 1. DB 스키마 — `trading_orders` 테이블

`backend/services/engine/order_executor.py` 에서 자동 생성:

```sql
CREATE TABLE IF NOT EXISTS trading_orders (
    id              TEXT PRIMARY KEY,
    trade_date      TEXT NOT NULL,
    signal_id       TEXT NOT NULL DEFAULT '',    -- trading_signals.id 참조
    symbol          TEXT NOT NULL,
    name            TEXT NOT NULL DEFAULT '',
    side            TEXT NOT NULL,               -- buy | sell
    order_type      TEXT NOT NULL DEFAULT 'limit', -- limit | market
    qty             INTEGER NOT NULL DEFAULT 0,
    price           REAL NOT NULL DEFAULT 0.0,
    kis_order_no    TEXT NOT NULL DEFAULT '',    -- KIS 주문번호 (odno)
    status          TEXT NOT NULL DEFAULT 'submitted', -- submitted | filled | failed | cancelled
    reason          TEXT NOT NULL DEFAULT '',    -- 청산 이유 (stop_loss|take_profit|trailing|time|eod)
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trading_orders_trade_date ON trading_orders(trade_date);
CREATE INDEX IF NOT EXISTS idx_trading_orders_symbol ON trading_orders(symbol);
```

---

## 2. S7 Order Executor — `backend/services/engine/order_executor.py` 신규

### 핵심 클래스

```python
class OrderExecutor:
    """S7: pending 신호를 주문으로 변환하고 KIS에 발행한다."""

    async def execute_signal(self, signal: dict) -> dict:
        """
        1. RulePack risk_limits 체크 (max_positions, position_size_pct)
        2. get_balance()로 예수금 조회
        3. 주문 수량 계산: floor(예수금 * position_size_pct / 100 / price)
        4. order_cash(side='buy', ...) 호출
        5. trading_orders 저장
        6. trading_signals.status → 'executed' 업데이트
        7. PositionManager에 포지션 등록
        """

    async def execute_sell(self, symbol: str, qty: int, price: float = 0, reason: str = "manual") -> dict:
        """
        매도 주문 발행 (손절/익절/청산 공통)
        price=0 이면 시장가(ord_dvsn='01'), 아니면 지정가(ord_dvsn='00')
        """

    def _check_risk_limits(self, rulepack: dict, current_position_count: int) -> tuple[bool, str]:
        """
        risk_limits.max_positions 초과 시 (False, "max_positions_exceeded") 반환
        """

    def _calc_qty(self, deposit: float, position_size_pct: float, price: float) -> int:
        """floor(deposit * position_size_pct / 100 / price), 최소 1"""

# 싱글턴
order_executor = OrderExecutor()
```

### position_size_pct 기본값
RulePack `risk_limits.position_size_pct` 없으면 `10.0` (예수금의 10%)

### 주문 실패 처리
KIS API 예외 발생 시 → `trading_orders`에 `status='failed'` 저장 후 계속 실행 (서버 종료 안 함)

---

## 3. S8 Position Manager — `backend/services/engine/position_manager.py` 신규

### 핵심 클래스

```python
class PositionManager:
    """S8: 보유 포지션의 손절/익절/트레일링/시간손절을 실시간 WS tick으로 감시한다."""

    def __init__(self):
        self._positions: dict[str, dict] = {}  # {symbol: position_dict}
        # position_dict 구조:
        # {
        #   symbol, name, qty, entry_price, entry_time,
        #   stop_loss_price,   # 진입가 * (1 - stop_loss_pct/100)
        #   take_profit_price, # 진입가 * (1 + take_profit_pct/100)
        #   trailing_active,   # bool — trailing 활성화 여부
        #   trailing_high,     # 현재까지 최고가
        # }

    def add_position(self, symbol: str, name: str, qty: int, entry_price: float, rulepack: dict) -> None:
        """주문 체결 후 포지션 등록. RulePack에서 손절/익절 조건 읽기."""

    def remove_position(self, symbol: str) -> None:
        """청산 완료 후 포지션 제거."""

    def get_positions(self) -> list[dict]:
        """현재 보유 포지션 목록 반환."""

    async def on_tick(self, tick: dict) -> None:
        """WS tick 콜백 — 손절/익절/트레일링 조건 평가"""
        # 1. 해당 symbol 포지션 없으면 return
        # 2. price 파싱
        # 3. 손절 체크: price <= stop_loss_price → execute_sell(reason='stop_loss')
        # 4. 익절 체크: price >= take_profit_price → execute_sell(reason='take_profit')
        # 5. 트레일링: price >= entry_price * 1.02 → trailing_active=True
        #              trailing_active이고 price <= trailing_high * 0.99 → execute_sell(reason='trailing')
        # 6. trailing_high 갱신

    def activate(self) -> None:
        """WS 콜백 등록"""
        realtime_ws_manager.register_tick_callback(self.on_tick)

    def deactivate(self) -> None:
        """WS 콜백 해제"""
        realtime_ws_manager.unregister_tick_callback(self.on_tick)

# 싱글턴
position_manager = PositionManager()
```

### RulePack 손절/익절 기본값 (machine_rules에 없을 때)
```python
STOP_LOSS_PCT_DEFAULT   = 1.5   # 진입가 대비 -1.5%
TAKE_PROFIT_PCT_DEFAULT = 3.0   # 진입가 대비 +3.0%
TRAILING_TRIGGER_PCT    = 2.0   # +2% 도달 시 트레일링 활성화
TRAILING_SLIP_PCT       = 1.0   # 고점 대비 -1% 시 청산
```

### 시간손절 (30분 보유 후 수익 +0.5% 미만)
`on_tick`에서 `entry_time` 기준 30분 경과 + 수익률 < 0.5% 이면 `execute_sell(reason='time_stop')`

---

## 4. S9 당일 청산 — `backend/services/engine/eod_liquidation.py` 신규

```python
async def run_eod_liquidation() -> dict:
    """15:20 KST: 보유 전 포지션을 시장가로 청산한다."""
    positions = position_manager.get_positions()
    results = []
    for pos in positions:
        result = await order_executor.execute_sell(
            symbol=pos["symbol"],
            qty=pos["qty"],
            price=0,          # 시장가
            reason="eod",
        )
        results.append(result)
    return {"liquidated": len(results), "results": results}
```

---

## 5. DecisionEngine 수정 — `_emit_signal()` 에서 S7 연동

`backend/services/engine/decision_engine.py` 수정:

`_emit_signal()` 끝에 아래 추가:
```python
# S7 즉시 실행
from .order_executor import order_executor
asyncio.create_task(order_executor.execute_signal({
    "id": signal_id,
    "symbol": symbol,
    "name": candidate.get("name", ""),
    "trigger_price": price,
    "confidence": float(candidate.get("confidence", 0.0)),
}))
```

---

## 6. DecisionEngine.activate() 수정

`activate()` 완료 후 position_manager 활성화:
```python
from .position_manager import position_manager
position_manager.activate()
```

`deactivate()` 에서:
```python
position_manager.deactivate()
```

---

## 7. API 라우트 — `backend/api/routes/orders.py` 신규

```python
router = APIRouter(prefix="/api/v1/orders", tags=["orders"])

@router.get("/today")
async def get_today_orders():
    """오늘 발행된 주문 목록"""

@router.get("/positions")
async def get_positions():
    """현재 보유 포지션 (PositionManager 인메모리)"""

@router.post("/sell")
async def manual_sell(body: SellRequest):
    """수동 매도 (테스트용) — symbol, qty, price(0=시장가)"""

@router.post("/liquidate-all")
async def liquidate_all():
    """전체 포지션 즉시 청산 (수동 S9)"""
```

---

## 8. scheduler.py 수정

```python
async def job_eod_liquidation() -> None:
    """Job S9 (15:20 KST): 당일 포지션 전량 청산"""
    logger.info("START: [Job S9] 당일 청산 (15:20 KST)")
    try:
        from .engine.eod_liquidation import run_eod_liquidation
        result = await run_eod_liquidation()
        logger.info("SUCCESS: [Job S9] 청산 완료 liquidated=%d", result.get("liquidated", 0))
    except Exception as exc:
        logger.error("FAIL: [Job S9] 청산 실패 — reason=%s", exc)
```

기존 `schedule_close_time` (기본값 `"15:20"`) job을 `job_eod_liquidation`으로 교체.

---

## 9. main.py 수정

```python
from .api.routes.orders import router as orders_router
app.include_router(orders_router)
```

---

## 완료 기준

```bash
python -m py_compile backend/services/engine/order_executor.py && echo "order_executor OK"
python -m py_compile backend/services/engine/position_manager.py && echo "position_manager OK"
python -m py_compile backend/services/engine/eod_liquidation.py && echo "eod_liquidation OK"
python -m py_compile backend/api/routes/orders.py && echo "orders_route OK"
python -m py_compile backend/services/engine/decision_engine.py && echo "decision_engine OK"
python -m py_compile backend/services/scheduler.py && echo "scheduler OK"
python -m py_compile backend/main.py && echo "main OK"
python -c "
from backend.services.engine.order_executor import order_executor
from backend.services.engine.position_manager import position_manager
from backend.services.engine.eod_liquidation import run_eod_liquidation
print('all imports OK')
"
```

OUTBOX(`docs/agent-comm/OUTBOX_EXECUTOR_s7_s8_s9.md`)에 결과 작성.
