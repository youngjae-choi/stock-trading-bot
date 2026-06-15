"""index-board 라이브 시황 브리핑(장전·장후) 조회 — 화면 표시용, 거래일 무관.

아침/장후 브리핑은 하루 1회 산출되는 안정 데이터다. 한 번 스크랩해 DB에 저장하면
이후엔 DB에서 조회해 표시한다(매 진입마다 재스크랩하지 않음 — PM 지시 2026-06-15).
"""
from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter

from ...services.engine.index_board_scraper import scrape_both_with_db

router = APIRouter(prefix="/api/v1/market-briefing", tags=["market-briefing"])
logger = logging.getLogger("MarketBriefingAPI")


@router.get("/live")
async def get_live_briefing() -> dict:
    """index-board 장전·장후 브리핑을 DB 우선으로 반환. 누락 조각만 1회 스크랩 후 저장."""
    trade_date = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    logger.info("START: GET /api/v1/market-briefing/live trade_date=%s", trade_date)
    data = await scrape_both_with_db(trade_date)
    logger.info(
        "SUCCESS: GET /api/v1/market-briefing/live ok=%s source=%s",
        data.get("ok"),
        data.get("source"),
    )
    return {
        "ok": bool(data.get("ok")),
        "payload": {
            "morning": data.get("morning"),
            "evening": data.get("evening"),
            "cached": data.get("source") == "db",
            "source": data.get("source"),
        },
    }
