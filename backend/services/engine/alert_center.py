"""Alert Center — 시스템 이상 알림 저장 및 조회."""

from __future__ import annotations

import logging
import uuid
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
    _refresh_alert_summary(alert["trade_date"])
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
        row = conn.execute("SELECT trade_date FROM system_alerts WHERE id = ?", (alert_id,)).fetchone()
        cursor = conn.execute("UPDATE system_alerts SET acknowledged = 1 WHERE id = ?", (alert_id,))
    acknowledged = cursor.rowcount > 0
    if acknowledged and row:
        _refresh_alert_summary(str(row["trade_date"]))
    logger.info("SUCCESS: AlertCenter.acknowledge alert_id=%s updated=%s", alert_id, acknowledged)
    return acknowledged


def _refresh_alert_summary(trade_date: str) -> dict:
    """알림 요약 스냅샷을 재계산해 영속(쓰기시점). 화면은 이 저장값만 읽는다.

    create_alert / acknowledge_alert 등 알림 상태가 바뀌는 쓰기 경로에서 호출되어
    alert_summary_daily를 항상 최신으로 유지한다(staleness 원천 차단).

    Args:
        trade_date: YYYY-MM-DD 대상 거래일.
    """
    import json as _json

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT severity, acknowledged FROM system_alerts WHERE trade_date = ?",
            (trade_date,),
        ).fetchall()
        severity_counts: dict[str, int] = {}
        unack = 0
        for r in rows:
            sev = str(r["severity"])
            severity_counts[sev] = severity_counts.get(sev, 0) + 1
            if not r["acknowledged"]:
                unack += 1
        summary = {
            "trade_date": trade_date,
            "total_count": len(rows),
            "severity_counts": severity_counts,
            "unacknowledged_count": unack,
        }
        conn.execute(
            """
            INSERT INTO alert_summary_daily
                (trade_date, total_count, severity_counts, unacknowledged_count, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(trade_date) DO UPDATE SET
                total_count = excluded.total_count,
                severity_counts = excluded.severity_counts,
                unacknowledged_count = excluded.unacknowledged_count,
                updated_at = excluded.updated_at
            """,
            (trade_date, summary["total_count"], _json.dumps(severity_counts),
             unack, _now_utc()),
        )
    return summary


def get_alert_summary(trade_date: str) -> dict:
    """저장된 알림 요약 스냅샷을 읽는다 — 읽기시점 집계 금지(2026-06-20 Phase2).

    화면은 그리기만 한다: 쓰기 경로(create/acknowledge)가 미리 계산해 저장한 값을 읽을 뿐.
    스냅샷이 없으면(과거 데이터·최초 1회) 1회 백필 후 읽는다(서버 내부 단일 writer, 안전).

    Args:
        trade_date: YYYY-MM-DD trade date to summarize.
    """
    import json as _json

    logger.info("START: AlertCenter.summary trade_date=%s", trade_date)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT total_count, severity_counts, unacknowledged_count "
            "FROM alert_summary_daily WHERE trade_date = ?",
            (trade_date,),
        ).fetchone()
    if row is None:
        # 저장값 없음 — 1회 백필(쓰기시점 계산을 lazy하게 보충).
        summary = _refresh_alert_summary(trade_date)
    else:
        try:
            severity_counts = _json.loads(row["severity_counts"]) or {}
        except Exception:
            severity_counts = {}
        summary = {
            "trade_date": trade_date,
            "total_count": int(row["total_count"] or 0),
            "severity_counts": severity_counts,
            "unacknowledged_count": int(row["unacknowledged_count"] or 0),
        }
    logger.info("SUCCESS: AlertCenter.summary trade_date=%s total=%d", trade_date, summary["total_count"])
    return summary
