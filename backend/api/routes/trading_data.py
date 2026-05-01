"""Trading data persistence routes for orders and later analytics."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ...api.dependencies import require_console_user
from ...services.trading_store import list_orders, record_order

logger = logging.getLogger("BackendTradingDataAPI")
router = APIRouter(prefix="/api/v1/trading-data", tags=["trading-data"], dependencies=[Depends(require_console_user)])


class OrderRecordRequest(BaseModel):
    """Minimal order record body for durable trading analysis storage."""

    symbol: str
    side: str
    quantity: float = Field(gt=0)
    order_type: str = "market"
    limit_price: float | None = None
    status: str = "created"
    strategy_run_id: str | None = None
    signal_id: str | None = None
    broker_order_id: str = ""
    request: dict[str, Any] = Field(default_factory=dict)
    response: dict[str, Any] = Field(default_factory=dict)


@router.get("/orders")
async def get_orders(limit: int = 50):
    """Return recent persisted order records."""
    logger.info("START: GET /api/v1/trading-data/orders")
    payload = {"items": list_orders(limit)}
    logger.info("SUCCESS: GET /api/v1/trading-data/orders")
    return {"ok": True, "source": "backend", "live": False, "payload": payload}


@router.post("/orders")
async def post_order(request: OrderRecordRequest):
    """Persist one order record for later fill, position, and PnL analysis."""
    logger.info("START: POST /api/v1/trading-data/orders symbol=%s", request.symbol)
    payload = record_order(request.model_dump())
    logger.info("SUCCESS: POST /api/v1/trading-data/orders symbol=%s", request.symbol)
    return {"ok": True, "source": "backend", "live": False, "payload": payload}
