"""Legacy 잔여 포지션을 KIS 실보유와 대조해 phantom 분을 reconciliation 기록으로 정리.

trading_orders/fills는 건드리지 않는다(P&L 보존). position_reconciliations에 기록하면
detect_legacy_residual_positions가 그만큼 빼서 더 이상 잔여로 안 잡는다.
KIS 조회 실패 시 아무것도 하지 않는다(오정리 방지).
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from ..db import get_connection
from .position_integrity import (
    _ensure_position_reconciliations_table,
    detect_legacy_residual_positions,
)

logger = logging.getLogger("ResidualReconciliation")


def _detect_residuals(trade_date: str) -> list[dict[str, Any]]:
    return detect_legacy_residual_positions(trade_date)


async def _kis_held_qty_map() -> dict[str, int]:
    from ...api.routes.account import _build_balance_payload
    from ..kis.domestic.service import get_balance

    payload = _build_balance_payload(await get_balance())
    out: dict[str, int] = {}
    for p in payload.get("positions", []) or []:
        sym = str(p.get("symbol") or "").strip()
        if sym:
            try:
                out[sym] = int(float(str(p.get("qty") or p.get("hldg_qty") or 0)))
            except (TypeError, ValueError):
                out[sym] = 0
    return out


def _record_reconciliation(
    *, symbol: str, reconciled_qty: int, db_net_qty: int, kis_qty: int, trade_date: str
) -> None:
    from datetime import datetime, timezone

    _ensure_position_reconciliations_table()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO position_reconciliations (id, symbol, reconciled_qty, db_net_qty, kis_qty, trade_date, reason, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                str(uuid.uuid4()),
                symbol,
                reconciled_qty,
                db_net_qty,
                kis_qty,
                trade_date,
                "kis_holdings_reconcile",
                datetime.now(timezone.utc).isoformat(),
            ),
        )


async def reconcile_residual_positions_with_kis(trade_date: str) -> dict[str, Any]:
    residuals = _detect_residuals(trade_date)
    if not residuals:
        return {"reconciled": 0, "residuals": 0}
    try:
        held = await _kis_held_qty_map()
    except Exception as exc:
        logger.warning("WARN: [ResidualReconcile] KIS 보유 조회 실패 — 정리 보류 reason=%s", exc)
        return {"reconciled": 0, "residuals": len(residuals), "skipped": True}
    count = 0
    for r in residuals:
        sym = str(r.get("symbol") or "").strip()
        net = int(r.get("net_qty") or 0)
        kis_qty = int(held.get(sym, 0))
        phantom = net - kis_qty
        if sym and phantom > 0:
            _record_reconciliation(
                symbol=sym,
                reconciled_qty=phantom,
                db_net_qty=net,
                kis_qty=kis_qty,
                trade_date=trade_date,
            )
            count += 1
            logger.info(
                "INFO: [ResidualReconcile] phantom 정리 symbol=%s net=%d kis=%d 정리=%d",
                sym,
                net,
                kis_qty,
                phantom,
            )
    logger.info("SUCCESS: [ResidualReconcile] residuals=%d reconciled=%d", len(residuals), count)
    return {"reconciled": count, "residuals": len(residuals)}
