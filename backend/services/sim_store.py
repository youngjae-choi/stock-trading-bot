"""In-memory local simulation order store."""

from __future__ import annotations

import time
from threading import Lock
from typing import Any, Dict, List

_order_lock = Lock()
_sim_orders: List[Dict[str, Any]] = []
_sim_fill_events: List[Dict[str, Any]] = []
_sequence = 0


def _next_order_id() -> str:
    global _sequence
    with _order_lock:
        _sequence += 1
        return f"SIM-{int(time.time() * 1000)}-{_sequence:05d}"


def create_order(*, symbol: str, side: str, qty: int, price: float) -> Dict[str, Any]:
    now = time.time()
    order_id = _next_order_id()
    order_record = {
        "order_id": order_id,
        "mode": "local_simulation",
        "symbol": symbol.upper(),
        "side": side,
        "qty": qty,
        "price": price,
        "status": "FILLED",
        "created_at": now,
    }
    fill_event = {
        "event_id": f"FILL-{order_id}",
        "order_id": order_id,
        "mode": "local_simulation",
        "symbol": symbol.upper(),
        "side": side,
        "filled_qty": qty,
        "filled_price": price,
        "event_type": "TRADE_FILLED",
        "received_at": now,
    }
    with _order_lock:
        _sim_orders.append(order_record)
        _sim_fill_events.append(fill_event)
    return {"order": order_record, "fill_event": fill_event}


def list_orders(limit: int = 20) -> List[Dict[str, Any]]:
    safe = max(1, min(limit, 200))
    with _order_lock:
        return list(reversed(_sim_orders[-safe:]))


def list_fills(limit: int = 20) -> List[Dict[str, Any]]:
    safe = max(1, min(limit, 200))
    with _order_lock:
        return list(reversed(_sim_fill_events[-safe:]))
