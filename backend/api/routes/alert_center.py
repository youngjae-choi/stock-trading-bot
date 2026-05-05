"""Alert Center API routes for operational system alerts."""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...services.engine.alert_center import (
    acknowledge_alert,
    create_alert,
    get_alert_summary,
    get_today_alerts,
)

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])
logger = logging.getLogger("AlertCenterAPI")


class AlertCreateRequest(BaseModel):
    """Request body for creating a system alert."""

    alert_type: str
    title: str = Field(..., min_length=1)
    severity: str = "WARNING"
    detail: str = ""


def _today_kst() -> str:
    """Return today's KST date as YYYY-MM-DD for route defaults."""
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


def _raise_bad_request(exc: ValueError) -> None:
    """Convert service validation errors into HTTP 400 responses."""
    logger.warning("WARN: AlertCenterAPI validation failed reason=%s", exc)
    raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/")
def list_alerts(unacknowledged_only: bool = False) -> dict:
    """Return today's system alerts, optionally only unacknowledged alerts."""
    trade_date = _today_kst()
    logger.info(
        "START: GET /api/v1/alerts trade_date=%s unacknowledged_only=%s",
        trade_date,
        unacknowledged_only,
    )
    try:
        alerts = get_today_alerts(trade_date, unacknowledged_only=unacknowledged_only)
    except Exception as exc:
        logger.error("FAIL: GET /api/v1/alerts trade_date=%s reason=%s", trade_date, exc)
        raise HTTPException(status_code=500, detail="Alert list lookup failed") from exc
    logger.info("SUCCESS: GET /api/v1/alerts trade_date=%s count=%d", trade_date, len(alerts))
    return {"ok": True, "payload": alerts}


@router.post("/")
def post_alert(body: AlertCreateRequest) -> dict:
    """Create a system alert for today's trade date."""
    logger.info("START: POST /api/v1/alerts alert_type=%s", body.alert_type)
    try:
        alert = create_alert(
            alert_type=body.alert_type,
            title=body.title,
            severity=body.severity,
            detail=body.detail,
        )
    except ValueError as exc:
        _raise_bad_request(exc)
    except Exception as exc:
        logger.error("FAIL: POST /api/v1/alerts reason=%s", exc)
        raise HTTPException(status_code=500, detail="Alert creation failed") from exc
    logger.info("SUCCESS: POST /api/v1/alerts alert_id=%s", alert["id"])
    return {"ok": True, "payload": alert}


@router.post("/{alert_id}/acknowledge")
def acknowledge(alert_id: str) -> dict:
    """Mark one system alert as acknowledged."""
    logger.info("START: POST /api/v1/alerts/%s/acknowledge", alert_id)
    try:
        updated = acknowledge_alert(alert_id)
    except Exception as exc:
        logger.error("FAIL: POST /api/v1/alerts/%s/acknowledge reason=%s", alert_id, exc)
        raise HTTPException(status_code=500, detail="Alert acknowledgement failed") from exc
    if not updated:
        logger.warning("WARN: POST /api/v1/alerts/%s/acknowledge not_found", alert_id)
        raise HTTPException(status_code=404, detail="Alert not found")
    logger.info("SUCCESS: POST /api/v1/alerts/%s/acknowledge", alert_id)
    return {"ok": True, "payload": {"alert_id": alert_id, "acknowledged": True}}


@router.get("/summary")
def summary() -> dict:
    """Return today's system alert summary."""
    trade_date = _today_kst()
    logger.info("START: GET /api/v1/alerts/summary trade_date=%s", trade_date)
    try:
        payload = get_alert_summary(trade_date)
    except Exception as exc:
        logger.error("FAIL: GET /api/v1/alerts/summary trade_date=%s reason=%s", trade_date, exc)
        raise HTTPException(status_code=500, detail="Alert summary lookup failed") from exc
    logger.info("SUCCESS: GET /api/v1/alerts/summary trade_date=%s", trade_date)
    return {"ok": True, "payload": payload}
