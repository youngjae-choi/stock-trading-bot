"""index-board 라이브 시황 브리핑(장전·장후) 조회 — 화면 표시용, 거래일 무관.

아침/장후 브리핑은 하루 1회 산출되는 안정 데이터다. 한 번 스크랩해 DB에 저장하면
이후엔 DB에서 조회해 표시한다(매 진입마다 재스크랩하지 않음 — PM 지시 2026-06-15).
"""
from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter

from ...services.engine.index_board_scraper import read_briefing_db, snapshot_briefing_to_db

router = APIRouter(prefix="/api/v1/market-briefing", tags=["market-briefing"])
logger = logging.getLogger("MarketBriefingAPI")


@router.get("/live")
async def get_live_briefing() -> dict:
    """index-board 장전·장중·장후 브리핑을 **DB에서만** 반환한다(페이지 로드 시 스크랩 0).

    스크랩·저장은 스케줄 잡(snapshot_briefing_to_db, 장전~장중 2분·장후)이 전담한다.
    캐시가 완전히 비어 있을 때만(콜드) 1회 스냅샷으로 채운 뒤 DB를 다시 읽는 안전망을 둔다.
    """
    trade_date = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    logger.info("START: GET /api/v1/market-briefing/live trade_date=%s", trade_date)
    data = read_briefing_db(trade_date)
    if not (data.get("morning") or data.get("evening") or data.get("intraday")):
        # 콜드 캐시 — 스케줄 잡이 아직 안 돌았거나 신규일. 1회만 채운다.
        logger.info("INFO: /market-briefing/live 콜드 캐시 — 1회 스냅샷 후 DB 재조회 trade_date=%s", trade_date)
        try:
            await snapshot_briefing_to_db(trade_date)
        except Exception as exc:
            logger.warning("WARN: /market-briefing/live 콜드 스냅샷 실패 — %s", exc)
        data = read_briefing_db(trade_date)
    logger.info("SUCCESS: GET /api/v1/market-briefing/live ok=%s source=%s", data.get("ok"), data.get("source"))
    return {
        "ok": bool(data.get("ok")),
        "payload": {
            "morning": data.get("morning"),
            "intraday": data.get("intraday"),
            "evening": data.get("evening"),
            "cached": True,
            "source": data.get("source"),
            "updated_at": data.get("updated_at"),
        },
    }
