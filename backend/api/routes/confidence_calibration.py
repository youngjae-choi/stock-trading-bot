"""Confidence Calibration API routes for confidence-vs-result analysis."""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException

from ...services.engine.confidence_calibration import get_calibration_summary, run_confidence_calibration

router = APIRouter(prefix="/api/v1/confidence-calibration", tags=["confidence-calibration"])
logger = logging.getLogger("ConfidenceCalibrationAPI")


def _today_kst() -> str:
    """Return today's KST date as YYYY-MM-DD for route defaults."""
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


@router.get("/today")
def get_today() -> dict:
    """Return today's persisted confidence calibration rows."""
    trade_date = _today_kst()
    logger.info("START: GET /api/v1/confidence-calibration/today trade_date=%s", trade_date)
    rows = get_calibration_summary(trade_date)
    logger.info("SUCCESS: GET /api/v1/confidence-calibration/today trade_date=%s count=%d", trade_date, len(rows))
    return {"ok": True, "payload": rows}


@router.post("/run")
def run() -> dict:
    """Run confidence calibration manually for today's KST trade date."""
    trade_date = _today_kst()
    logger.info("START: POST /api/v1/confidence-calibration/run trade_date=%s", trade_date)
    try:
        result = run_confidence_calibration(trade_date)
    except Exception as exc:
        logger.error("FAIL: POST /api/v1/confidence-calibration/run trade_date=%s reason=%s", trade_date, exc)
        raise HTTPException(status_code=500, detail="Confidence calibration run failed") from exc
    logger.info("SUCCESS: POST /api/v1/confidence-calibration/run trade_date=%s", trade_date)
    return {"ok": True, "payload": result}
