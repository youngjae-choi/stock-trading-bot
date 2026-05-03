"""Order and in-memory position routes for S7/S8/S9."""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ...services.engine.eod_liquidation import run_eod_liquidation
from ...services.engine.order_executor import get_today_orders, order_executor
from ...services.engine.position_manager import position_manager

logger = logging.getLogger("BackendOrdersAPI")
router = APIRouter(prefix="/api/v1/orders", tags=["orders"])


class SellRequest(BaseModel):
    """Manual sell request body for test and operator-triggered exits."""

    symbol: str = Field(..., min_length=1)
    qty: int = Field(..., gt=0)
    price: float = Field(0, ge=0)


def _today_kst() -> str:
    """Return today's Asia/Seoul date as YYYY-MM-DD."""
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


@router.get("/today")
async def get_today_orders_api():
    """오늘 발행된 주문 목록."""
    trade_date = _today_kst()
    endpoint = "/api/v1/orders/today"
    logger.info("START: GET %s trade_date=%s", endpoint, trade_date)
    try:
        orders = get_today_orders(trade_date)
        logger.info("SUCCESS: GET %s count=%d", endpoint, len(orders))
        return {"ok": True, "payload": {"trade_date": trade_date, "orders": orders, "count": len(orders)}}
    except Exception as exc:
        logger.error("FAIL: GET %s — %s", endpoint, exc)
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})


@router.get("/positions")
async def get_positions_api():
    """현재 보유 포지션(PositionManager 인메모리)을 조회한다."""
    endpoint = "/api/v1/orders/positions"
    logger.info("START: GET %s", endpoint)
    try:
        positions = position_manager.get_positions()
        logger.info("SUCCESS: GET %s count=%d", endpoint, len(positions))
        return {"ok": True, "payload": {"positions": positions, "count": len(positions)}}
    except Exception as exc:
        logger.error("FAIL: GET %s — %s", endpoint, exc)
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})


@router.post("/sell")
async def manual_sell(body: SellRequest):
    """수동 매도 주문을 발행한다.

    Args:
        body: Sell request containing symbol, qty, and optional price.
    """
    endpoint = "/api/v1/orders/sell"
    logger.info("START: POST %s symbol=%s qty=%d", endpoint, body.symbol, body.qty)
    try:
        result = await order_executor.execute_sell(
            symbol=body.symbol,
            qty=body.qty,
            price=body.price,
            reason="manual",
        )
        status_code = 200 if result.get("ok") else 502
        logger.info("SUCCESS: POST %s ok=%s", endpoint, result.get("ok"))
        if status_code == 200:
            return {"ok": True, "payload": result}
        return JSONResponse(status_code=status_code, content={"ok": False, "payload": result, "error": result.get("reason", "")})
    except Exception as exc:
        logger.error("FAIL: POST %s — %s", endpoint, exc)
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})


@router.post("/liquidate-all")
async def liquidate_all():
    """전체 포지션을 즉시 시장가로 청산한다."""
    endpoint = "/api/v1/orders/liquidate-all"
    logger.info("START: POST %s", endpoint)
    try:
        result = await run_eod_liquidation()
        logger.info("SUCCESS: POST %s liquidated=%d", endpoint, result.get("liquidated", 0))
        return {"ok": True, "payload": result}
    except Exception as exc:
        logger.error("FAIL: POST %s — %s", endpoint, exc)
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})
