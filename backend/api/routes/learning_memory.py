"""Learning Memory API routes for S11 review-derived recommendations."""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException

from ...services.engine.learning_memory import (
    get_active_memories,
    get_today_memories,
    run_learning_memory_builder,
)

router = APIRouter(prefix="/api/v1/learning-memory", tags=["learning-memory"])
logger = logging.getLogger("LearningMemoryAPI")


def _today_kst() -> str:
    """Return today's KST date as YYYY-MM-DD for route defaults."""
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


@router.post("/build")
async def build() -> dict:
    """Run S11 Learning Memory Builder manually for today's KST trade date."""
    trade_date = _today_kst()
    logger.info("START: POST /api/v1/learning-memory/build trade_date=%s", trade_date)
    try:
        result = await run_learning_memory_builder(trade_date)
        if not result.get("ok"):
            logger.warning(
                "WARN: POST /api/v1/learning-memory/build trade_date=%s reason=%s",
                trade_date,
                result.get("reason"),
            )
            return {"ok": False, "payload": result}
        logger.info("SUCCESS: POST /api/v1/learning-memory/build trade_date=%s", trade_date)
        return {"ok": True, "payload": result}
    except Exception as exc:
        logger.error("FAIL: POST /api/v1/learning-memory/build trade_date=%s reason=%s", trade_date, exc)
        raise HTTPException(status_code=500, detail="Learning memory build failed") from exc


@router.get("/today")
def get_today() -> dict:
    """Return today's generated S11 learning memories."""
    trade_date = _today_kst()
    logger.info("START: GET /api/v1/learning-memory/today trade_date=%s", trade_date)
    memories = get_today_memories(trade_date)
    logger.info("SUCCESS: GET /api/v1/learning-memory/today trade_date=%s count=%d", trade_date, len(memories))
    return {"ok": True, "payload": memories}


@router.get("/active")
def get_active(scope: str | None = None) -> dict:
    """Return active S11 learning memories, optionally filtered by scope.

    Args:
        scope: Optional scope filter such as S3_UNIVERSE_FILTER, S4_HYBRID_SCREENING, or S5_DAILY_PLAN.
    """
    logger.info("START: GET /api/v1/learning-memory/active scope=%s", scope or "all")
    memories = get_active_memories(scope=scope)
    logger.info("SUCCESS: GET /api/v1/learning-memory/active scope=%s count=%d", scope or "all", len(memories))
    return {"ok": True, "payload": memories}
