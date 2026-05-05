"""Review & Audit API routes for S10 daily trade analysis."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException

from ...services.engine.review_audit import get_review_report, run_review_audit

# docs/ 디렉토리 기준 경로 (backend/api/routes/ → 프로젝트 루트/docs/)
_DOCS_DIR = Path(__file__).resolve().parents[3] / "docs"

router = APIRouter(prefix="/api/v1/review-audit", tags=["review-audit"])
logger = logging.getLogger("ReviewAuditAPI")


def _today_kst() -> str:
    """Return today's KST date as YYYY-MM-DD for route defaults."""
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


def _read_audit_md(date: str) -> str | None:
    """docs/SYSTEM_AUDIT_YYYYMMDD.md 파일을 읽어 반환한다. 없으면 None."""
    compact = date.replace("-", "")
    md_path = _DOCS_DIR / f"SYSTEM_AUDIT_{compact}.md"
    if md_path.exists():
        try:
            return md_path.read_text(encoding="utf-8")
        except Exception:
            pass
    return None


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
    md_content = _read_audit_md(trade_date)
    if not report and not md_content:
        logger.info("INFO: GET /api/v1/review-audit/today no report trade_date=%s", trade_date)
        return {"ok": True, "payload": None}
    payload = report or {"trade_date": trade_date}
    if md_content:
        payload["md_content"] = md_content
    logger.info("SUCCESS: GET /api/v1/review-audit/today trade_date=%s md=%s", trade_date, bool(md_content))
    return {"ok": True, "payload": payload}


@router.get("/{date}")
def get_by_date(date: str) -> dict:
    """Return an S10 Review & Audit report by trade date.

    Args:
        date: YYYY-MM-DD trade date path parameter.
    """
    logger.info("START: GET /api/v1/review-audit/%s", date)
    report = get_review_report(date)
    md_content = _read_audit_md(date)
    if not report and not md_content:
        logger.warning("WARN: GET /api/v1/review-audit/%s not found", date)
        raise HTTPException(status_code=404, detail="Review report not found")
    payload = report or {"trade_date": date}
    if md_content:
        payload["md_content"] = md_content
    logger.info("SUCCESS: GET /api/v1/review-audit/%s md=%s", date, bool(md_content))
    return {"ok": True, "payload": payload}
