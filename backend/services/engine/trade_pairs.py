"""Trade Pairs — symbol 기준 날짜 초월 FIFO 매수→매도 페어링 및 손익 계산."""

from __future__ import annotations

import logging
from typing import Any

from ..db import get_connection

logger = logging.getLogger("TradePairs")


def _determine_status(buys: list[dict], sells: list[dict]) -> str:
    """4단계 상태 결정: 매수주문 → 매수완료 → 매도주문 → 매도완료."""
    _filled = {"filled", "completed", "executed"}
    _active = {"submitted", "submitted_without_order_no", "submit_uncertain", "partial_fill"}

    has_filled_sell = any(o["status"] in _filled for o in sells)
    has_sell = len(sells) > 0
    has_filled_buy = any(o["status"] in _filled | {"partial_fill"} for o in buys)
    has_active_buy = any(o["status"] in _active for o in buys)

    if has_filled_sell:
        return "매도완료"
    if has_sell:
        return "매도주문"
    if has_filled_buy or has_active_buy:
        return "매수완료" if has_filled_buy else "매수주문"
    return "매수주문"


def _effective_price(order: dict, fill_map: dict) -> float:
    """체결가 우선, 없으면 주문가 반환."""
    fp, _ = fill_map.get(order["id"], (0.0, 0.0))
    if fp > 0:
        return fp
    return float(order.get("price") or 0)


def _effective_qty(order: dict, fill_map: dict) -> float:
    """체결수량 우선, 없으면 주문수량 반환."""
    _, fq = fill_map.get(order["id"], (0.0, 0.0))
    if fq > 0:
        return fq
    return float(order.get("qty") or 0)


def _wavg(orders: list[dict], fill_map: dict) -> tuple[float, float]:
    """가중평균가와 총수량 반환."""
    total_qty = 0.0
    total_amount = 0.0
    for o in orders:
        p = _effective_price(o, fill_map)
        q = _effective_qty(o, fill_map)
        total_qty += q
        total_amount += p * q
    avg = total_amount / total_qty if total_qty > 0 else 0.0
    return avg, total_qty


def get_trade_pairs(start_date: str, end_date: str) -> list[dict[str, Any]]:
    """날짜 범위 내 주문을 symbol 기준 FIFO로 페어링해 손익을 계산한다.

    매수와 매도가 다른 날짜여도 같은 symbol이면 하나의 거래로 묶는다.
    결과는 매도 날짜(없으면 매수 날짜) 기준 최신순 정렬.
    """
    logger.info("START: TradePairs start=%s end=%s", start_date, end_date)

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, trade_date, signal_id, symbol, name, side,
                   qty, price, kis_order_no, status, reason, created_at
            FROM trading_orders
            WHERE trade_date >= ? AND trade_date <= ?
              AND status NOT IN ('failed', 'preflight_blocked', 'cancelled')
              AND (kis_order_no IS NOT NULL AND kis_order_no != '')
            ORDER BY symbol, created_at
            """,
            (start_date, end_date),
        ).fetchall()

        order_ids = [row["id"] for row in rows]
        fill_map: dict[str, tuple[float, float]] = {}
        if order_ids:
            placeholders = ",".join("?" * len(order_ids))
            fill_rows = conn.execute(
                f"SELECT order_id, price, quantity FROM fills WHERE order_id IN ({placeholders})",
                order_ids,
            ).fetchall()
            for fr in fill_rows:
                fill_map[fr["order_id"]] = (float(fr["price"] or 0), float(fr["quantity"] or 0))

    # symbol 기준으로 매수/매도 분리 (시간순)
    by_symbol: dict[str, dict[str, list]] = {}
    for row in rows:
        sym = row["symbol"]
        if sym not in by_symbol:
            by_symbol[sym] = {"buys": [], "sells": [], "name": row["name"] or sym}
        if row["name"]:
            by_symbol[sym]["name"] = row["name"]
        order = dict(row)
        if row["side"] == "buy":
            by_symbol[sym]["buys"].append(order)
        else:
            by_symbol[sym]["sells"].append(order)

    pairs = []
    for sym, g in by_symbol.items():
        buys = g["buys"]
        sells = g["sells"]
        name = g["name"]

        buy_avg, buy_qty = _wavg(buys, fill_map)
        sell_avg, sell_qty = _wavg(sells, fill_map)

        # 대표 날짜: 매도 있으면 가장 최근 매도일, 없으면 가장 최근 매수일
        if sells:
            rep_date = max(o["trade_date"] for o in sells)
        else:
            rep_date = max(o["trade_date"] for o in buys)

        # 손익 계산
        matched_qty = min(buy_qty, sell_qty) if buy_qty > 0 and sell_qty > 0 else 0.0
        if matched_qty > 0 and buy_avg > 0 and sell_avg > 0:
            pnl_amount = round((sell_avg - buy_avg) * matched_qty)
            pnl_pct = round((sell_avg - buy_avg) / buy_avg * 100, 2)
        else:
            pnl_amount = None
            pnl_pct = None

        exit_reason = sells[-1].get("reason") if sells else None
        status = _determine_status(buys, sells)

        # 주문 이력 (시간순)
        all_orders = sorted(buys + sells, key=lambda x: x.get("created_at", ""))
        orders_detail = []
        for o in all_orders:
            fp, fq = fill_map.get(o["id"], (0.0, 0.0))
            orders_detail.append({
                "id": o["id"],
                "trade_date": o["trade_date"],
                "side": o["side"],
                "qty": o["qty"],
                "price": o["price"],
                "fill_price": fp if fp > 0 else None,
                "fill_qty": fq if fq > 0 else None,
                "status": o["status"],
                "reason": o["reason"],
                "created_at": o["created_at"],
                "kis_order_no": o["kis_order_no"],
            })

        pairs.append({
            "trade_date": rep_date,
            "symbol": sym,
            "name": name,
            "status": status,
            "buy_price": round(buy_avg) if buy_avg > 0 else None,
            "buy_qty": int(buy_qty) if buy_qty > 0 else None,
            "sell_price": round(sell_avg) if sell_avg > 0 else None,
            "sell_qty": int(sell_qty) if sell_qty > 0 else None,
            "pnl_amount": pnl_amount,
            "pnl_pct": pnl_pct,
            "exit_reason": exit_reason,
            "risk_profile": None,
            "orders": orders_detail,
        })

    # 대표날짜 최신순 정렬
    pairs.sort(key=lambda x: x["trade_date"], reverse=True)

    logger.info("SUCCESS: TradePairs count=%d start=%s end=%s", len(pairs), start_date, end_date)
    return pairs
