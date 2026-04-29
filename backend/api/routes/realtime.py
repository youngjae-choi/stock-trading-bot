"""Realtime websocket control and cache access routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ...services.kis.realtime_ws import realtime_ws_manager

logger = logging.getLogger("BackendRealtimeAPI")
router = APIRouter(prefix="/api/v1/kis/realtime", tags=["realtime"])


class RealtimeStartRequest(BaseModel):
    symbols: list[str]


@router.get("/status")
async def get_realtime_status():
    latest = realtime_ws_manager.get_latest(200)
    return {
        "ok": True,
        "payload": {
            "connected": realtime_ws_manager.is_connected,
            "cache_size": len(latest),
        },
    }


@router.get("/latest")
async def get_realtime_latest(n: int = 50):
    try:
        items = realtime_ws_manager.get_latest(n=n)
        return {"ok": True, "payload": {"items": items, "count": len(items)}}
    except Exception as exc:
        logger.error("FAIL: /api/v1/kis/realtime/latest - %s", str(exc))
        return JSONResponse(status_code=502, content={"ok": False, "error": str(exc)})


@router.post("/start")
async def start_realtime(payload: RealtimeStartRequest):
    try:
        await realtime_ws_manager.start(symbols=payload.symbols)
        return {
            "ok": True,
            "payload": {
                "connected": realtime_ws_manager.is_connected,
                "symbols": payload.symbols,
            },
        }
    except Exception as exc:
        logger.error("FAIL: /api/v1/kis/realtime/start - %s", str(exc))
        return JSONResponse(status_code=502, content={"ok": False, "error": str(exc)})


@router.post("/stop")
async def stop_realtime():
    try:
        await realtime_ws_manager.stop()
        return {"ok": True, "payload": {"connected": realtime_ws_manager.is_connected}}
    except Exception as exc:
        logger.error("FAIL: /api/v1/kis/realtime/stop - %s", str(exc))
        return JSONResponse(status_code=502, content={"ok": False, "error": str(exc)})
