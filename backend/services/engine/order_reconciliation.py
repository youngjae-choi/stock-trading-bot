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
        return {"checked": 0, "resolved": [], "cancelled": [], "skipped": []}
    logger.info("START: [Reconcile] orphan 주문 %d건 trade_date=%s", len(orphans), trade_date)
    date_str = trade_date.replace("-", "")
    from ..kis.domestic.service import get_daily_order_inquiry

    # side별 KIS 체결조회 1회씩
    kis_rows_by_side: dict[str, list[dict[str, Any]]] = {}
    kis_query_ok: dict[str, bool] = {}
    resolved, cancelled, skipped = [], [], []
    for o in orphans:
        side = str(o.get("side") or "buy").lower()
        if side not in kis_rows_by_side:
            try:
                resp = await get_daily_order_inquiry(date_str, side if side in ("buy", "sell") else "all")
                kis_rows_by_side[side] = resp.get("output1") or []
                kis_query_ok[side] = True
            except Exception as exc:
                logger.warning("WARN: [Reconcile] KIS 체결조회 실패 side=%s reason=%s", side, exc)
                kis_rows_by_side[side] = []
                kis_query_ok[side] = False
        oid = str(o.get("id") or "")
        # ⚠️ KIS 조회 자체가 실패하면 '체결 없음'으로 단정해 취소하면 안 된다(실주문 유실 위험).
        # 보류하고 다음 EOD/재실행 때 다시 시도한다.
        if not kis_query_ok.get(side, False):
            skipped.append({"order_id": oid, "symbol": o.get("symbol"), "reason": "kis_query_failed"})
            logger.warning("WARN: [Reconcile] KIS 조회 실패로 보류(취소 안 함) symbol=%s", o.get("symbol"))
            continue
        match = _match_orphan_to_kis_fills(o, kis_rows_by_side[side])
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
    logger.info(
        "SUCCESS: [Reconcile] resolved=%d cancelled=%d skipped=%d",
        len(resolved), len(cancelled), len(skipped),
    )
    return {"checked": len(orphans), "resolved": resolved, "cancelled": cancelled, "skipped": skipped}


# ──────────────────────────────────────────────────────────────────────────────
# 장중 정합 — 주문번호 없는(submit_uncertain) 매도가 장중 내내 중복가드를 막는 문제 해소.
# 이중매도 방지: 로컬에 매핑 안 된 KIS 매도주문(unaccounted)만 후보로 본다.
#   · unaccounted 체결 있음 → filled 기록(해소)
#   · unaccounted resting(주문번호 있고 미체결) → 주문번호 복구·status=submitted 승격(블록 유지)
#   · KIS에 unaccounted 매도 없음(제출 실제 실패) → 취소(재매도 차단 해제)
#   · KIS 조회 실패 → 보류(취소 안 함)
# (주문번호 있는 'submitted' 정상 미체결은 장중 취소 대상이 아니다 — EOD가 처리)
# ──────────────────────────────────────────────────────────────────────────────

_UNCERTAIN_SELL_STATUSES = ("submitted_without_order_no", "submit_uncertain")


def _kis_odno(row: dict[str, Any]) -> str:
    return str(row.get("odno") or row.get("ODNO") or "").strip()


def _load_uncertain_sells(trade_date: str) -> list[dict[str, Any]]:
    """주문번호 없는 미검증 매도(체결기록 없는 것) 로드."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM trading_orders WHERE trade_date = ? AND side = 'sell' AND status IN (?,?)",
            (trade_date, *_UNCERTAIN_SELL_STATUSES),
        ).fetchall()
        order_dicts = [dict(r) for r in rows]
        from .position_integrity import _load_fill_quantities_for_orders

        fills = _load_fill_quantities_for_orders(conn, [str(o.get("id") or "") for o in order_dicts])
    return [o for o in order_dicts if not fills.get(str(o.get("id") or ""))]


def _local_odnos_for_symbol(trade_date: str, symbol: str) -> set[str]:
    """해당 종목의 로컬 주문들이 이미 보유한 KIS 주문번호 집합(이미 매핑된 것)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT kis_order_no FROM trading_orders WHERE trade_date = ? AND symbol = ? AND side = 'sell'",
            (trade_date, symbol),
        ).fetchall()
    return {str(r["kis_order_no"]).strip() for r in rows if str(r["kis_order_no"] or "").strip()}


def _promote_order_submitted(order_id: str, odno: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE trading_orders SET status = 'submitted', kis_order_no = ? WHERE id = ?",
            (odno, order_id),
        )


async def reconcile_uncertain_sells_intraday(trade_date: str) -> dict[str, Any]:
    """장중: 주문번호 없는 매도를 KIS와 대조해 해소(체결/승격/취소). 이중매도 방지 우선.

    Args:
        trade_date: YYYY-MM-DD.

    Returns:
        {checked, resolved, promoted, cancelled, skipped}.
    """
    uncertain = _load_uncertain_sells(trade_date)
    if not uncertain:
        return {"checked": 0, "resolved": [], "promoted": [], "cancelled": [], "skipped": []}
    logger.info("START: [IntradayReconcile] 미확정 매도 %d건 trade_date=%s", len(uncertain), trade_date)
    date_str = trade_date.replace("-", "")
    from ..kis.domestic.service import get_daily_order_inquiry

    # 매도 KIS 주문 1회 조회 후 종목별로 분류
    kis_sell_rows: list[dict[str, Any]] = []
    kis_ok = True
    try:
        resp = await get_daily_order_inquiry(date_str, "sell")
        kis_sell_rows = resp.get("output1") or []
    except Exception as exc:
        kis_ok = False
        logger.warning("WARN: [IntradayReconcile] KIS 매도 체결조회 실패 reason=%s", exc)

    resolved, promoted, cancelled, skipped = [], [], [], []
    for o in uncertain:
        oid = str(o.get("id") or "")
        symbol = str(o.get("symbol") or "").strip()
        if not kis_ok:
            skipped.append({"order_id": oid, "symbol": symbol, "reason": "kis_query_failed"})
            continue
        used_odnos = _local_odnos_for_symbol(trade_date, symbol)
        # 이 종목의 KIS 매도주문 중 로컬에 아직 매핑 안 된(unaccounted) 것만 후보
        sym_rows = [r for r in kis_sell_rows if str(r.get("pdno") or "").strip() == symbol]
        unaccounted = [r for r in sym_rows if _kis_odno(r) and _kis_odno(r) not in used_odnos]
        if not unaccounted:
            # KIS에 이 주문에 해당할 매도가 없음 → 제출 실제 실패 → 취소(재매도 차단 해제)
            _set_order_cancelled(oid, "intraday_reconcile_no_kis_order")
            cancelled.append({"order_id": oid, "symbol": symbol})
            logger.info("INFO: [IntradayReconcile] 미확정 매도 취소(KIS 주문 없음) symbol=%s — 재매도 허용", symbol)
            continue
        filled_row = next((r for r in unaccounted if _kis_filled_qty(r) > 0), None)
        if filled_row:
            try:
                with get_connection() as conn:
                    conn.execute(
                        "UPDATE trading_orders SET kis_order_no = ? WHERE id = ?",
                        (_kis_odno(filled_row), oid),
                    )
                _mark_order_filled(o, _build_fill_data(o, filled_row))
                resolved.append({"order_id": oid, "symbol": symbol, "odno": _kis_odno(filled_row)})
                logger.info("INFO: [IntradayReconcile] 미확정 매도 체결확인 symbol=%s odno=%s", symbol, _kis_odno(filled_row))
            except Exception as exc:
                logger.warning("WARN: [IntradayReconcile] fill 기록 실패 order=%s reason=%s", oid, exc)
            continue
        # unaccounted resting(미체결, 주문번호 있음) → 살아있는 주문 → 승격(블록 유지, 이중매도 방지)
        resting = unaccounted[0]
        _promote_order_submitted(oid, _kis_odno(resting))
        promoted.append({"order_id": oid, "symbol": symbol, "odno": _kis_odno(resting)})
        logger.info("INFO: [IntradayReconcile] 미확정 매도 승격(KIS resting) symbol=%s odno=%s — 블록 유지", symbol, _kis_odno(resting))

    logger.info(
        "SUCCESS: [IntradayReconcile] resolved=%d promoted=%d cancelled=%d skipped=%d",
        len(resolved), len(promoted), len(cancelled), len(skipped),
    )
    return {"checked": len(uncertain), "resolved": resolved, "promoted": promoted,
            "cancelled": cancelled, "skipped": skipped}
