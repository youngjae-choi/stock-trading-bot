"""Review & Audit API routes for S10 daily trade analysis."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, HTTPException, Query

from ...services.engine.review_audit import apply_next_day_overrides, get_review_report, run_review_audit
from ...services.settings_store import get_settings_changes_for_date

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
async def run(
    trade_date: str | None = Query(default=None, alias="trade_date"),
    payload: dict[str, Any] | None = Body(default=None),
) -> dict[str, Any]:
    """Run S10 Review & Audit manually for a requested date or today's KST date.

    Args:
        trade_date: Query param YYYY-MM-DD (takes priority over body).
        payload: Optional JSON body with ``date`` or ``trade_date`` in YYYY-MM-DD format.
    """
    requested_date = trade_date or (payload or {}).get("date") or (payload or {}).get("trade_date")
    trade_date = str(requested_date or _today_kst())
    try:
        datetime.strptime(trade_date, "%Y-%m-%d")
    except ValueError as exc:
        logger.warning("WARN: POST /api/v1/review-audit/run invalid date=%s", trade_date)
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD") from exc
    logger.info("START: POST /api/v1/review-audit/run trade_date=%s", trade_date)
    try:
        result = await run_review_audit(trade_date)
        logger.info("SUCCESS: POST /api/v1/review-audit/run trade_date=%s", trade_date)
        return {"ok": True, "payload": result}
    except Exception as exc:
        logger.error("FAIL: POST /api/v1/review-audit/run trade_date=%s reason=%s", trade_date, exc)
        raise HTTPException(status_code=500, detail="Review audit execution failed") from exc


@router.post("/apply-overrides")
async def apply_overrides(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """다음 거래일 daily_trading_plans.daily_overrides에 파라미터 추천값을 저장한다.

    Args:
        payload: {trade_date: YYYY-MM-DD, overrides: {key: value}}
    """
    trade_date = payload.get("trade_date")
    overrides  = payload.get("overrides") or {}
    if not trade_date:
        raise HTTPException(status_code=400, detail="trade_date is required")
    try:
        datetime.strptime(trade_date, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="trade_date must be YYYY-MM-DD") from exc
    if not isinstance(overrides, dict) or not overrides:
        raise HTTPException(status_code=400, detail="overrides must be a non-empty dict")
    logger.info("START: POST /api/v1/review-audit/apply-overrides trade_date=%s overrides=%s", trade_date, overrides)
    try:
        result = apply_next_day_overrides(trade_date, overrides)
        logger.info("SUCCESS: POST /api/v1/review-audit/apply-overrides trade_date=%s", trade_date)
        return {"ok": True, "payload": result}
    except Exception as exc:
        logger.error("FAIL: POST /api/v1/review-audit/apply-overrides reason=%s", exc)
        raise HTTPException(status_code=500, detail="apply overrides failed") from exc


@router.get("/today")
def get_today() -> dict[str, Any]:
    """Return today's S10 Review & Audit report."""
    trade_date = _today_kst()
    logger.info("START: GET /api/v1/review-audit/today trade_date=%s", trade_date)
    report = get_review_report(trade_date)
    md_content = _read_audit_md(trade_date)
    if not report and not md_content:
        logger.info("INFO: GET /api/v1/review-audit/today no report trade_date=%s", trade_date)
        return {"ok": True, "payload": None}
    payload: dict[str, Any] = report or {"trade_date": trade_date, "review_source": "md_backup_only"}
    if md_content:
        compact = trade_date.replace("-", "")
        payload["md_content"] = md_content
        payload["md_path"] = str(_DOCS_DIR / f"SYSTEM_AUDIT_{compact}.md")
        payload["md_backup_exists"] = True
    payload["settings_changes"] = get_settings_changes_for_date(trade_date)
    logger.info("SUCCESS: GET /api/v1/review-audit/today trade_date=%s md=%s", trade_date, bool(md_content))
    return {"ok": True, "payload": payload}


@router.get("/{date}")
def get_by_date(date: str) -> dict[str, Any]:
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
    payload: dict[str, Any] = report or {"trade_date": date, "review_source": "md_backup_only"}
    if md_content:
        compact = date.replace("-", "")
        payload["md_content"] = md_content
        payload["md_path"] = str(_DOCS_DIR / f"SYSTEM_AUDIT_{compact}.md")
        payload["md_backup_exists"] = True
    payload["settings_changes"] = get_settings_changes_for_date(date)
    logger.info("SUCCESS: GET /api/v1/review-audit/%s md=%s", date, bool(md_content))
    return {"ok": True, "payload": payload}
