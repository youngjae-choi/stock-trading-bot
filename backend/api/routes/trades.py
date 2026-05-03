"""API routes for trade history and overnight market snapshots."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/trades", tags=["trades"])


@router.get("/history")
async def get_trade_history(limit: int = 30):
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


@router.post("/run-summary")
async def run_summary_manual():
    """S10 수동 실행: 당일 거래 요약 집계 + DB 백업."""
    from ...services.engine.daily_summary import run_daily_summary
    result = await run_daily_summary()
    return {"ok": True, "payload": result}
