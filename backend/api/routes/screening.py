"""Hybrid Screening API routes (S4)."""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ...api.dependencies import require_console_user
from ...config import validate_config
from ...services.engine import hybrid_screening as screening_svc
from .status_envelope import build_pipeline_read_envelope

logger = logging.getLogger("BackendScreeningAPI")

router = APIRouter(
    prefix="/api/v1/screening",
    tags=["screening"],
    dependencies=[Depends(require_console_user)],
)


@router.get("/today", summary="오늘 하이브리드 스크리닝 결과 조회")
async def get_screening_today():
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    logger.info("START: GET /api/v1/screening/today trade_date=%s", today)
    result = screening_svc.get_today_screening(today)
    logger.info("SUCCESS: GET /api/v1/screening/today found=%s", result is not None)
    return build_pipeline_read_envelope(
        payload={"screening": result, "trade_date": today},
        result=result,
        trade_date=today,
    )


@router.post("/run", summary="하이브리드 스크리닝 즉시 실행")
async def run_screening_now(trigger_source: str = Query(default="api_manual")):
    if not validate_config():
        return JSONResponse(
            status_code=503,
            content={"ok": False, "error": "KIS config not set", "source": "backend", "live": True},
        )
    logger.info("START: POST /api/v1/screening/run trigger_source=%s", trigger_source)
    try:
        result = await screening_svc.run_hybrid_screening(trigger_source=trigger_source)
        logger.info(
            "SUCCESS: POST /api/v1/screening/run output_count=%d provider=%s",
            result.get("output_count", 0),
            result.get("provider", ""),
        )
        return {"ok": True, "source": "backend", "live": True, "payload": result}
    except Exception as exc:
        logger.error("FAIL: POST /api/v1/screening/run — %s", exc)
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": str(exc), "source": "backend", "live": True},
        )
