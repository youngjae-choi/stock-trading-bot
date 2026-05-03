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


def upsert_setting(key: str, value: Any, value_type: str, description: str, actor: str) -> dict[str, Any]:
    """Create or update one system setting by key."""
    logger.info("START: settings_store.upsert_setting key=%s", key)
    now = _now_iso()
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
    logger.info("SUCCESS: settings_store.upsert_setting key=%s", key)
    return {"key": key, "value": value, "value_type": value_type, "description": description, "updated_at": now, "updated_by": actor}
