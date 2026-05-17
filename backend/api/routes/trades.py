"""API routes for trade history and overnight market snapshots."""

from __future__ import annotations

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/v1/trades", tags=["trades"])


@router.get("/history")
async def get_trade_history(limit: int = 31):
    """일별 거래 요약 최근 N일 조회."""
    from ...services.engine.daily_summary import get_trade_history as _get
    items = _get(limit=limit)
    return {"ok": True, "payload": {"items": items, "count": len(items)}}


@router.get("/history/{trade_date}")
async def get_trade_detail(trade_date: str):
    """특정 날짜 거래 상세 (주문 목록 + 신호 목록 포함)."""
    from ...services.engine.daily_summary import get_trade_history as _get_history
    from ...services.engine.order_executor import get_today_orders
    from ...services.engine.decision_engine import get_today_signals

    orders = get_today_orders(trade_date)
    signals = get_today_signals(trade_date)
    history = _get_history(limit=365)
    summary = next((h for h in history if h["trade_date"] == trade_date), None)
    return {
        "ok": True,
        "payload": {
            "summary": summary,
            "orders": orders,
            "signals": signals,
        },
    }


@router.get("/overnight/latest")
async def get_overnight_snapshot():
    """최신 해외 시장 스냅샷 조회."""
    from ...services.engine.us_market_watch import get_latest_snapshot
    snapshot = get_latest_snapshot()
    return {"ok": True, "payload": {"snapshot": snapshot}}


@router.get("/pairs")
async def get_trade_pairs(
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
):
    """날짜 범위 내 (날짜 × 종목) 거래 결과 페어 조회.

    매수/매도 주문을 날짜+종목 기준으로 묶어 손익을 계산해 반환한다.
    """
    from ...services.engine.trade_pairs import get_trade_pairs as _get
    pairs = _get(start, end)
    return {"ok": True, "payload": {"pairs": pairs, "count": len(pairs)}}


@router.get("/debug-kis-orders")
async def debug_kis_orders(
    date: str = Query(..., description="YYYYMMDD"),
    ccld_dvsn: str = Query("01", description="00=전체, 01=체결, 02=미체결"),
    symbol: str = Query("", description="종목코드 (비우면 전체)"),
):
    """KIS 당일 주문체결 raw 응답 디버그."""
    from ...services.kis.common.client import kis_client
    s = __import__("backend.config", fromlist=["settings"]).settings
    resp = await kis_client.request(
        method="GET",
        path="/uapi/domestic-stock/v1/trading/inquire-daily-ccld",
        tr_id="VTTC8001R",
        params={
            "CANO": s.KIS_CANO,
            "ACNT_PRDT_CD": s.KIS_ACNT_PRDT_CD,
            "INQR_STRT_DT": date,
            "INQR_END_DT": date,
            "SLL_BUY_DVSN_CD": "00",
            "INQR_DVSN": "00",
            "PDNO": symbol or "",
            "CCLD_DVSN": ccld_dvsn,
            "ORD_GNO_BRNO": "",
            "ODNO": "",
            "INQR_DVSN_3": "00",
            "INQR_DVSN_1": "",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        },
    )
    out1 = resp.get("output1", [])
    return {
        "rt_cd": resp.get("rt_cd"),
        "msg1": resp.get("msg1"),
        "output1_count": len(out1) if isinstance(out1, list) else str(type(out1)),
        "output1_sample": out1[:5] if isinstance(out1, list) else out1,
        "output2": resp.get("output2"),
    }


@router.post("/run-summary")
async def run_summary_manual():
    """S10 수동 실행: 당일 거래 요약 집계 + DB 백업."""
    from ...services.engine.daily_summary import run_daily_summary
    result = await run_daily_summary()
    return {"ok": True, "payload": result}


@router.post("/backfill-fills")
async def backfill_fills():
    """과거 submitted 주문에 대해 KIS output2(종목별 합계)로 체결가를 복원해 fills + status 업데이트."""
    import json
    import uuid
    import asyncio
    from ...services.kis.common.client import kis_client
    from ...services.db import get_connection
    from ...config import settings as _s

    def to_int(v):
        try:
            return int(float(str(v).replace(",", "").strip() or "0"))
        except Exception:
            return 0

    def to_float(v):
        try:
            return float(str(v).replace(",", "").strip() or "0")
        except Exception:
            return 0.0

    async def fetch_symbol_day(symbol: str, date_str: str) -> dict:
        """특정 (종목, 날짜)의 KIS 체결 요약 반환 (output2 사용)."""
        resp = await kis_client.request(
            method="GET",
            path="/uapi/domestic-stock/v1/trading/inquire-daily-ccld",
            tr_id="VTTC8001R",
            params={
                "CANO": _s.KIS_CANO,
                "ACNT_PRDT_CD": _s.KIS_ACNT_PRDT_CD,
                "INQR_STRT_DT": date_str,
                "INQR_END_DT": date_str,
                "SLL_BUY_DVSN_CD": "00",
                "INQR_DVSN": "00",
                "PDNO": symbol,
                "CCLD_DVSN": "00",
                "ORD_GNO_BRNO": "",
                "ODNO": "",
                "INQR_DVSN_3": "00",
                "INQR_DVSN_1": "",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": "",
            },
        )
        return resp

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, trade_date, symbol, side, qty, price, kis_order_no, created_at
            FROM trading_orders
            WHERE status = 'submitted'
              AND kis_order_no != ''
              AND kis_order_no IS NOT NULL
            """
        ).fetchall()

    orders = [dict(r) for r in rows]
    results = {"orders_found": len(orders), "filled": [], "skipped": [], "errors": []}

    for order in orders:
        date_str = order["trade_date"].replace("-", "")
        symbol = order["symbol"]
        side = order["side"]

        # 이미 fills 있으면 skip
        with get_connection() as conn:
            existing = conn.execute(
                "SELECT id FROM fills WHERE order_id=? LIMIT 1", (order["id"],)
            ).fetchone()
        if existing:
            results["skipped"].append({"symbol": symbol, "date": order["trade_date"], "reason": "이미존재"})
            continue

        # KIS output2로 실제 체결 수량/가격 확인 (buy/sell 모두)
        try:
            await asyncio.sleep(0.1)  # rate limit
            resp = await fetch_symbol_day(symbol, date_str)
            out2 = resp.get("output2") or {}
            kis_ccld_qty = to_int(out2.get("tot_ccld_qty") or "0")
            kis_ccld_amt = to_float(out2.get("tot_ccld_amt") or "0")
            kis_avg_price = to_float(out2.get("pchs_avg_pric") or "0")
        except Exception as e:
            results["errors"].append({"symbol": symbol, "date": order["trade_date"], "error": str(e)})
            continue

        # 체결 수량이 0이면 미체결 → 스킵
        if kis_ccld_qty == 0:
            results["skipped"].append({"symbol": symbol, "date": order["trade_date"], "reason": "미체결(tot_ccld_qty=0)"})
            continue

        if side == "buy" and order["price"] and order["price"] > 0:
            # buy limit 주문: KIS가 체결됐으면 DB 가격 사용 (output2는 buy+sell 혼합될 수 있음)
            fill_price = float(order["price"])
            fill_qty = to_int(order["qty"])
        else:
            # sell/market 주문: KIS output2 가격 사용
            fill_qty = kis_ccld_qty
            fill_price = kis_avg_price
            if fill_price <= 0 and kis_ccld_amt > 0 and fill_qty > 0:
                fill_price = kis_ccld_amt / fill_qty

        if fill_price <= 0:
            results["skipped"].append({"symbol": symbol, "date": order["trade_date"], "reason": "체결가없음"})
            continue

        kis_no = str(order["kis_order_no"]).strip()
        raw = json.dumps({"source": "output2_backfill", "symbol": symbol, "date": date_str})

        with get_connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO orders
                    (id, broker_order_id, symbol, side, order_type, quantity,
                     limit_price, status, requested_at, updated_at, request_json, response_json)
                VALUES (?,?,?,?,'limit',?,?,'filled',?,?,?,?)
                """,
                (
                    order["id"], kis_no, symbol, side,
                    fill_qty, fill_price,
                    order["created_at"], order["created_at"],
                    "{}", raw,
                ),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO fills
                    (id, order_id, broker_fill_id, symbol, side, quantity,
                     price, fee, tax, filled_at, raw_json)
                VALUES (?,?,?,?,?,?,?,0,0,?,?)
                """,
                (
                    str(uuid.uuid4()), order["id"], kis_no,
                    symbol, side, fill_qty, fill_price,
                    order["created_at"], raw,
                ),
            )
            conn.execute(
                "UPDATE trading_orders SET status='filled', price=? WHERE id=?",
                (fill_price, order["id"]),
            )

        results["filled"].append({
            "symbol": symbol, "date": order["trade_date"],
            "side": side, "qty": fill_qty, "price": fill_price,
        })

    return {"ok": True, "payload": results}
