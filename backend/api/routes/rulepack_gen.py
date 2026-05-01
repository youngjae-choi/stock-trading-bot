"""RulePack 자동 생성 API routes (S5)."""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ...api.dependencies import require_console_user
from ...services.engine import rulepack_generation as gen_svc

logger = logging.getLogger("BackendRulePackGenAPI")

router = APIRouter(
    prefix="/api/v1/rulepack-gen",
    tags=["rulepack-gen"],
    dependencies=[Depends(require_console_user)],
)


@router.get("/today", summary="오늘 활성 RulePack 조회 (생성 결과)")
async def get_rulepack_gen_today():
    """오늘 날짜(KST)의 활성 RulePack 생성 결과를 조회한다."""
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    logger.info("START: GET /api/v1/rulepack-gen/today trade_date=%s", today)
    result = gen_svc.get_today_rulepack(today)
    logger.info("SUCCESS: GET /api/v1/rulepack-gen/today found=%s", result is not None)
    return {
        "ok": True,
        "source": "backend",
        "live": True,
        "payload": {"rulepack": result, "trade_date": today},
    }


@router.post("/run", summary="RulePack 자동 생성 즉시 실행")
async def run_rulepack_gen_now():
    """S5 RulePack 자동 생성을 수동으로 즉시 실행한다."""
    logger.info("START: POST /api/v1/rulepack-gen/run (manual trigger)")
    try:
        result = await gen_svc.run_rulepack_generation()
        logger.info(
            "SUCCESS: POST /api/v1/rulepack-gen/run rulepack_id=%s provider=%s",
            result.get("rulepack_id", ""),
            result.get("provider", ""),
        )
        return {"ok": True, "source": "backend", "live": True, "payload": result}
    except Exception as exc:
        logger.error("FAIL: POST /api/v1/rulepack-gen/run — %s", exc)
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": str(exc), "source": "backend", "live": True},
        )
