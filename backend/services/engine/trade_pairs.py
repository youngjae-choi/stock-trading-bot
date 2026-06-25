"""Trade Pairs — symbol 기준 날짜 초월 FIFO 매수→매도 페어링 및 손익 계산."""

from __future__ import annotations

import logging
from typing import Any

from ..db import get_connection
from .position_cost_basis import get_cost_basis_map
from .symbol_norm import norm_symbol

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


_FILLED_STATUS = {"filled", "completed", "executed"}


def _effective_qty(order: dict, fill_map: dict) -> float:
    """완전체결(filled) 주문은 주문수량이 권위 — fills가 부분수량만 기록하는 경우 보정.

    KIS 모의/실거래에서 fills가 분할 기록되거나 일부만 동기화돼 fill 수량이 실제보다
    작게 남는 사례가 있다(예: 주문 1056, fill 1). status가 완전체결이면 주문수량을 쓴다.
    그 외(부분체결 등)는 기존대로 체결수량 우선, 없으면 주문수량.
    """
    status = (order.get("status") or "").lower()
    order_qty = float(order.get("qty") or 0)
    if status in _FILLED_STATUS and order_qty > 0:
        return order_qty
    _, fq = fill_map.get(order["id"], (0.0, 0.0))
    if fq > 0:
        return fq
    return order_qty


def _wavg(orders: list[dict], fill_map: dict) -> tuple[float, float]:
    """가중평균가와 총수량 반환. 단가 0(미체결·취소대기) 주문은 평균 오염 방지로 제외한다.

    price=0인 미체결 주문이 가중평균에 합산되면 단가가 붕괴(절반 등)해 손익율이
    비현실적으로 박제되는 사례가 있었다(6/15). effective price ≤ 0은 제외한다.
    """
    total_qty = 0.0
    total_amount = 0.0
    for o in orders:
        p = _effective_price(o, fill_map)
        if p <= 0:
            continue
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

    # 정규화 심볼(norm_symbol) 기준으로 매수/매도 분리 — ETN Q-형 매수와 무Q 매도를 한 쌍으로 묶는다.
    # 표시/시그널 조인용 symbol은 원본 유지(매수 원본 우선 — 시그널·태그가 매수 시점 심볼로 기록됨).
    by_symbol: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = norm_symbol(row["symbol"])
        if key not in by_symbol:
            by_symbol[key] = {
                "buys": [],
                "sells": [],
                "name": row["name"] or row["symbol"],
                "symbol": row["symbol"],
            }
        g = by_symbol[key]
        if row["name"]:
            g["name"] = row["name"]
        order = dict(row)
        if row["side"] == "buy":
            if not g["buys"]:
                g["symbol"] = row["symbol"]
            g["buys"].append(order)
        else:
            g["sells"].append(order)

    # A2: 매수 fill 없는 흡수/정합 포지션의 매수측 원가를 보조 원장에서 일괄 조회한다.
    # 매도만 있는 그룹(buy_qty==0 & sell_qty>0)만 대상 — as_of는 전체 매도일 상한으로 1회 조회.
    cost_basis_map: dict[str, Any] = {}
    sell_only_norms: list[str] = []
    sell_only_as_of = ""
    for key, g in by_symbol.items():
        has_buy = any(_effective_qty(o, fill_map) > 0 and _effective_price(o, fill_map) > 0 for o in g["buys"])
        if not has_buy and g["sells"]:
            sell_only_norms.append(key)
            g_rep = max(o["trade_date"] for o in g["sells"])
            if g_rep > sell_only_as_of:
                sell_only_as_of = g_rep
    if sell_only_norms:
        try:
            cost_basis_map = get_cost_basis_map(sell_only_norms, sell_only_as_of)
        except Exception as cb_exc:
            logger.warning("WARN: TradePairs cost_basis 조회 실패 reason=%s", cb_exc)
            cost_basis_map = {}

    pairs = []
    for key, g in by_symbol.items():
        # 그룹이 두 형(Q/무Q)에서 합쳐질 수 있어 시간순 재정렬
        buys = sorted(g["buys"], key=lambda x: x.get("created_at") or "")
        sells = sorted(g["sells"], key=lambda x: x.get("created_at") or "")
        name = g["name"]
        sym = g["symbol"]

        buy_avg, buy_qty = _wavg(buys, fill_map)
        sell_avg, sell_qty = _wavg(sells, fill_map)

        # 대표 날짜: 매도 있으면 가장 최근 매도일, 없으면 가장 최근 매수일
        if sells:
            rep_date = max(o["trade_date"] for o in sells)
        else:
            rep_date = max(o["trade_date"] for o in buys)

        # A2: 매수측이 비고(buy_qty==0) 매도만 있을 때 cost_basis로 매수측 보강.
        # 원가일이 매도일 이후면 무효(미래 원가). 보강 시 표시·이월 판정용 필드를 채운다.
        cost_basis_source = None
        cost_basis_trade_date = None
        if buy_qty == 0 and sell_qty > 0:
            cb_row = cost_basis_map.get(key)
            if cb_row and cb_row.get("avg_price", 0) > 0 and str(cb_row.get("trade_date") or "") <= rep_date:
                buy_avg = float(cb_row["avg_price"])
                buy_qty = float(cb_row["qty"])
                cost_basis_source = cb_row.get("source")
                cost_basis_trade_date = cb_row.get("trade_date")

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
            "cost_basis_source": cost_basis_source,
            "cost_basis_trade_date": cost_basis_trade_date,
            "orders": orders_detail,
        })

    # 대표날짜 최신순 정렬
    pairs.sort(key=lambda x: x["trade_date"], reverse=True)

    logger.info("SUCCESS: TradePairs count=%d start=%s end=%s", len(pairs), start_date, end_date)
    return pairs


def compute_daily_score(trade_date: str, pairs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """당일 매매성적 단일 산출(SSOT) — 모든 화면/카드가 이 결과를 공유한다.

    기준: rep_date(trade_date) == 대상일인 trade_pair만. (false_positive·daily-results와 동일)
    완료=매도완료+pnl_pct 존재. 승=pnl_pct>0, 패=pnl_pct<0. 손실건=패 건수와 동일 정의.
    체결 건수는 day 짝의 orders 중 fill_qty가 있는 것만(취소·미체결 재시도 제외).

    Args:
        trade_date: YYYY-MM-DD.
        pairs: 사전 조회한 get_trade_pairs 결과(범위 포함). None이면 7일 lookback으로 조회.
    """
    if pairs is None:
        from datetime import datetime, timedelta

        start = (datetime.fromisoformat(trade_date) - timedelta(days=7)).strftime("%Y-%m-%d")
        pairs = get_trade_pairs(start, trade_date)

    day = [p for p in pairs if p.get("trade_date") == trade_date]
    completed = [p for p in day if p.get("status") == "매도완료" and p.get("pnl_pct") is not None]
    wins = [p for p in completed if (p.get("pnl_pct") or 0) > 0]
    losses = [p for p in completed if (p.get("pnl_pct") or 0) < 0]
    flat = [p for p in completed if (p.get("pnl_pct") or 0) == 0]
    open_pairs = [p for p in day if p.get("status") != "매도완료"]
    # 주의: 실현손익(돈)은 계좌 기준 SSOT(equity_pnl)가 단일 출처다. 여기서 페어 pnl_amount를
    # 합산하면 수량 아티팩트로 계좌값과 어긋날 수 있어 의도적으로 노출하지 않는다(카운트 전용).

    buy_fills = sell_fills = 0
    for p in day:
        for o in (p.get("orders") or []):
            if o.get("fill_qty"):
                if o.get("side") == "buy":
                    buy_fills += 1
                elif o.get("side") == "sell":
                    sell_fills += 1

    losers = [
        {
            "symbol": p.get("symbol"),
            "name": p.get("name"),
            "pnl_pct": p.get("pnl_pct"),
            "pnl_amount": p.get("pnl_amount"),
            "exit_reason": p.get("exit_reason"),
        }
        for p in losses
    ]

    n = len(completed)
    return {
        "trade_date": trade_date,
        "symbols": len(day),
        "completed": n,
        "wins": len(wins),
        "losses": len(losses),
        "flat": len(flat),
        "win_rate": round(len(wins) / n * 100, 1) if n else 0.0,
        "open_positions": len(open_pairs),
        "buy_fills": buy_fills,
        "sell_fills": sell_fills,
        "losers": losers,
    }


def get_today_realized_pnl(trade_date: str) -> float:
    """당일 청산 완료된 매매의 실현손익 합계(원). Trade History와 동일 기준(trade_pairs).

    장중 단타 청산 손익을 실시간 당일손익에 반영하기 위한 헬퍼.
    미체결/보유 중(open) 페어는 pnl_amount=None이라 제외된다.
    """
    try:
        pairs = get_trade_pairs(trade_date, trade_date)
    except Exception as exc:
        logger.warning("WARN: get_today_realized_pnl failed date=%s reason=%s", trade_date, exc)
        return 0.0
    return float(sum(p["pnl_amount"] for p in pairs if p.get("pnl_amount") is not None))
