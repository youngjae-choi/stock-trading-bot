"""Shadow Trading API routes for same-day virtual missed-entry tracking."""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...services.engine.shadow_trading import (
    create_shadow_trade,
    get_shadow_summary,
    get_today_shadow_trades,
)

router = APIRouter(prefix="/api/v1/shadow-trading", tags=["shadow-trading"])
logger = logging.getLogger("ShadowTradingAPI")


class ShadowTradeCreateRequest(BaseModel):
    """Request body for manually creating a Shadow Trading row."""

    trade_date: str | None = None
    symbol: str = Field(..., min_length=1)
    symbol_name: str = ""
    missed_stage: str = Field(..., min_length=1)
    entry_price: float = 0.0
    entry_time: str | None = None


def _today_kst() -> str:
    """Return today's KST date as YYYY-MM-DD for route defaults."""
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


def _now_kst_iso() -> str:
    """Return the current KST timestamp for route request defaults."""
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()


@router.get("/today")
def get_today() -> dict:
    """Return today's Shadow Trading rows."""
    trade_date = _today_kst()
    logger.info("START: GET /api/v1/shadow-trading/today trade_date=%s", trade_date)
    rows = get_today_shadow_trades(trade_date)
    logger.info("SUCCESS: GET /api/v1/shadow-trading/today trade_date=%s count=%d", trade_date, len(rows))
    return {"ok": True, "payload": rows}


@router.get("/summary")
def get_summary() -> dict:
    """Return today's Shadow Trading aggregate summary."""
    trade_date = _today_kst()
    logger.info("START: GET /api/v1/shadow-trading/summary trade_date=%s", trade_date)
    summary = get_shadow_summary(trade_date)
    logger.info("SUCCESS: GET /api/v1/shadow-trading/summary trade_date=%s", trade_date)
    return {"ok": True, "payload": summary}


@router.post("/")
def create(body: ShadowTradeCreateRequest) -> dict:
    """Create a Shadow Trading row manually for backend testing."""
    trade_date = body.trade_date or _today_kst()
    entry_time = body.entry_time or _now_kst_iso()
    logger.info("START: POST /api/v1/shadow-trading symbol=%s trade_date=%s", body.symbol, trade_date)
    try:
        row = create_shadow_trade(
            trade_date=trade_date,
            symbol=body.symbol,
            symbol_name=body.symbol_name,
            missed_stage=body.missed_stage,
            entry_price=body.entry_price,
            entry_time=entry_time,
        )
    except ValueError as exc:
        logger.warning("WARN: POST /api/v1/shadow-trading validation reason=%s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("FAIL: POST /api/v1/shadow-trading reason=%s", exc)
        raise HTTPException(status_code=500, detail="Shadow trade creation failed") from exc
    logger.info("SUCCESS: POST /api/v1/shadow-trading id=%s", row["id"])
    return {"ok": True, "payload": row}
