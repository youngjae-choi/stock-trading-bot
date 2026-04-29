"""Local simulation order/fill routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter

from ...services.sim_store import create_order, list_fills, list_orders
from ..models import SimOrderRequest

logger = logging.getLogger("BackendSimAPI")
router = APIRouter(prefix="/api/v1/sim", tags=["sim"])


@router.post("/orders")
async def create_sim_order(payload: SimOrderRequest):
    logger.info("START: /api/v1/sim/orders symbol=%s side=%s qty=%s", payload.symbol, payload.side, payload.qty)
    created = create_order(symbol=payload.symbol, side=payload.side, qty=payload.qty, price=payload.price)
    logger.info("SUCCESS: /api/v1/sim/orders order_id=%s", created["order"]["order_id"])
    return {
        "ok": True,
        "mode": "local_simulation",
        "message": "실거래 주문은 전송되지 않았고 로컬 시뮬레이션 주문만 기록되었습니다.",
        "order": created["order"],
        "fill_event": created["fill_event"],
    }


@router.get("/orders")
async def get_recent_sim_orders(limit: int = 20):
    logger.info("START: /api/v1/sim/orders?limit=%s", limit)
    items = list_orders(limit)
    logger.info("SUCCESS: /api/v1/sim/orders count=%s", len(items))
    return {"ok": True, "mode": "local_simulation", "count": len(items), "orders": items}


@router.get("/fills")
async def get_sim_fill_events(limit: int = 20):
    logger.info("START: /api/v1/sim/fills?limit=%s", limit)
    items = list_fills(limit)
    logger.info("SUCCESS: /api/v1/sim/fills count=%s", len(items))
    return {"ok": True, "mode": "local_simulation", "count": len(items), "events": items}
