"""Pipeline run audit helpers for preserving automatic and manual trigger sources."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from ..db import get_connection

logger = logging.getLogger("PipelineRunAudit")

TRIGGER_AUTO = "auto_scheduler"
TRIGGER_CONSOLE = "console_manual"
TRIGGER_API = "api_manual"
_ALLOWED_TRIGGERS = {TRIGGER_AUTO, TRIGGER_CONSOLE, TRIGGER_API}


def normalize_trigger_source(trigger_source: str | None, default: str = TRIGGER_API) -> str:
    """Return a known trigger source value for DB audit and logs.

    Args:
        trigger_source: Raw source from scheduler, console, or API route.
        default: Fallback source when the raw value is missing or unknown.
    """
    source = str(trigger_source or "").strip().lower()
    if source in _ALLOWED_TRIGGERS:
        return source
    safe_default = default if default in _ALLOWED_TRIGGERS else TRIGGER_API
    logger.warning("WARN: pipeline audit unknown trigger_source=%s fallback=%s", trigger_source, safe_default)
    return safe_default


def start_pipeline_run(
    *,
    trade_date: str,
    step: str,
    trigger_source: str,
    display_source: str = "",
    metadata: dict[str, Any] | None = None,
) -> str:
    """Insert a started pipeline audit row and return its run id.

    Args:
        trade_date: YYYY-MM-DD trade date.
        step: Pipeline step label such as S2, S3, S4, S5, S5-V, or S5-A.
        trigger_source: Actual origin, for example auto_scheduler or console_manual.
        display_source: Optional UI-facing source label.
        metadata: Optional JSON-serializable start metadata.
    """
    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()
    safe_source = normalize_trigger_source(trigger_source)
    logger.info("START: pipeline_run_audit step=%s trade_date=%s source=%s", step, trade_date, safe_source)
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO pipeline_run_audit
                (id, trade_date, step, trigger_source, display_source, status,
                 result_ref_id, message, metadata_json, started_at, finished_at)
            VALUES (?, ?, ?, ?, ?, 'started', '', '', ?, ?, NULL)
            """,
            (
                run_id,
                trade_date,
                step,
                safe_source,
                display_source,
                json.dumps(metadata or {}, ensure_ascii=False),
                started_at,
            ),
        )
    return run_id


def finish_pipeline_run(
    *,
    run_id: str,
    status: str,
    result_ref_id: str = "",
    message: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    """Mark a pipeline audit row completed, skipped, or failed.

    Args:
        run_id: Audit id returned by start_pipeline_run.
        status: Final status such as success, skipped, or failed.
        result_ref_id: Optional DB result id created by the step.
        message: Human-readable run result summary.
        metadata: Optional JSON-serializable result metadata.
    """
    if not run_id:
        logger.warning("WARN: pipeline_run_audit finish called without run_id status=%s", status)
        return
    finished_at = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE pipeline_run_audit
            SET status = ?, result_ref_id = ?, message = ?, metadata_json = ?, finished_at = ?
            WHERE id = ?
            """,
            (
                status,
                result_ref_id,
                message,
                json.dumps(metadata or {}, ensure_ascii=False),
                finished_at,
                run_id,
            ),
        )
    logger.info("SUCCESS: pipeline_run_audit run_id=%s status=%s result_ref_id=%s", run_id, status, result_ref_id)


def get_recent_pipeline_runs(trade_date: str, limit: int = 50) -> list[dict[str, Any]]:
    """Return recent pipeline audit rows for console and scheduler visibility.

    Args:
        trade_date: YYYY-MM-DD trade date.
        limit: Maximum number of rows to return.
    """
    safe_limit = max(1, min(int(limit or 50), 200))
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM pipeline_run_audit
            WHERE trade_date = ?
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (trade_date, safe_limit),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["metadata"] = json.loads(item.get("metadata_json") or "{}")
        except Exception:
            item["metadata"] = {}
        result.append(item)
    return result
