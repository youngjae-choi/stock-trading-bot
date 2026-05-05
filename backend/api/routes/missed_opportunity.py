"""Missed Opportunity API routes for judgment validation review."""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter

from ...services.engine.missed_opportunity import get_improvement_candidates, get_today_missed

router = APIRouter(prefix="/api/v1/missed-opportunity", tags=["missed-opportunity"])
logger = logging.getLogger("MissedOpportunityAPI")


def _today_kst() -> str:
    """Return today's KST date as YYYY-MM-DD for route defaults."""
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


@router.get("/today")
def get_today() -> dict:
    """Return today's missed opportunities."""
    trade_date = _today_kst()
    logger.info("START: GET /api/v1/missed-opportunity/today trade_date=%s", trade_date)
    rows = get_today_missed(trade_date)
    logger.info("SUCCESS: GET /api/v1/missed-opportunity/today trade_date=%s count=%d", trade_date, len(rows))
    return {"ok": True, "payload": rows}


@router.get("/candidates")
def get_candidates() -> dict:
    """Return today's missed opportunities marked as improvement candidates."""
    trade_date = _today_kst()
    logger.info("START: GET /api/v1/missed-opportunity/candidates trade_date=%s", trade_date)
    rows = get_improvement_candidates(trade_date)
    logger.info("SUCCESS: GET /api/v1/missed-opportunity/candidates trade_date=%s count=%d", trade_date, len(rows))
    return {"ok": True, "payload": rows}
