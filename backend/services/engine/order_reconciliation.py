"""EOD orphan 주문 reconciliation — odno 없이 submitted로 남은 주문을 KIS 실체결과 대조.

fill_poller는 ODNO 기준이라 odno 없는 주문을 못 잡는다. 이 모듈은 KIS 당일 체결내역
(inquire-daily-ccld)을 종목+수량으로 매칭해 orphan을 해소한다:
  - 매칭되면 fill 기록 + odno 보정 + status=filled
  - 매칭 안 되면 status=cancelled (KIS에 체결 없음)
→ pnl 검증(summarize_order_integrity)이 unverified를 벗어난다.
"""

from __future__ import annotations

import logging
from typing import Any

from ..db import get_connection
from .fill_poller import _mark_order_filled

logger = logging.getLogger("OrderReconciliation")

_ORPHAN_STATUSES = ("submitted", "submitted_without_order_no", "submit_uncertain")


def _to_int(v: Any) -> int:
    try:
        return int(float(str(v).replace(",", "").strip() or 0))
    except (TypeError, ValueError):
        return 0


def _kis_filled_qty(row: dict[str, Any]) -> int:
    for k in ("tot_ccld_qty", "ccld_qty"):
        q = _to_int(row.get(k))
        if q > 0:
            return q
    return 0


def _match_orphan_to_kis_fills(orphan: dict[str, Any], kis_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """orphan(symbol,qty)을 KIS output1 행들과 종목+수량으로 매칭. 우선순위: 수량 일치 > 임의 체결."""
    symbol = str(orphan.get("symbol") or "").strip()
    want_qty = _to_int(orphan.get("qty"))
    if not symbol:
        return None
    candidates = [r for r in kis_rows if str(r.get("pdno") or "").strip() == symbol and _kis_filled_qty(r) > 0]
    if not candidates:
        return None
    for r in candidates:  # 수량 정확 일치 우선
        if _kis_filled_qty(r) == want_qty:
            return r
    return candidates[0]


def _load_orphan_orders(trade_date: str) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM trading_orders WHERE trade_date = ? AND status IN (?,?,?)",
            (trade_date, *_ORPHAN_STATUSES),
        ).fetchall()
        order_dicts = [dict(r) for r in rows]
        # fills 있는 건 제외 (이미 검증됨)
        from .position_integrity import _load_fill_quantities_for_orders

        fills = _load_fill_quantities_for_orders(conn, [str(o.get("id") or "") for o in order_dicts])
    return [o for o in order_dicts if not fills.get(str(o.get("id") or ""))]


def _set_order_cancelled(order_id: str, reason: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE trading_orders SET status = 'cancelled', reason = ? WHERE id = ?",
            (reason, order_id),
        )


def _build_fill_data(order: dict[str, Any], kis_row: dict[str, Any]) -> dict[str, Any]:
    """_mark_order_filled 호환 fill dict 생성 (output1 형식)."""
    side = str(order.get("side") or "")
    sll_buy = "02" if side == "buy" else "01" if side == "sell" else ""
    qty = _kis_filled_qty(kis_row)
    return {
        "odno": str(kis_row.get("odno") or order.get("kis_order_no") or ""),
        "pdno": str(order.get("symbol") or ""),
        "tot_ccld_qty": str(qty),
        "ccld_qty": str(qty),
        "avg_prvs": str(order.get("price") or kis_row.get("avg_prvs") or "0"),
        "sll_buy_dvsn_cd": sll_buy,
        "_source": "eod_reconciliation",
    }


async def reconcile_orders_with_kis(trade_date: str) -> dict[str, Any]:
    """orphan 주문을 KIS 당일 체결과 대조해 해소. {resolved, cancelled, checked}."""
    orphans = _load_orphan_orders(trade_date)
    if not orphans:
        return {"checked": 0, "resolved": [], "cancelled": []}
    logger.info("START: [Reconcile] orphan 주문 %d건 trade_date=%s", len(orphans), trade_date)
    date_str = trade_date.replace("-", "")
    from ..kis.domestic.service import get_daily_order_inquiry

    # side별 KIS 체결조회 1회씩
    kis_rows_by_side: dict[str, list[dict[str, Any]]] = {}
    resolved, cancelled = [], []
    for o in orphans:
        side = str(o.get("side") or "buy").lower()
        if side not in kis_rows_by_side:
            try:
                resp = await get_daily_order_inquiry(date_str, side if side in ("buy", "sell") else "all")
                kis_rows_by_side[side] = resp.get("output1") or []
            except Exception as exc:
                logger.warning("WARN: [Reconcile] KIS 체결조회 실패 side=%s reason=%s", side, exc)
                kis_rows_by_side[side] = []
        match = _match_orphan_to_kis_fills(o, kis_rows_by_side[side])
        oid = str(o.get("id") or "")
        if match:
            try:
                # odno 보정
                with get_connection() as conn:
                    conn.execute(
                        "UPDATE trading_orders SET kis_order_no = ? WHERE id = ?",
                        (str(match.get("odno") or ""), oid),
                    )
                _mark_order_filled(o, _build_fill_data(o, match))
                resolved.append({"order_id": oid, "symbol": o.get("symbol"), "odno": match.get("odno")})
                logger.info(
                    "INFO: [Reconcile] orphan 해소(체결확인) symbol=%s odno=%s", o.get("symbol"), match.get("odno")
                )
            except Exception as exc:
                logger.warning("WARN: [Reconcile] fill 기록 실패 order=%s reason=%s", oid, exc)
        else:
            _set_order_cancelled(oid, "eod_reconcile_no_kis_fill")
            cancelled.append({"order_id": oid, "symbol": o.get("symbol")})
            logger.info("INFO: [Reconcile] orphan 취소(KIS 체결 없음) symbol=%s", o.get("symbol"))
    logger.info("SUCCESS: [Reconcile] resolved=%d cancelled=%d", len(resolved), len(cancelled))
    return {"checked": len(orphans), "resolved": resolved, "cancelled": cancelled}
