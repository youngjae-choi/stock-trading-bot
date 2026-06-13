"""Missed Opportunity API routes for judgment validation review."""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query

from ...services.engine.missed_opportunity import (
    get_improvement_candidates,
    get_missed_range,
    get_today_missed,
)

router = APIRouter(prefix="/api/v1/missed-opportunity", tags=["missed-opportunity"])
logger = logging.getLogger("MissedOpportunityAPI")


def _today_kst() -> str:
    """Return today's KST date as YYYY-MM-DD for route defaults."""
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


@router.get("/today")
def get_today(
    start: str = Query(None, description="YYYY-MM-DD (기본값: 오늘) — 기간검색 시작일"),
    end: str = Query(None, description="YYYY-MM-DD (기본값: 오늘) — 기간검색 종료일"),
) -> dict:
    """Return missed opportunities — 기본은 오늘, start/end 지정 시 기간 조회 (하위 호환)."""
    today = _today_kst()
    start = start or today
    end = end or today
    logger.info("START: GET /api/v1/missed-opportunity/today start=%s end=%s", start, end)
    if start == today and end == today:
        rows = get_today_missed(today)
    else:
        rows = get_missed_range(start, end)
    logger.info("SUCCESS: GET /api/v1/missed-opportunity/today start=%s end=%s count=%d", start, end, len(rows))
    return {"ok": True, "payload": rows}


@router.get("/candidates")
def get_candidates() -> dict:
    """Return today's missed opportunities marked as improvement candidates."""
    trade_date = _today_kst()
    logger.info("START: GET /api/v1/missed-opportunity/candidates trade_date=%s", trade_date)
    rows = get_improvement_candidates(trade_date)
    logger.info("SUCCESS: GET /api/v1/missed-opportunity/candidates trade_date=%s count=%d", trade_date, len(rows))
    return {"ok": True, "payload": rows}
