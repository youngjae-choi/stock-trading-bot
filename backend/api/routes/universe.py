"""Universe API routes for ranking-based symbol discovery."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ...config import validate_config
from ...services.kis.domestic import universe_service
from ..dependencies import kis_config_error_response

logger = logging.getLogger("BackendUniverseAPI")
router = APIRouter(prefix="/api/v1/kis/universe", tags=["universe"])


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
