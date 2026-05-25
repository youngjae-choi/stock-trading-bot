"""Morning Market Context API."""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query

logger = logging.getLogger("MorningContextAPI")
router = APIRouter(prefix="/api/v1/morning-context", tags=["morning-context"])


@router.get("/today")
async def get_today_morning_context_api(trade_date: str | None = Query(default=None)) -> dict:
    """오늘 아침 시장 컨텍스트를 반환한다.

    오늘 데이터가 없으면 가장 최근 날짜 데이터로 폴백하며 is_today=False를 반환한다.
    """
    target = trade_date or datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    try:
        from ...services.engine.market_tone import get_today_morning_context, get_latest_morning_context
        ctx = get_today_morning_context(target)
        if ctx is not None:
            return {"ok": True, "data": ctx, "is_today": True}
        # 오늘 데이터 없음 — 가장 최근 데이터로 폴백
        ctx = get_latest_morning_context()
        if ctx is None:
            return {"ok": False, "data": None, "message": f"{target} morning context 없음 (S2 미실행)"}
        return {"ok": True, "data": ctx, "is_today": False}
    except Exception as exc:
        logger.error("morning_context today 조회 실패: %s", exc)
        return {"ok": False, "data": None, "message": str(exc)}


@router.get("/{trade_date}")
async def get_morning_context_by_date(trade_date: str) -> dict:
    """특정 날짜의 아침 시장 컨텍스트를 반환한다."""
    try:
        from ...services.engine.market_tone import get_today_morning_context
        ctx = get_today_morning_context(trade_date)
        if ctx is None:
            return {"ok": False, "data": None, "message": f"{trade_date} morning context 없음"}
        return {"ok": True, "data": ctx}
    except Exception as exc:
        logger.error("morning_context 조회 실패 date=%s: %s", trade_date, exc)
        return {"ok": False, "data": None, "message": str(exc)}
