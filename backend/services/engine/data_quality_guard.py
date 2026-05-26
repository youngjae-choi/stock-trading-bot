"""Data Quality Guard — 데이터 이상 감지 및 전체 품질 상태 관리."""

from __future__ import annotations

import json
import logging
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection

logger = logging.getLogger("DataQualityGuard")

_VALID_EVENT_TYPES = {
    "tick_delay",
    "price_diverge",
    "volume_missing",
    "orderbook_missing",
    "db_write_fail",
    "llm_parse_error",
    "duplicate_tick",
    "symbol_mapping_error",
    "price_zero_or_negative",
    "ws_consecutive_disconnect",
}
_SEVERITY_RANK = {
    "INFO": 0,
    "WARNING": 1,
    "DEGRADED": 2,
    "BLOCK_NEW_ENTRY": 3,
    "EMERGENCY": 4,
}


def _now_utc() -> str:
    """Return a compact UTC timestamp for data-quality persistence rows."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _today_kst() -> str:
    """Return today's KST trade date for event rows created without an explicit date."""
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


def _validate_event_type(event_type: str) -> str:
    """Validate the DQ event type so misspelled operational states are not stored."""
    clean_event_type = str(event_type or "").strip()
    if clean_event_type not in _VALID_EVENT_TYPES:
        raise ValueError(f"invalid data quality event_type: {event_type}")
    return clean_event_type


def _validate_severity(severity: str) -> str:
    """Validate and normalize severity by the guard's priority table."""
    clean_severity = str(severity or "WARNING").strip().upper()
    if clean_severity not in _SEVERITY_RANK:
        raise ValueError(f"invalid data quality severity: {severity}")
    return clean_severity


def _json_dumps(value: Any) -> str:
    """Serialize snapshot counters into compact JSON text for SQLite."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _event_row_to_dict(row: Any) -> dict[str, Any]:
    """Convert a data_quality_events SQLite row into an API-friendly dictionary."""
    event = dict(row)
    event["resolved"] = bool(event.get("resolved"))
    return event


def record_dq_event(event_type, severity: str = "WARNING", symbol: str | None = None, detail: str = "") -> str:
    """Record one data-quality event and return its generated event id.

    Args:
        event_type: One of the supported DQ event types.
        severity: INFO, WARNING, DEGRADED, BLOCK_NEW_ENTRY, or EMERGENCY.
        symbol: Optional symbol related to the event.
        detail: Operator/developer-facing detail text.
    """
    clean_event_type = _validate_event_type(str(event_type))
    clean_severity = _validate_severity(severity)
    event_id = str(uuid.uuid4())
    trade_date = _today_kst()
    created_at = _now_utc()
    logger.info("START: DataQualityGuard.record event_type=%s severity=%s", clean_event_type, clean_severity)
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO data_quality_events
                (id, trade_date, event_type, severity, symbol, detail, resolved, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (event_id, trade_date, clean_event_type, clean_severity, symbol, detail or "", created_at),
        )
    logger.info("SUCCESS: DataQualityGuard.record event_id=%s", event_id)
    return event_id


def get_today_dq_status(trade_date: str) -> dict:
    """Return aggregate data-quality status and raw events for one trade date.

    Args:
        trade_date: YYYY-MM-DD trade date to inspect.
    """
    logger.info("START: DataQualityGuard.status trade_date=%s", trade_date)
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM data_quality_events
            WHERE trade_date = ? AND resolved = 0
            ORDER BY created_at DESC
            """,
            (trade_date,),
        ).fetchall()

    events = [_event_row_to_dict(row) for row in rows]
    event_counts = dict(Counter(event["event_type"] for event in events))
    severity_counts = Counter(event["severity"] for event in events)
    worst_severity = "INFO"
    if events:
        worst_severity = max(
            (event["severity"] for event in events),
            key=lambda item: _SEVERITY_RANK.get(item, 0),
        )

    if severity_counts["EMERGENCY"] >= 1:
        overall_status = "EMERGENCY"
    elif severity_counts["BLOCK_NEW_ENTRY"] >= 1:
        overall_status = "BLOCK_NEW_ENTRY"
    elif severity_counts["DEGRADED"] >= 3:
        overall_status = "DEGRADED"
    elif severity_counts["WARNING"] >= 5:
        overall_status = "WARNING"
    else:
        overall_status = "NORMAL"

    payload = {
        "overall_status": overall_status,
        "worst_severity": worst_severity,
        "event_counts": event_counts,
        "events": events,
    }
    logger.info("SUCCESS: DataQualityGuard.status trade_date=%s status=%s", trade_date, overall_status)
    return payload


def take_dq_snapshot(trade_date: str) -> dict:
    """Persist the latest aggregate DQ status as a point-in-time snapshot.

    Args:
        trade_date: YYYY-MM-DD trade date to snapshot.
    """
    logger.info("START: DataQualityGuard.snapshot.create trade_date=%s", trade_date)
    status = get_today_dq_status(trade_date)
    snapshot = {
        "id": str(uuid.uuid4()),
        "trade_date": trade_date,
        "overall_status": status["overall_status"],
        "event_counts": status["event_counts"],
        "worst_severity": status["worst_severity"],
        "created_at": _now_utc(),
    }
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO data_quality_snapshots
                (id, trade_date, overall_status, event_counts, worst_severity, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot["id"],
                snapshot["trade_date"],
                snapshot["overall_status"],
                _json_dumps(snapshot["event_counts"]),
                snapshot["worst_severity"],
                snapshot["created_at"],
            ),
        )
    logger.info("SUCCESS: DataQualityGuard.snapshot.create snapshot_id=%s", snapshot["id"])
    return snapshot


def publish_event(
    source: str,
    event_type: str,
    severity: str,
    detail: dict | None = None,
    symbol: str | None = None,
    notify_telegram: bool = False,
) -> str | None:
    """Record a DQ event and optionally send a Telegram alert.

    Args:
        source: Component that detected the issue (e.g. "position_manager").
        event_type: One of the supported DQ event types.
        severity: INFO, WARNING, DEGRADED, BLOCK_NEW_ENTRY, or EMERGENCY.
        detail: Optional dict of contextual data — serialized to JSON.
        symbol: Optional stock symbol related to the event.
        notify_telegram: Whether to send a Telegram alert in addition to DB recording.
    """
    import json as _json
    detail_str = _json.dumps(detail or {}, ensure_ascii=False) if detail else ""
    full_detail = f"[{source}] {detail_str}" if detail_str else f"[{source}]"
    try:
        event_id = record_dq_event(event_type=event_type, severity=severity, symbol=symbol, detail=full_detail)
    except Exception as exc:
        logger.warning("WARN: DataQualityGuard.publish_event failed source=%s reason=%s", source, exc)
        return None
    if notify_telegram:
        try:
            import asyncio
            from ..alert_service import send_telegram_alert
            msg = f"[데이터 품질 경보] {severity}\n원인: {event_type}\n컴포넌트: {source}\n{detail_str}"
            asyncio.create_task(send_telegram_alert("[매매봇] DQ 경보", msg))
        except Exception as exc:
            logger.warning("WARN: DataQualityGuard.publish_event telegram failed reason=%s", exc)
    return event_id


def resolve_dq_events(trade_date: str, event_ids: list[str] | None = None) -> int:
    """Mark data-quality events as resolved so they are excluded from status calculation.

    Args:
        trade_date: YYYY-MM-DD trade date to target.
        event_ids: Specific event IDs to resolve. If None, resolves all events for the date.

    Returns:
        Number of rows updated.
    """
    logger.info("START: DataQualityGuard.resolve trade_date=%s ids=%s", trade_date, event_ids)
    with get_connection() as conn:
        if event_ids:
            placeholders = ",".join("?" * len(event_ids))
            cursor = conn.execute(
                f"UPDATE data_quality_events SET resolved = 1 WHERE trade_date = ? AND id IN ({placeholders})",
                [trade_date, *event_ids],
            )
        else:
            cursor = conn.execute(
                "UPDATE data_quality_events SET resolved = 1 WHERE trade_date = ?",
                (trade_date,),
            )
        updated = cursor.rowcount
    logger.info("SUCCESS: DataQualityGuard.resolve updated=%d", updated)
    return updated


def get_current_status() -> str:
    """Return the current overall DQ status based on today's events.

    Returns one of: NORMAL, WARNING, DEGRADED, BLOCK_NEW_ENTRY, EMERGENCY.
    """
    today = _today_kst()
    try:
        result = get_today_dq_status(today)
        return str(result.get("overall_status", "NORMAL"))
    except Exception as exc:
        logger.warning("WARN: DataQualityGuard.get_current_status failed reason=%s", exc)
        return "NORMAL"


def get_latest_dq_snapshot(trade_date: str) -> dict | None:
    """Return the newest DQ snapshot for one trade date, if present.

    Args:
        trade_date: YYYY-MM-DD trade date to inspect.
    """
    logger.info("START: DataQualityGuard.snapshot.latest trade_date=%s", trade_date)
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM data_quality_snapshots
            WHERE trade_date = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (trade_date,),
        ).fetchone()
    if not row:
        logger.info("SUCCESS: DataQualityGuard.snapshot.latest trade_date=%s found=false", trade_date)
        return None
    snapshot = dict(row)
    try:
        snapshot["event_counts"] = json.loads(snapshot.get("event_counts") or "{}")
    except (TypeError, json.JSONDecodeError):
        logger.warning("WARN: DataQualityGuard.snapshot.latest malformed event_counts snapshot_id=%s", snapshot["id"])
        snapshot["event_counts"] = {}
    logger.info("SUCCESS: DataQualityGuard.snapshot.latest trade_date=%s found=true", trade_date)
    return snapshot
