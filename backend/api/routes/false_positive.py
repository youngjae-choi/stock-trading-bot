"""False Positive API routes for daily judgment validation cases."""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter

from ...services.engine.false_positive import get_today_false_positives

router = APIRouter(prefix="/api/v1/false-positive", tags=["false-positive"])
logger = logging.getLogger("FalsePositiveAPI")


def _today_kst() -> str:
    """Return today's KST date as YYYY-MM-DD for route defaults."""
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


@router.get("/today")
def get_today() -> dict:
    """Return today's false positive cases."""
    trade_date = _today_kst()
    logger.info("START: GET /api/v1/false-positive/today trade_date=%s", trade_date)
    rows = get_today_false_positives(trade_date)
    logger.info("SUCCESS: GET /api/v1/false-positive/today trade_date=%s count=%d", trade_date, len(rows))
    return {"ok": True, "payload": rows}
