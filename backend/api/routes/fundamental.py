"""Fundamental API routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ...config import validate_config
from ...services.kis.domestic import fundamental_service
from ..dependencies import kis_config_error_response

logger = logging.getLogger("BackendFundamentalAPI")
router = APIRouter(prefix="/api/v1/kis", tags=["fundamental"])


@router.get("/fundamental/{symbol}")
async def get_fundamental(symbol: str):
    if not validate_config():
        return kis_config_error_response(f"/api/v1/kis/fundamental/{symbol}")

    try:
        logger.info("START: /api/v1/kis/fundamental/%s", symbol)
        payload = await fundamental_service.get_fundamental(symbol=symbol)
        if payload.get("ok") is True:
            logger.info("SUCCESS: /api/v1/kis/fundamental/%s", symbol)
        else:
            logger.warning("WARN: /api/v1/kis/fundamental/%s - %s", symbol, payload.get("error", "unknown"))
        return payload
    except Exception as exc:
        logger.error("FAIL: /api/v1/kis/fundamental/%s - %s", symbol, str(exc))
        return JSONResponse(status_code=502, content={"ok": False, "error": str(exc)})
