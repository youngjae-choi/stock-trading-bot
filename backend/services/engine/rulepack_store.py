"""RulePack CRUD service — stores and retrieves RulePacks from SQLite."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from ..db import get_connection

logger = logging.getLogger("BackendRulePackStore")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _today_kst() -> str:
    """Return today's date in KST (UTC+9) as YYYY-MM-DD."""
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


def create_rulepack(
    *,
    trade_date: str,
    machine_rules: dict[str, Any],
    summary: str = "",
    changes: str = "",
    mode: str = "auto",
    validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Insert a new RulePack row and return the created record."""
    logger.info("START: rulepack_store.create_rulepack trade_date=%s", trade_date)
    rulepack_id = f"RP-{trade_date.replace('-', '')}-{uuid.uuid4().hex[:6].upper()}"
    now = _utc_now_iso()
    validation_json = json.dumps(validation or {"schema": "pending", "risk_policy": "pending", "runtime": "pending"}, ensure_ascii=False)
    machine_rules_json = json.dumps(machine_rules, ensure_ascii=False)

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO rulepacks
                (rulepack_id, trade_date, mode, status, machine_rules, summary, changes, validation, created_at)
            VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?)
            """,
            (rulepack_id, trade_date, mode, machine_rules_json, summary, changes, validation_json, now),
        )

    logger.info("SUCCESS: rulepack_store.create_rulepack rulepack_id=%s", rulepack_id)
    return get_rulepack(rulepack_id)


def get_rulepack(rulepack_id: str) -> dict[str, Any] | None:
    """Return a single RulePack by ID, or None if not found."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM rulepacks WHERE rulepack_id = ?",
            (rulepack_id,),
        ).fetchone()
    if row is None:
        return None
    return _row_to_dict(row)


def list_rulepacks(*, trade_date: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """Return RulePacks ordered by creation time descending."""
    with get_connection() as conn:
        if trade_date:
            rows = conn.execute(
                "SELECT * FROM rulepacks WHERE trade_date = ? ORDER BY created_at DESC LIMIT ?",
                (trade_date, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM rulepacks ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [_row_to_dict(r) for r in rows]


def activate_rulepack(rulepack_id: str) -> dict[str, Any] | None:
    """Set a RulePack as active for its trade_date.

    Archives any previously active RulePack for the same date.
    Raises ValueError if the RulePack does not exist or validation has failed.
    """
    logger.info("START: rulepack_store.activate_rulepack rulepack_id=%s", rulepack_id)
    record = get_rulepack(rulepack_id)
    if record is None:
        raise ValueError(f"RulePack not found: {rulepack_id}")

    validation = record.get("validation", {})
    if validation.get("risk_policy") == "fail":
        raise ValueError("RulePack cannot be activated: risk_policy validation failed.")

    now = _utc_now_iso()
    trade_date = record["trade_date"]

    with get_connection() as conn:
        # Archive any currently active rulepack for the same date
        conn.execute(
            "UPDATE rulepacks SET status = 'archived' WHERE trade_date = ? AND status = 'active'",
            (trade_date,),
        )
        conn.execute(
            "UPDATE rulepacks SET status = 'active', activated_at = ? WHERE rulepack_id = ?",
            (now, rulepack_id),
        )

    logger.info("SUCCESS: rulepack_store.activate_rulepack rulepack_id=%s trade_date=%s", rulepack_id, trade_date)
    return get_rulepack(rulepack_id)


def get_active_rulepack_for_date(trade_date: str) -> dict[str, Any] | None:
    """Return the active RulePack for a given date, or None."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM rulepacks WHERE trade_date = ? AND status = 'active' LIMIT 1",
            (trade_date,),
        ).fetchone()
    if row is None:
        return None
    return _row_to_dict(row)


def update_rulepack_validation(rulepack_id: str, validation: dict[str, Any]) -> None:
    """Persist the validation result dict for a RulePack."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE rulepacks SET validation = ? WHERE rulepack_id = ?",
            (json.dumps(validation, ensure_ascii=False), rulepack_id),
        )


def _row_to_dict(row) -> dict[str, Any]:
    d = dict(row)
    for field in ("machine_rules", "validation"):
        if isinstance(d.get(field), str):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                pass
    return d
