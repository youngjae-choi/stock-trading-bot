"""Universe API routes for ranking-based symbol discovery and filter results."""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ...api.dependencies import require_console_user
from ...config import validate_config
from ...services.engine import universe_filter as universe_filter_svc
from ...services.kis.domestic import universe_service
from ..dependencies import kis_config_error_response

logger = logging.getLogger("BackendUniverseAPI")
router = APIRouter(prefix="/api/v1/kis/universe", tags=["universe"])

_filter_router = APIRouter(
    prefix="/api/v1/universe-filter",
    tags=["universe-filter"],
    dependencies=[Depends(require_console_user)],
)


@_filter_router.get("/today", summary="오늘 유니버스 필터 결과 조회")
async def get_universe_filter_today():
    """DB에 저장된 오늘의 유니버스 필터 결과를 반환한다."""
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    logger.info("START: GET /api/v1/universe-filter/today trade_date=%s", today)
    result = universe_filter_svc.get_today_universe(today)
    logger.info("SUCCESS: GET /api/v1/universe-filter/today found=%s", result is not None)
    return {
        "ok": True,
        "source": "backend",
        "live": True,
        "payload": {"universe": result, "trade_date": today},
    }


@_filter_router.post("/run", summary="유니버스 필터 즉시 실행")
async def run_universe_filter_now():
    """KIS API를 즉시 호출해 유니버스 필터를 실행하고 결과를 저장한다."""
    if not validate_config():
        return JSONResponse(
            status_code=503,
            content={"ok": False, "error": "KIS config not set", "source": "backend", "live": True},
        )
    logger.info("START: POST /api/v1/universe-filter/run (manual trigger)")
    try:
        result = await universe_filter_svc.run_universe_filter()
        logger.info(
            "SUCCESS: POST /api/v1/universe-filter/run result_count=%d",
            result.get("result_count", 0),
        )
        return {"ok": True, "source": "backend", "live": True, "payload": result}
    except Exception as exc:
        logger.error("FAIL: POST /api/v1/universe-filter/run — %s", exc)
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": str(exc), "source": "backend", "live": True},
        )


# filter_router는 main.py에서 별도로 include한다
filter_router = _filter_router


@router.get("/volume-rank")
async def get_volume_rank(market_code: str = "J", top_n: int = 100):
    if not validate_config():
        return kis_config_error_response("/api/v1/kis/universe/volume-rank")
    try:
        logger.info("START: /api/v1/kis/universe/volume-rank market_code=%s top_n=%s", market_code, top_n)
        payload = await universe_service.get_volume_rank(market_code=market_code, top_n=top_n)
        logger.info("SUCCESS: /api/v1/kis/universe/volume-rank")
        return {"ok": True, "payload": payload}
    except Exception as exc:
        logger.error("FAIL: /api/v1/kis/universe/volume-rank - %s", str(exc))
        return JSONResponse(status_code=502, content={"ok": False, "error": str(exc)})


@router.get("/price-rank")
async def get_price_rank(sort_by: str = "change_rate", market_code: str = "J", top_n: int = 100):
    if not validate_config():
        return kis_config_error_response("/api/v1/kis/universe/price-rank")
    try:
        logger.info(
            "START: /api/v1/kis/universe/price-rank sort_by=%s market_code=%s top_n=%s",
            sort_by,
            market_code,
            top_n,
        )
        payload = await universe_service.get_price_rank(sort_by=sort_by, market_code=market_code, top_n=top_n)
        logger.info("SUCCESS: /api/v1/kis/universe/price-rank")
        return {"ok": True, "payload": payload}
    except Exception as exc:
        logger.error("FAIL: /api/v1/kis/universe/price-rank - %s", str(exc))
        return JSONResponse(status_code=502, content={"ok": False, "error": str(exc)})
