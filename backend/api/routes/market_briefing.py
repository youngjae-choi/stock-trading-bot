"""index-board 라이브 시황 브리핑(장전·장후) 조회 — 화면 표시용, 거래일 무관."""
from __future__ import annotations

import logging

from fastapi import APIRouter

from ...services.engine.index_board_scraper import scrape_both_live

router = APIRouter(prefix="/api/v1/market-briefing", tags=["market-briefing"])
logger = logging.getLogger("MarketBriefingAPI")


@router.get("/live")
async def get_live_briefing() -> dict:
    """index-board 장전·장후 브리핑을 직접 스크랩(10분 캐시)해 반환. LLM·KIS 미사용."""
    logger.info("START: GET /api/v1/market-briefing/live")
    data = await scrape_both_live()
    logger.info(
        "SUCCESS: GET /api/v1/market-briefing/live ok=%s cached=%s",
        data.get("ok"),
        data.get("cached"),
    )
    return {
        "ok": bool(data.get("ok")),
        "payload": {
            "morning": data.get("morning"),
            "evening": data.get("evening"),
            "cached": data.get("cached", False),
        },
    }
