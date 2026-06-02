"""Decision Engine control and signal query routes."""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ...services.engine.decision_engine import decision_engine, get_today_signals
from ...services.kis.realtime_ws import realtime_ws_manager

logger = logging.getLogger("BackendDecisionAPI")
router = APIRouter(prefix="/api/v1/decision", tags=["decision"])


def _today_kst() -> str:
    """Return today's Asia/Seoul date as YYYY-MM-DD."""
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


@router.get("/signals/today")
async def get_today_signals_api():
    """오늘 생성된 매수 신호 조회."""
    trade_date = _today_kst()
    logger.info("START: GET /api/v1/decision/signals/today trade_date=%s", trade_date)
    try:
        signals = get_today_signals(trade_date)
        logger.info("SUCCESS: GET /api/v1/decision/signals/today count=%d", len(signals))
        return {"ok": True, "payload": {"trade_date": trade_date, "signals": signals, "count": len(signals)}}
    except Exception as exc:
        logger.error("FAIL: GET /api/v1/decision/signals/today — %s", exc)
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})


@router.get("/status")
async def get_decision_status():
    """Decision Engine 활성화 상태와 WS 연결 상태를 조회한다."""
    logger.info("START: GET /api/v1/decision/status")
    payload = {
        "active": decision_engine._active,
        "ws_connected": realtime_ws_manager.is_connected,
        "candidates": len(decision_engine._candidates),
        "signals_sent": len(decision_engine._signal_sent),
    }
    logger.info("SUCCESS: GET /api/v1/decision/status active=%s", payload["active"])
    return {"ok": True, "payload": payload}


@router.post("/activate")
async def activate_decision_engine():
    """수동 활성화 — RulePack과 S4 후보를 로드하고 실시간 WS를 시작한다."""
    logger.info("START: POST /api/v1/decision/activate")
    try:
        result = await decision_engine.activate()
        # 수동 활성화도 자동복구 의도로 기록 — 재기동 시 워치독이 복원하게 한다.
        if result.get("ok"):
            from ...services.scheduler import _set_engine_should_be_active

            _set_engine_should_be_active(True)
        logger.info("SUCCESS: POST /api/v1/decision/activate ok=%s", result.get("ok"))
        return {"ok": True, "payload": result}
    except Exception as exc:
        logger.error("FAIL: POST /api/v1/decision/activate — %s", exc)
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})


@router.post("/deactivate")
async def deactivate_decision_engine():
    """수동 비활성화 — 실시간 WS 콜백과 연결을 종료한다."""
    logger.info("START: POST /api/v1/decision/deactivate")
    try:
        # 수동 비활성화는 "꺼둘 의도" — 워치독이 다시 켜지 않도록 플래그를 끈다.
        from ...services.scheduler import _set_engine_should_be_active

        _set_engine_should_be_active(False)
        await decision_engine.deactivate()
        logger.info("SUCCESS: POST /api/v1/decision/deactivate")
        return {"ok": True}
    except Exception as exc:
        logger.error("FAIL: POST /api/v1/decision/deactivate — %s", exc)
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})
