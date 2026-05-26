"""Data Quality Guard API routes for operational data health monitoring."""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.engine.data_quality_guard import (
    get_latest_dq_snapshot,
    get_today_dq_status,
    record_dq_event,
    resolve_dq_events,
    take_dq_snapshot,
)

router = APIRouter(prefix="/api/v1/data-quality", tags=["data-quality"])
logger = logging.getLogger("DataQualityAPI")


class DataQualityEventRequest(BaseModel):
    """Request body for manually recording a Data Quality event."""

    event_type: str
    severity: str = "WARNING"
    symbol: str | None = None
    detail: str = ""


def _today_kst() -> str:
    """Return today's KST date as YYYY-MM-DD for route defaults."""
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


def _raise_bad_request(exc: ValueError) -> None:
    """Convert service validation errors into HTTP 400 responses."""
    logger.warning("WARN: DataQualityAPI validation failed reason=%s", exc)
    raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/status")
def get_status() -> dict:
    """Return today's aggregate Data Quality status."""
    trade_date = _today_kst()
    logger.info("START: GET /api/v1/data-quality/status trade_date=%s", trade_date)
    try:
        status = get_today_dq_status(trade_date)
    except Exception as exc:
        logger.error("FAIL: GET /api/v1/data-quality/status trade_date=%s reason=%s", trade_date, exc)
        raise HTTPException(status_code=500, detail="Data quality status lookup failed") from exc
    logger.info("SUCCESS: GET /api/v1/data-quality/status trade_date=%s", trade_date)
    return {"ok": True, "payload": status}


@router.get("/snapshot")
def get_snapshot() -> dict:
    """Return today's latest Data Quality snapshot, or null when absent."""
    trade_date = _today_kst()
    logger.info("START: GET /api/v1/data-quality/snapshot trade_date=%s", trade_date)
    try:
        snapshot = get_latest_dq_snapshot(trade_date)
    except Exception as exc:
        logger.error("FAIL: GET /api/v1/data-quality/snapshot trade_date=%s reason=%s", trade_date, exc)
        raise HTTPException(status_code=500, detail="Data quality snapshot lookup failed") from exc
    logger.info("SUCCESS: GET /api/v1/data-quality/snapshot trade_date=%s found=%s", trade_date, bool(snapshot))
    return {"ok": True, "payload": snapshot}


@router.post("/snapshot")
def create_snapshot() -> dict:
    """Create and persist today's Data Quality snapshot."""
    trade_date = _today_kst()
    logger.info("START: POST /api/v1/data-quality/snapshot trade_date=%s", trade_date)
    try:
        snapshot = take_dq_snapshot(trade_date)
    except Exception as exc:
        logger.error("FAIL: POST /api/v1/data-quality/snapshot trade_date=%s reason=%s", trade_date, exc)
        raise HTTPException(status_code=500, detail="Data quality snapshot creation failed") from exc
    logger.info("SUCCESS: POST /api/v1/data-quality/snapshot snapshot_id=%s", snapshot["id"])
    return {"ok": True, "payload": snapshot}


@router.post("/resolve")
def resolve_events(trade_date: str | None = None) -> dict:
    """Resolve (suppress) all data-quality events for a trade date.

    Resolved events are excluded from status calculation and will not block orders.
    Defaults to today's KST date when trade_date is omitted.
    """
    target_date = trade_date or _today_kst()
    logger.info("START: POST /api/v1/data-quality/resolve trade_date=%s", target_date)
    try:
        updated = resolve_dq_events(target_date)
    except Exception as exc:
        logger.error("FAIL: POST /api/v1/data-quality/resolve reason=%s", exc)
        raise HTTPException(status_code=500, detail="Data quality resolve failed") from exc
    logger.info("SUCCESS: POST /api/v1/data-quality/resolve updated=%d", updated)
    return {"ok": True, "payload": {"resolved_count": updated, "trade_date": target_date}}


@router.post("/event")
def create_event(body: DataQualityEventRequest) -> dict:
    """Manually record a Data Quality event for testing and operator workflows."""
    logger.info("START: POST /api/v1/data-quality/event event_type=%s", body.event_type)
    try:
        event_id = record_dq_event(
            event_type=body.event_type,
            severity=body.severity,
            symbol=body.symbol,
            detail=body.detail,
        )
    except ValueError as exc:
        _raise_bad_request(exc)
    except Exception as exc:
        logger.error("FAIL: POST /api/v1/data-quality/event reason=%s", exc)
        raise HTTPException(status_code=500, detail="Data quality event creation failed") from exc
    logger.info("SUCCESS: POST /api/v1/data-quality/event event_id=%s", event_id)
    return {"ok": True, "payload": {"event_id": event_id}}
