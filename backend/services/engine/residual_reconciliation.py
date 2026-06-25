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


def _kis_balance_positions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return payload.get("positions", []) or []


async def _kis_held_qty_map() -> dict[str, int]:
    """KIS 실보유 수량 맵 {symbol: qty}. avg_price는 _kis_held_avg_map가 별도 제공."""
    from ...api.routes.account import _build_balance_payload
    from ..kis.domestic.service import get_balance

    payload = _build_balance_payload(await get_balance())
    out: dict[str, int] = {}
    for p in _kis_balance_positions(payload):
        sym = str(p.get("symbol") or "").strip()
        if sym:
            try:
                out[sym] = int(float(str(p.get("qty") or p.get("hldg_qty") or 0)))
            except (TypeError, ValueError):
                out[sym] = 0
    return out


async def _kis_held_avg_map() -> dict[str, float]:
    """KIS 실보유 평단 맵 {symbol: avg_price} — A2 원가 보조 원장 기록용.

    qty 맵과 분리해 기존 _kis_held_qty_map 계약(테스트 monkeypatch 포함)을 보존한다.
    조회 실패 시 빈 맵을 반환해 정합(phantom 정리)을 차단하지 않는다(best-effort).
    """
    try:
        from ...api.routes.account import _build_balance_payload
        from ..kis.domestic.service import get_balance

        payload = _build_balance_payload(await get_balance())
    except Exception as exc:
        logger.warning("WARN: [ResidualReconcile] KIS 평단 조회 실패 — cost_basis 보강 생략 reason=%s", exc)
        return {}
    out: dict[str, float] = {}
    for p in _kis_balance_positions(payload):
        sym = str(p.get("symbol") or "").strip()
        if sym:
            try:
                out[sym] = float(p.get("avg_price") or 0)
            except (TypeError, ValueError):
                out[sym] = 0.0
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
    avg_map = await _kis_held_avg_map()  # best-effort, 실패 시 빈 맵(정리는 계속)
    count = 0
    for r in residuals:
        sym = str(r.get("symbol") or "").strip()
        net = int(r.get("net_qty") or 0)
        kis_qty = int(held.get(sym, 0))
        kis_avg = float(avg_map.get(sym, 0) or 0)
        phantom = net - kis_qty

        # KIS 실보유가 확인된 잔여(kis_qty>0)는 매수 fill이 없는 진짜 보유 — A2 원가 보조 원장에
        # 기록해 trade_pairs가 청산 시 손익을 누락하지 않게 한다(phantom 분과 무관하게 기록).
        if sym and kis_qty > 0 and kis_avg > 0:
            try:
                from .position_cost_basis import upsert_cost_basis

                upsert_cost_basis(sym, kis_qty, kis_avg, "reconciled", trade_date)
            except Exception as _cb_exc:
                logger.warning("WARN: [ResidualReconcile] cost_basis 기록 실패 symbol=%s reason=%s", sym, _cb_exc)

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
