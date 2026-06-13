"""장후(evening) 시황 브리핑 조회 API."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query

from ...services.engine.evening_briefing import (
    get_evening_briefing,
    get_evening_briefings_range,
)

router = APIRouter(prefix="/api/v1/evening-briefing", tags=["evening-briefing"])
logger = logging.getLogger("EveningBriefingAPI")


def _today_kst() -> str:
    """Return today's KST date as YYYY-MM-DD for route defaults."""
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


@router.get("/today")
def get_today(
    start: str = Query(None, description="YYYY-MM-DD — 기간검색 시작일"),
    end: str = Query(None, description="YYYY-MM-DD — 기간검색 종료일"),
) -> dict:
    """오늘 장후 브리핑(없으면 직전 7일 최신 1건 폴백). start/end 지정 시 기간 목록."""
    today = _today_kst()
    if start and end:
        logger.info("START: GET /api/v1/evening-briefing/today range start=%s end=%s", start, end)
        rows = get_evening_briefings_range(start, end)
        logger.info("SUCCESS: GET /api/v1/evening-briefing/today range count=%d", len(rows))
        return {"ok": True, "payload": rows}

    logger.info("START: GET /api/v1/evening-briefing/today today=%s", today)
    row = get_evening_briefing(today)
    if not row:
        # 직전 7일 폴백: 최신 1건
        d = datetime.now(ZoneInfo("Asia/Seoul"))
        start7 = (d - timedelta(days=7)).strftime("%Y-%m-%d")
        rows = get_evening_briefings_range(start7, today)
        row = rows[0] if rows else None
    is_today = bool(row and row.get("trade_date") == today)
    logger.info(
        "SUCCESS: GET /api/v1/evening-briefing/today found=%s is_today=%s",
        row is not None,
        is_today,
    )
    return {"ok": True, "payload": row, "is_today": is_today}
