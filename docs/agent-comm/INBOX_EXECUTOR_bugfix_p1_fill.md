# INBOX_EXECUTOR_bugfix_p1_fill

## 역할
너는 Executor다. 아래 P1 버그 — Fill Confirmation 미구현을 수정하라.
완료 후 `docs/agent-comm/OUTBOX_EXECUTOR_bugfix_p1_fill.md`에 결과를 작성하라.

---

## 버그 개요

### 증상
- `trading_orders.status`가 `submitted`에서 벗어나지 않음 (체결 확인 없음)
- `fills` 테이블이 비어있음
- 서버 재시작 시 `position_manager._positions`가 소멸 (인메모리)

### 현재 동작
1. `order_executor.py`에서 `order_cash()` 호출 후 즉시 `position_manager.add_position()` (낙관적 등록)
2. KIS 체결 여부를 polling하지 않음
3. 서버 재시작 시 인메모리 포지션 소멸 → PositionManager가 stop-loss 감시 중단

### 수정 목표
1. KIS 주문 체결 조회 API 추가
2. FillPoller 서비스 구현 (60초마다 체결 상태 확인 → DB 갱신)
3. DecisionEngine 재시작 시 `position_stop_states`에서 포지션 복원

---

## 수정 방법

### 수정 1 — KIS 주문 체결 조회 API 추가

파일: `backend/services/kis/domestic/service.py`

아래 함수를 추가한다:

```python
async def get_daily_order_inquiry(date_str: str, side: str = "buy") -> Dict[str, Any]:
    """당일 주문 체결 내역 조회 (VTTC8001R / TTTC8001R).
    
    Args:
        date_str: YYYYMMDD 형식 날짜
        side: "buy" | "sell" | "all"
    """
    sll_buy_dvsn_cd = "02" if side == "buy" else "01" if side == "sell" else "00"
    env = _order_env()
    tr_id = "VTTC8001R" if env == "demo" else "TTTC8001R"
    return await kis_client.request(
        method="GET",
        path="/uapi/domestic-stock/v1/trading/inquire-daily-ccld",
        tr_id=tr_id,
        params={
            "CANO": settings.KIS_CANO,
            "ACNT_PRDT_CD": settings.KIS_ACNT_PRDT_CD,
            "INQR_STRT_DT": date_str,
            "INQR_END_DT": date_str,
            "SLL_BUY_DVSN_CD": sll_buy_dvsn_cd,
            "INQR_DVSN": "00",
            "PDNO": "",
            "CCL_DVSN": "01",        # 01 = 체결된 주문만
            "ORDER_GNO_BRNO": "",
            "ODNO": "",
            "INQR_DVSN_3": "00",
            "INQR_DVSN_1": "",
            "CTX_AREA_FK200": "",
            "CTX_AREA_NK200": "",
        },
    )
```

---

### 수정 2 — FillPoller 구현

파일 신규: `backend/services/engine/fill_poller.py`

```python
"""S7.5 Fill Poller — 주기적으로 KIS 체결 내역을 조회해 trading_orders / fills를 갱신."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection
from ..kis.domestic.service import get_daily_order_inquiry

logger = logging.getLogger("FillPoller")

_POLL_INTERVAL = 60          # 60초마다 체결 확인
_MAX_AGE_HOURS = 8           # 8시간 이상 된 submitted 주문은 폴링 중단


def _now_kst() -> datetime:
    return datetime.now(ZoneInfo("Asia/Seoul"))


def _today_kst() -> str:
    return _now_kst().strftime("%Y-%m-%d")


def _date_kst_nodash() -> str:
    return _now_kst().strftime("%Y%m%d")


def _get_submitted_orders(trade_date: str) -> list[dict[str, Any]]:
    """오늘 submitted 상태 주문 중 kis_order_no가 있는 것만 반환."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM trading_orders WHERE trade_date = ? AND status = 'submitted'"
            " AND kis_order_no != '' AND kis_order_no IS NOT NULL",
            (trade_date,),
        ).fetchall()
    return [dict(r) for r in rows]


def _is_already_filled(order_id: str) -> bool:
    """fills 테이블에 이 order_id의 fill이 이미 존재하는지 확인."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM fills WHERE order_id = ? LIMIT 1", (order_id,)
        ).fetchone()
    return row is not None


def _mark_order_filled(order_id: str, kis_fill_data: dict[str, Any]) -> None:
    """trading_orders를 filled로 갱신하고 fills 테이블에 레코드를 삽입한다."""
    now = _now_kst().isoformat()
    symbol = str(kis_fill_data.get("pdno") or "")
    qty = int(float(kis_fill_data.get("tot_ccld_qty") or 0))
    price_str = str(kis_fill_data.get("avg_prvs") or "0").replace(",", "")
    try:
        price = float(price_str)
    except ValueError:
        price = 0.0
    side = "buy" if str(kis_fill_data.get("sll_buy_dvsn_cd") or "") == "02" else "sell"

    with get_connection() as conn:
        conn.execute(
            "UPDATE trading_orders SET status = 'filled' WHERE id = ?",
            (order_id,),
        )
        fill_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT OR IGNORE INTO fills
                (id, order_id, broker_fill_id, symbol, side, quantity, price,
                 fee, tax, filled_at, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
            """,
            (
                fill_id,
                order_id,
                str(kis_fill_data.get("odno") or ""),
                symbol,
                side,
                qty,
                price,
                now,
                json.dumps(kis_fill_data, ensure_ascii=False),
            ),
        )


def _mark_order_cancelled(order_id: str) -> None:
    """취소 처리된 주문을 DB에 반영한다."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE trading_orders SET status = 'cancelled' WHERE id = ?",
            (order_id,),
        )


async def poll_once(trade_date: str) -> dict[str, Any]:
    """KIS 체결 내역을 1회 조회해 submitted 주문의 상태를 업데이트한다."""
    submitted = _get_submitted_orders(trade_date)
    if not submitted:
        logger.debug("DEBUG: [FillPoller] submitted 주문 없음 — skip")
        return {"filled": 0, "unchanged": 0}

    date_nodash = trade_date.replace("-", "")
    try:
        response = await get_daily_order_inquiry(date_nodash, side="all")
    except Exception as e:
        logger.warning("WARN: [FillPoller] KIS 조회 실패 — %s", e)
        return {"filled": 0, "error": str(e)}

    kis_orders = response.get("output1", [])
    if not isinstance(kis_orders, list):
        kis_orders = []

    # odno → kis_order 매핑 빌드
    kis_map: dict[str, dict] = {}
    for k in kis_orders:
        odno = str(k.get("odno") or "").strip()
        if odno:
            kis_map[odno] = k

    filled_count = 0
    for order in submitted:
        order_id = order["id"]
        kis_order_no = str(order.get("kis_order_no") or "").strip()
        if not kis_order_no or kis_order_no not in kis_map:
            continue

        kis_data = kis_map[kis_order_no]
        ccld_qty = int(float(str(kis_data.get("tot_ccld_qty") or "0").replace(",", "")))
        ord_qty = int(float(str(kis_data.get("ord_qty") or "0").replace(",", "")))
        rmn_qty = int(float(str(kis_data.get("rmn_qty") or "0").replace(",", "")))

        # 전량 체결: tot_ccld_qty == ord_qty 또는 rmn_qty == 0
        if ccld_qty > 0 and (ccld_qty >= ord_qty or rmn_qty == 0):
            if not _is_already_filled(order_id):
                _mark_order_filled(order_id, kis_data)
                logger.info(
                    "SUCCESS: [FillPoller] filled order_id=%s symbol=%s qty=%d price=%.2f",
                    order_id, kis_data.get("pdno"), ccld_qty, float(str(kis_data.get("avg_prvs") or "0").replace(",", "") or 0)
                )
                filled_count += 1

    return {"filled": filled_count, "unchanged": len(submitted) - filled_count}


class FillPoller:
    """주기적으로 KIS 체결 조회를 실행하는 백그라운드 서비스."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._running = False

    def start(self, trade_date: str) -> None:
        """폴링 루프를 백그라운드 태스크로 시작한다."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(trade_date))
        logger.info("SUCCESS: [FillPoller] 시작 trade_date=%s interval=%ds", trade_date, _POLL_INTERVAL)

    def stop(self) -> None:
        """폴링 루프를 정지한다."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        logger.info("SUCCESS: [FillPoller] 정지")

    async def _loop(self, trade_date: str) -> None:
        while self._running:
            try:
                result = await poll_once(trade_date)
                logger.info("INFO: [FillPoller] poll_once 완료 filled=%d", result.get("filled", 0))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("FAIL: [FillPoller] poll_once 오류 — %s", e)
            await asyncio.sleep(_POLL_INTERVAL)


fill_poller = FillPoller()
```

---

### 수정 3 — DecisionEngine 시작 시 포지션 복원 + FillPoller 연동

파일: `backend/services/engine/decision_engine.py`

#### 3a. FillPoller import 추가

`activate()` 내부에 아래 import + 시작 코드 추가:

```python
from .fill_poller import fill_poller

# (activate 마지막 부분 — realtime_ws_manager.start() 호출 전후 어디든)
fill_poller.start(today)
```

#### 3b. deactivate()에 FillPoller 정지 추가

```python
from .fill_poller import fill_poller
fill_poller.stop()
```

#### 3c. 서버 재시작 시 포지션 복원 로직 추가

`activate()` 내부, `load_daily_rules()` 호출 이후에 삽입:

```python
# 인메모리 포지션이 없으면 position_stop_states에서 복원
if not position_manager.get_positions():
    _restore_positions_from_db(today, list(self._candidates.keys()))
```

그리고 module-level 함수 추가:

```python
def _restore_positions_from_db(trade_date: str, candidate_symbols: list[str]) -> None:
    """서버 재시작 후 position_stop_states에서 오늘 포지션을 복원한다."""
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT ps.*, o.qty
                FROM position_stop_states ps
                JOIN trading_orders o
                  ON o.symbol = ps.symbol_code
                  AND o.trade_date = ?
                  AND o.status IN ('submitted', 'filled')
                  AND o.side = 'buy'
                WHERE ps.symbol_code IN ({})
                GROUP BY ps.symbol_code
                HAVING MAX(ps.last_updated_at)
                """.format(",".join("?" * len(candidate_symbols))),
                [trade_date] + candidate_symbols,
            ).fetchall()
    except Exception as e:
        logger.warning("WARN: [S6] 포지션 복원 쿼리 실패 — %s", e)
        return

    from .rule_cache import get_rule
    for row in rows:
        d = dict(row)
        symbol = d.get("symbol_code") or ""
        qty = int(d.get("qty") or 0)
        entry_price = float(d.get("entry_price") or 0)
        if not symbol or qty <= 0 or entry_price <= 0:
            continue
        rule = get_rule(symbol) or {}
        position_manager.add_position(
            symbol=symbol,
            name="",
            qty=qty,
            entry_price=entry_price,
            final_rule=rule,
        )
        logger.info(
            "SUCCESS: [S6] 포지션 복원 symbol=%s qty=%d entry=%.2f",
            symbol, qty, entry_price,
        )
```

---

### 수정 4 — `GET /api/v1/orders/positions` 응답 필드 정규화

파일: `backend/api/routes/orders.py`

`get_positions_api()` 함수에서 position_manager 데이터를 반환할 때
UI가 기대하는 필드명으로 매핑해서 반환한다:

```python
@router.get("/positions")
async def get_positions_api():
    """현재 보유 포지션(PositionManager 인메모리)을 조회한다."""
    endpoint = "/api/v1/orders/positions"
    logger.info("START: GET %s", endpoint)
    try:
        raw_positions = position_manager.get_positions()
        positions = []
        for pos in raw_positions:
            entry = float(pos.get("entry_price") or 0)
            active_stop = float(pos.get("active_stop_price") or 0)
            highest = float(pos.get("highest_price_since_entry") or entry)
            pnl_pct = round((highest - entry) / entry * 100, 2) if entry > 0 else 0.0
            positions.append({
                **pos,
                "stop_loss_price": active_stop,        # UI alias
                "take_profit_price": 0,                # 항상 OFF
                "pnl_pct": pnl_pct,                   # 고점 기준 임시 P&L
                "current_price": 0,                    # 실시간 price는 WS에서
            })
        logger.info("SUCCESS: GET %s count=%d", endpoint, len(positions))
        return {"ok": True, "payload": {"positions": positions, "count": len(positions)}}
    except Exception as exc:
        logger.error("FAIL: GET %s — %s", endpoint, exc)
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})
```

---

## 검증

```bash
python3 -m py_compile \
  backend/services/kis/domestic/service.py \
  backend/services/engine/fill_poller.py \
  backend/services/engine/decision_engine.py \
  backend/api/routes/orders.py
echo "py_compile OK"
```

그리고 아래 로직 검증 스크립트를 실행해 OUTBOX에 포함하라:

```bash
python3 - <<'EOF'
import sys, os, asyncio
sys.path.insert(0, '.')
os.environ.setdefault("APP_ENV", "development")

from backend.services.engine.fill_poller import FillPoller, poll_once

# FillPoller 인스턴스화 확인
fp = FillPoller()
print("FillPoller created:", fp)

# poll_once 직접 호출 (KIS 연결 없으므로 예외 허용)
async def test():
    try:
        result = await poll_once("2026-05-04")
        print("poll_once result:", result)
    except Exception as e:
        print("poll_once exception (KIS 연결 없음 — 정상):", type(e).__name__, str(e)[:60])

asyncio.run(test())
print("PASS")
EOF
```

---

## 완료 체크리스트

- [ ] `backend/services/kis/domestic/service.py`에 `get_daily_order_inquiry()` 추가
- [ ] `backend/services/engine/fill_poller.py` 신규 생성
- [ ] `decision_engine.py activate()`에 `fill_poller.start()` + `_restore_positions_from_db()` 추가
- [ ] `decision_engine.py deactivate()`에 `fill_poller.stop()` 추가
- [ ] `orders.py GET /positions`에 필드 정규화 (`stop_loss_price`, `pnl_pct`) 추가
- [ ] py_compile 전체 통과
- [ ] 검증 스크립트 통과

결과는 `docs/agent-comm/OUTBOX_EXECUTOR_bugfix_p1_fill.md`에 작성하라.
