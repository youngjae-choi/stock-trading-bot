"""Persistence helpers for trading data used by later analysis jobs."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from .db import get_connection

logger = logging.getLogger("BackendTradingStore")


def _now_iso() -> str:
    """Return the current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def record_order(data: dict[str, Any]) -> dict[str, Any]:
    """Persist one order request so it can be joined with fills and strategy runs later."""
    logger.info("START: trading_store.record_order symbol=%s", data.get("symbol"))
    now = _now_iso()
    order_id = str(uuid.uuid4())
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO orders (
                id, strategy_run_id, signal_id, broker_order_id, symbol, side, order_type,
                quantity, limit_price, status, requested_at, updated_at, request_json, response_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_id,
                data.get("strategy_run_id"),
                data.get("signal_id"),
                data.get("broker_order_id", ""),
                data["symbol"],
                data["side"],
                data.get("order_type", "market"),
                float(data["quantity"]),
                data.get("limit_price"),
                data.get("status", "created"),
                data.get("requested_at", now),
                now,
                json.dumps(data.get("request", data), ensure_ascii=False),
                json.dumps(data.get("response", {}), ensure_ascii=False),
            ),
        )
    logger.info("SUCCESS: trading_store.record_order id=%s", order_id)
    return {"id": order_id, "symbol": data["symbol"], "side": data["side"], "quantity": float(data["quantity"]), "status": data.get("status", "created")}


def list_orders(limit: int = 50) -> list[dict[str, Any]]:
    """Return recent orders for console checks and analysis smoke tests."""
    logger.info("START: trading_store.list_orders")
    safe_limit = max(1, min(limit, 200))
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, symbol, side, order_type, quantity, limit_price, status, requested_at, updated_at
            FROM orders
            ORDER BY requested_at DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
    items = [dict(row) for row in rows]
    logger.info("SUCCESS: trading_store.list_orders count=%s", len(items))
    return items
