# INBOX_EXECUTOR_position_restore

## 역할
너는 Executor(Codex)다. S9 당일 청산이 실제로 동작하도록 포지션 복원 로직을 안정화한다.
완료 후 `docs/agent-comm/OUTBOX_EXECUTOR_position_restore.md`에 결과를 작성하라.

수정 대상:
- `backend/services/engine/decision_engine.py`
- `backend/services/engine/eod_liquidation.py`
- `backend/services/engine/position_manager.py`

---

## 배경

단타봇은 15:20에 S9(eod_liquidation)이 전량 시장가 청산을 실행한다.
그런데 실제로 청산 대상이 0건이 되는 이유:

1. `position_manager._positions`는 인메모리 dict
2. 서버 재시작 시 초기화됨
3. `_restore_positions_from_db()`가 있지만 **`_candidates`가 비어 있으면 복원 안 됨**
   - `activate()`에서 S4 스크리닝 결과 없으면 `_candidates = {}` → 복원 호출 자체가 `candidate_symbols=[]`로 통과됨
4. S9는 `position_manager.get_positions()`를 호출 → 빈 리스트 → 청산 0건

---

## 작업 1 — `_restore_positions_from_db()` 개선: candidates 독립적으로 복원

`backend/services/engine/decision_engine.py`의 `_restore_positions_from_db()` 함수를 수정한다.

**현재**: `candidate_symbols` 리스트가 있어야만 복원
**목표**: `candidate_symbols`가 비어 있어도 오늘 날짜의 trading_orders(buy, submitted/filled)를 기준으로 복원

```python
def _restore_positions_from_db(trade_date: str, candidate_symbols: list[str]) -> None:
    """서버 재시작 후 position_stop_states에서 오늘 포지션을 복원한다."""
    try:
        with get_connection() as conn:
            # candidate_symbols가 있으면 그것만, 없으면 오늘 buy 주문 전체를 대상으로
            if candidate_symbols:
                placeholders = ",".join("?" for _ in candidate_symbols)
                symbol_filter = f"AND o.symbol IN ({placeholders})"
                params_symbols = candidate_symbols
            else:
                symbol_filter = ""
                params_symbols = []

            rows = conn.execute(
                f"""
                SELECT ps.*, o.qty
                FROM position_stop_states ps
                JOIN (
                    SELECT symbol, qty, MAX(created_at) AS latest_created_at
                    FROM trading_orders
                    WHERE trade_date = ?
                      AND status IN ('submitted', 'filled')
                      AND side = 'buy'
                      {symbol_filter}
                    GROUP BY symbol
                ) o ON o.symbol = ps.symbol_code
                JOIN (
                    SELECT symbol_code, MAX(last_updated_at) AS latest_updated_at
                    FROM position_stop_states
                    WHERE date(last_updated_at) = ?
                    GROUP BY symbol_code
                ) latest_stop
                  ON latest_stop.symbol_code = ps.symbol_code
                 AND latest_stop.latest_updated_at = ps.last_updated_at
                """,
                [trade_date] + params_symbols + [trade_date],
            ).fetchall()
    except Exception as exc:
        logger.warning("WARN: [S6] 포지션 복원 쿼리 실패 error=%s", exc)
        return

    from .position_manager import position_manager

    restored = 0
    for row in rows:
        data = dict(row)
        symbol = str(data.get("symbol_code") or "")
        qty = int(data.get("qty") or 0)
        entry_price = float(data.get("entry_price") or 0)
        if not symbol or qty <= 0 or entry_price <= 0:
            continue
        position_manager.add_position(
            symbol=symbol,
            qty=qty,
            entry_price=entry_price,
            rule={"initial_stop_loss": float(data.get("stop_loss_rate") or 0.02),
                  "trailing_activate_profit": float(data.get("trailing_activate_profit") or 0.02),
                  "trailing_stop_rate": float(data.get("trailing_stop_rate") or 0.01),
                  "max_holding_minutes": int(data.get("max_holding_minutes") or 180),
                  "force_exit_time": str(data.get("force_exit_time") or "15:20:00")},
        )
        restored += 1
    logger.info("INFO: [S6] 포지션 복원 완료 restored=%d trade_date=%s", restored, trade_date)
```

---

## 작업 2 — `run_eod_liquidation()` 개선: 인메모리 없으면 DB에서 직접 청산

`backend/services/engine/eod_liquidation.py`를 수정한다.

**현재**: `position_manager.get_positions()`만 보고 청산
**목표**: 인메모리 포지션이 0이면 DB에서 오늘 미청산 주문을 직접 조회해 청산

```python
"""S9 end-of-day liquidation service."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection
from .order_executor import order_executor
from .position_manager import position_manager

logger = logging.getLogger("EODLiquidation")


def _today_kst() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


def _get_open_positions_from_db(trade_date: str) -> list[dict[str, Any]]:
    """trading_orders에서 오늘 매수 후 아직 매도 안 된 종목을 조회한다."""
    try:
        with get_connection() as conn:
            # 오늘 buy 주문 중 같은 날 sell이 없는 종목
            rows = conn.execute(
                """
                SELECT symbol, SUM(qty) AS qty, AVG(price) AS avg_price
                FROM trading_orders
                WHERE trade_date = ?
                  AND side = 'buy'
                  AND status IN ('submitted', 'filled')
                  AND symbol NOT IN (
                      SELECT DISTINCT symbol FROM trading_orders
                      WHERE trade_date = ? AND side = 'sell'
                      AND status NOT IN ('failed', 'cancelled')
                  )
                GROUP BY symbol
                HAVING qty > 0
                """,
                (trade_date, trade_date),
            ).fetchall()
        return [dict(row) for row in rows]
    except Exception as exc:
        logger.warning("WARN: [S9] DB 포지션 조회 실패 error=%s", exc)
        return []


async def run_eod_liquidation() -> dict[str, Any]:
    """15:20 KST: 보유 전 포지션을 시장가로 청산한다.
    
    인메모리 포지션 우선, 없으면 DB에서 직접 조회해 청산.
    """
    today = _today_kst()
    positions = position_manager.get_positions()

    if not positions:
        logger.info("INFO: [S9] 인메모리 포지션 없음, DB 직접 조회 시도 trade_date=%s", today)
        db_positions = _get_open_positions_from_db(today)
        positions = [
            {"symbol": p["symbol"], "qty": int(p["qty"] or 0)}
            for p in db_positions
            if int(p.get("qty") or 0) > 0
        ]
        logger.info("INFO: [S9] DB 조회 포지션 count=%d", len(positions))

    logger.info("START: [S9] EOD liquidation positions=%d trade_date=%s", len(positions), today)

    if not positions:
        logger.info("INFO: [S9] 청산할 포지션 없음")
        return {"liquidated": 0, "results": []}

    results = []
    for pos in positions:
        symbol = str(pos.get("symbol") or "")
        qty = int(pos.get("qty") or 0)
        if not symbol or qty <= 0:
            continue
        result = await order_executor.execute_sell(
            symbol=symbol,
            qty=qty,
            price=0,
            reason="eod",
        )
        results.append(result)

    logger.info("SUCCESS: [S9] EOD liquidation finished liquidated=%d", len(results))
    return {"liquidated": len(results), "results": results}
```

---

## 작업 3 — startup 시 포지션 자동 복원

`backend/main.py`에 앱 시작 시 오늘 포지션을 자동 복원하는 로직을 추가한다.
lifespan 함수 내 `scheduler.start()` 이후에 추가:

```python
# 서버 재시작 시 오늘 포지션 복원 (S6 activate 없이도 S9가 올바로 동작하도록)
try:
    from .services.engine.decision_engine import _restore_positions_from_db
    from datetime import datetime
    from zoneinfo import ZoneInfo
    _today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    _restore_positions_from_db(_today, [])
    logger.info("INFO: [startup] 오늘 포지션 자동 복원 완료 trade_date=%s", _today)
except Exception as _exc:
    logger.warning("WARN: [startup] 포지션 복원 실패 error=%s", _exc)
```

---

## 검증

```bash
python3 -m py_compile backend/services/engine/decision_engine.py backend/services/engine/eod_liquidation.py backend/main.py && echo "py_compile OK"
```

```bash
python3 - <<'PY'
import os
os.environ.setdefault("APP_ENV", "development")
import asyncio
from backend.services.engine.eod_liquidation import run_eod_liquidation, _get_open_positions_from_db
from backend.services.db import initialize_database
initialize_database()
today = "2026-05-05"
positions = _get_open_positions_from_db(today)
print(f"DB open positions: {len(positions)}")
result = asyncio.run(run_eod_liquidation())
print(f"EOD result: liquidated={result['liquidated']}")
print("PASS")
PY
```

---

## 완료 체크리스트

- [ ] `_restore_positions_from_db()` — candidate_symbols 없어도 복원
- [ ] `run_eod_liquidation()` — 인메모리 없으면 DB 직접 조회 청산
- [ ] `main.py` startup 포지션 자동 복원
- [ ] py_compile OK
- [ ] 검증 스크립트 통과

결과는 `docs/agent-comm/OUTBOX_EXECUTOR_position_restore.md`에 작성하라.
