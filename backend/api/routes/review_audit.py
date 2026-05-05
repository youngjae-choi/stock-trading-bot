"""Review & Audit API routes for S10 daily trade analysis."""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException

from ...services.engine.review_audit import get_review_report, run_review_audit

router = APIRouter(prefix="/api/v1/review-audit", tags=["review-audit"])
logger = logging.getLogger("ReviewAuditAPI")


def _today_kst() -> str:
    """Return today's KST date as YYYY-MM-DD for route defaults."""
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


@router.post("/run")
async def run() -> dict:
    """Run S10 Review & Audit manually for today's KST trade date."""
    trade_date = _today_kst()
    logger.info("START: POST /api/v1/review-audit/run trade_date=%s", trade_date)
    try:
        result = await run_review_audit(trade_date)
        logger.info("SUCCESS: POST /api/v1/review-audit/run trade_date=%s", trade_date)
        return {"ok": True, "payload": result}
    except Exception as exc:
        logger.error("FAIL: POST /api/v1/review-audit/run trade_date=%s reason=%s", trade_date, exc)
        raise HTTPException(status_code=500, detail="Review audit execution failed") from exc


@router.get("/today")
def get_today() -> dict:
    """Return today's S10 Review & Audit report."""
    trade_date = _today_kst()
    logger.info("START: GET /api/v1/review-audit/today trade_date=%s", trade_date)
    report = get_review_report(trade_date)
    if not report:
        logger.info("INFO: GET /api/v1/review-audit/today no report trade_date=%s", trade_date)
        return {"ok": True, "payload": None}
    logger.info("SUCCESS: GET /api/v1/review-audit/today trade_date=%s", trade_date)
    return {"ok": True, "payload": report}


@router.get("/{date}")
def get_by_date(date: str) -> dict:
    """Return an S10 Review & Audit report by trade date.

    Args:
        date: YYYY-MM-DD trade date path parameter.
    """
    logger.info("START: GET /api/v1/review-audit/%s", date)
    report = get_review_report(date)
    if not report:
        logger.warning("WARN: GET /api/v1/review-audit/%s not found", date)
        raise HTTPException(status_code=404, detail="Review report not found")
    logger.info("SUCCESS: GET /api/v1/review-audit/%s", date)
    return {"ok": True, "payload": report}
