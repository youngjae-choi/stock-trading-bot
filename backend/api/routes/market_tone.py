"""시장 톤 분석 API 라우터 (S2)."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ...api.dependencies import require_console_user
from ...services.engine import llm_router, market_tone
from .status_envelope import build_pipeline_read_envelope

logger = logging.getLogger("BackendMarketToneAPI")
router = APIRouter(prefix="/api/v1/market-tone", tags=["market-tone"], dependencies=[Depends(require_console_user)])


@router.get("/today", summary="오늘 시장 톤 조회")
async def get_market_tone_today():
    """DB에 저장된 오늘의 시장 톤 분석 결과를 반환한다.

    아직 분석이 실행되지 않은 경우 null payload를 반환한다.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    logger.info("START: GET /api/v1/market-tone/today trade_date=%s", today)

    result = market_tone.get_today_market_tone(today)
    logger.info("SUCCESS: GET /api/v1/market-tone/today found=%s", result is not None)
    return build_pipeline_read_envelope(
        payload={"market_tone": result, "trade_date": today},
        result=result,
        trade_date=today,
    )


@router.post("/analyze", summary="시장 톤 즉시 분석 실행")
async def run_market_tone_now(trigger_source: str = Query(default="api_manual")):
    """LLM을 즉시 호출해 시장 톤 분석을 실행하고 결과를 저장한다.

    스케줄러 자동 실행(08:00 KST) 외에 수동으로도 트리거할 수 있다.
    """
    logger.info("START: POST /api/v1/market-tone/analyze trigger_source=%s", trigger_source)
    try:
        result = await market_tone.run_market_tone_analysis(trigger_source=trigger_source)
        logger.info("SUCCESS: POST /api/v1/market-tone/analyze provider=%s tone=%s", result.get("provider"), result.get("tone"))
        return {"ok": True, "source": "backend", "live": True, "payload": result}
    except Exception as exc:
        logger.error("FAIL: POST /api/v1/market-tone/analyze — %s", exc)
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": str(exc), "source": "backend", "live": True},
        )


@router.get("/providers", summary="LLM provider 상태 조회")
async def get_llm_providers():
    """현재 설정된 LLM provider 목록과 활성화 여부를 반환한다."""
    logger.info("START: GET /api/v1/market-tone/providers")
    providers = llm_router.provider_status()
    logger.info("SUCCESS: GET /api/v1/market-tone/providers count=%s", len(providers))
    return {
        "ok": True,
        "source": "backend",
        "live": True,
        "payload": {"providers": providers},
    }
