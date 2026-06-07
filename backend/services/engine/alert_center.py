"""Alert Center — 시스템 이상 알림 저장 및 조회."""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection

logger = logging.getLogger("AlertCenter")

_VALID_ALERT_TYPES = {
    "risk_guard",
    "daily_loss_limit",
    "ws_delay",
    "rest_error",
    "db_fail",
    "fill_missing",
    "plan_validation_fail",
    "preflight_block",
    "dq_degraded",
    "emergency_halt",
    "morning_diagnostic",
    "ops_watch",
}
_VALID_SEVERITIES = {"INFO", "WARNING", "CRITICAL"}


def _now_utc() -> str:
    """Return a compact UTC timestamp for alert rows."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _today_kst() -> str:
    """Return today's KST trade date for new alert rows."""
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


def _validate_alert_type(alert_type: str) -> str:
    """Validate alert_type against the Phase 5A alert taxonomy."""
    clean_alert_type = str(alert_type or "").strip()
    if clean_alert_type not in _VALID_ALERT_TYPES:
        raise ValueError(f"invalid alert_type: {alert_type}")
    return clean_alert_type


def _validate_severity(severity: str) -> str:
    """Validate and normalize an alert severity value."""
    clean_severity = str(severity or "WARNING").strip().upper()
    if clean_severity not in _VALID_SEVERITIES:
        raise ValueError(f"invalid alert severity: {severity}")
    return clean_severity


def _alert_row_to_dict(row: Any) -> dict[str, Any]:
    """Convert a system_alerts row into an API-friendly dictionary."""
    alert = dict(row)
    alert["acknowledged"] = bool(alert.get("acknowledged"))
    return alert


def create_alert(alert_type, title, severity: str = "WARNING", detail: str = "",
                  trade_date: str | None = None) -> dict:
    """Create a system alert for today's trade date.

    Args:
        alert_type: One of the supported system alert types.
        title: Short operator-facing title.
        severity: INFO, WARNING, or CRITICAL.
        detail: Optional detailed context for operators and logs.
        trade_date: Override trade date (YYYY-MM-DD). Defaults to today (KST).
    """
    clean_alert_type = _validate_alert_type(str(alert_type))
    clean_severity = _validate_severity(severity)
    clean_title = str(title or "").strip()
    if not clean_title:
        raise ValueError("alert title is required")
    alert = {
        "id": str(uuid.uuid4()),
        "trade_date": str(trade_date).strip() if trade_date else _today_kst(),
        "alert_type": clean_alert_type,
        "severity": clean_severity,
        "title": clean_title,
        "detail": detail or "",
        "acknowledged": False,
        "created_at": _now_utc(),
    }
    logger.info("START: AlertCenter.create alert_type=%s severity=%s", clean_alert_type, clean_severity)
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO system_alerts
                (id, trade_date, alert_type, severity, title, detail, acknowledged, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                alert["id"],
                alert["trade_date"],
                alert["alert_type"],
                alert["severity"],
                alert["title"],
                alert["detail"],
                alert["created_at"],
            ),
        )
    logger.info("SUCCESS: AlertCenter.create alert_id=%s", alert["id"])
    return alert


def get_today_alerts(trade_date: str, unacknowledged_only: bool = False) -> list[dict]:
    """Return system alerts for one trade date, newest first.

    Args:
        trade_date: YYYY-MM-DD trade date to inspect.
        unacknowledged_only: When true, return only alerts still requiring operator acknowledgement.
    """
    logger.info(
        "START: AlertCenter.list trade_date=%s unacknowledged_only=%s",
        trade_date,
        unacknowledged_only,
    )
    where_sql = "WHERE trade_date = ?"
    params: list[Any] = [trade_date]
    if unacknowledged_only:
        where_sql += " AND acknowledged = 0"
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM system_alerts
            {where_sql}
            ORDER BY created_at DESC
            """,
            params,
        ).fetchall()
    alerts = [_alert_row_to_dict(row) for row in rows]
    logger.info("SUCCESS: AlertCenter.list trade_date=%s count=%d", trade_date, len(alerts))
    return alerts


def acknowledge_alert(alert_id: str) -> bool:
    """Mark one system alert as acknowledged.

    Args:
        alert_id: system_alerts.id value.
    """
    logger.info("START: AlertCenter.acknowledge alert_id=%s", alert_id)
    with get_connection() as conn:
        cursor = conn.execute("UPDATE system_alerts SET acknowledged = 1 WHERE id = ?", (alert_id,))
    acknowledged = cursor.rowcount > 0
    logger.info("SUCCESS: AlertCenter.acknowledge alert_id=%s updated=%s", alert_id, acknowledged)
    return acknowledged


def get_alert_summary(trade_date: str) -> dict:
    """Return total, severity counts, and unacknowledged count for one trade date.

    Args:
        trade_date: YYYY-MM-DD trade date to summarize.
    """
    logger.info("START: AlertCenter.summary trade_date=%s", trade_date)
    alerts = get_today_alerts(trade_date)
    severity_counts = dict(Counter(alert["severity"] for alert in alerts))
    summary = {
        "trade_date": trade_date,
        "total_count": len(alerts),
        "severity_counts": severity_counts,
        "unacknowledged_count": sum(1 for alert in alerts if not alert["acknowledged"]),
    }
    logger.info("SUCCESS: AlertCenter.summary trade_date=%s total=%d", trade_date, summary["total_count"])
    return summary
