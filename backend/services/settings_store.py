"""Database-backed system settings storage."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from .db import get_connection

logger = logging.getLogger("BackendSettingsStore")


def _now_iso() -> str:
    """Return a UTC timestamp string."""
    return datetime.now(timezone.utc).isoformat()


def list_settings() -> list[dict[str, Any]]:
    """List all persisted system settings."""
    logger.info("START: settings_store.list_settings")
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT key, value_json, value_type, description, updated_at, updated_by FROM system_settings ORDER BY key"
        ).fetchall()
    settings = [
        {
            "key": row["key"],
            "value": json.loads(row["value_json"]),
            "value_type": row["value_type"],
            "description": row["description"],
            "updated_at": row["updated_at"],
            "updated_by": row["updated_by"],
        }
        for row in rows
    ]
    logger.info("SUCCESS: settings_store.list_settings count=%s", len(settings))
    return settings


def get_setting(key: str, default: Any = None) -> Any:
    """단일 키 조회. 없으면 default 반환."""
    with get_connection() as connection:
        row = connection.execute(
            "SELECT value_json FROM system_settings WHERE key = ?", (key,)
        ).fetchone()
    if row is None:
        return default
    return json.loads(row["value_json"])


def get_setting_record(key: str) -> dict[str, Any] | None:
    """Return one setting with value metadata for schedule and safety checks.

    Args:
        key: system_settings key to fetch.
    """
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT key, value_json, value_type, description, updated_at, updated_by
            FROM system_settings
            WHERE key = ?
            """,
            (key,),
        ).fetchone()
    if row is None:
        return None
    return {
        "key": row["key"],
        "value": json.loads(row["value_json"]),
        "value_type": row["value_type"],
        "description": row["description"],
        "updated_at": row["updated_at"],
        "updated_by": row["updated_by"],
    }


def upsert_setting(key: str, value: Any, value_type: str, description: str, actor: str) -> dict[str, Any]:
    """Create or update one system setting by key."""
    import uuid
    logger.info("START: settings_store.upsert_setting key=%s", key)
    now = _now_iso()
    # 변경 전 값 조회 (이력 기록용)
    old_value = get_setting(key, None)

    # 값이 동일하면 DB 업데이트 및 audit 기록 생략
    try:
        if old_value is not None and float(old_value) == float(value):
            logger.info("SKIP: settings_store.upsert_setting key=%s value unchanged=%s", key, value)
            return {"key": key, "value": value, "value_type": value_type, "description": description, "updated_at": now, "updated_by": actor}
    except (TypeError, ValueError):
        if str(old_value) == str(value):
            logger.info("SKIP: settings_store.upsert_setting key=%s value unchanged=%s", key, value)
            return {"key": key, "value": value, "value_type": value_type, "description": description, "updated_at": now, "updated_by": actor}

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO system_settings (key, value_json, value_type, description, updated_at, updated_by)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value_json = excluded.value_json,
                value_type = excluded.value_type,
                description = excluded.description,
                updated_at = excluded.updated_at,
                updated_by = excluded.updated_by
            """,
            (key, json.dumps(value, ensure_ascii=False), value_type, description, now, actor),
        )
        # audit_events에 설정 변경 이력 저장 (실제 변경이 있을 때만)
        try:
            metadata = json.dumps({
                "key": key,
                "old_value": old_value,
                "new_value": value,
                "reason": description,
                "actor": actor,
            }, ensure_ascii=False)
            connection.execute(
                """
                INSERT INTO audit_events (id, event_type, actor, severity, message, metadata_json, created_at)
                VALUES (?, 'settings_change', ?, 'info', ?, ?, ?)
                """,
                (str(uuid.uuid4()), actor, f"설정 변경: {key} {old_value} → {value}", metadata, now),
            )
        except Exception as audit_exc:
            logger.warning("WARN: settings_store audit log failed key=%s error=%s", key, audit_exc)
    logger.info("SUCCESS: settings_store.upsert_setting key=%s old=%s new=%s", key, old_value, value)
    return {"key": key, "value": value, "value_type": value_type, "description": description, "updated_at": now, "updated_by": actor}


def get_settings_changes_for_date(trade_date: str) -> list[dict[str, Any]]:
    """특정 거래일에 변경된 설정 이력 조회 (audit_events).

    Args:
        trade_date: YYYY-MM-DD 형식 거래일.
    """
    date_start = trade_date + "T00:00:00"
    date_end = trade_date + "T23:59:59"
    with get_connection() as connection:
        table_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='audit_events'"
        ).fetchone()
        if not table_exists:
            return []
        rows = connection.execute(
            """
            SELECT actor, message, metadata_json, created_at
            FROM audit_events
            WHERE event_type = 'settings_change'
              AND created_at BETWEEN ? AND ?
            ORDER BY created_at ASC
            """,
            (date_start, date_end),
        ).fetchall()
    result = []
    for row in rows:
        meta: dict[str, Any] = {}
        try:
            meta = json.loads(row["metadata_json"] or "{}")
        except Exception:
            pass
        result.append({
            "key": meta.get("key", ""),
            "old_value": meta.get("old_value"),
            "new_value": meta.get("new_value"),
            "reason": meta.get("reason", ""),
            "actor": row["actor"],
            "changed_at": row["created_at"],
        })
    return result
