"""Auto-trading workflow routes with dry-run/live safety guard."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ...services.autotrade.workflow import LIVE_CONFIRM_TEXT, execute_auto_trade, run_autotrade_scenarios
from ..models import AutoTradeExecuteRequest

logger = logging.getLogger("BackendAutoTradeAPI")
router = APIRouter(prefix="/api/v1/kis/autotrade", tags=["kis-autotrade"])


@router.get("/guard")
async def get_autotrade_guard():
    return {
        "ok": True,
        "live_confirm_text": LIVE_CONFIRM_TEXT,
        "modes": ["dry_run", "live"],
        "notes": [
            "dry_run은 로컬 시뮬레이션 저장소만 사용합니다.",
            "live 모드는 confirm_text 일치 시에만 주문을 전송합니다.",
        ],
    }


@router.post("/execute")
async def execute_trade(payload: AutoTradeExecuteRequest):
    try:
        result = await execute_auto_trade(payload.model_dump())
        if result.get("ok"):
            return result
        return JSONResponse(status_code=400, content=result)
    except Exception as exc:
        logger.error("FAIL: /api/v1/kis/autotrade/execute - %s", str(exc))
        return JSONResponse(status_code=502, content={"ok": False, "error": str(exc)})


@router.post("/scenario-test")
async def run_scenario_test():
    try:
        return await run_autotrade_scenarios()
    except Exception as exc:
        logger.error("FAIL: /api/v1/kis/autotrade/scenario-test - %s", str(exc))
        return JSONResponse(status_code=502, content={"ok": False, "error": str(exc)})
