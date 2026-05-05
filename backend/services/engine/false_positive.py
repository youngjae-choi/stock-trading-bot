"""False Positive Tracker."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection

logger = logging.getLogger("FalsePositive")


def _now_kst_iso() -> str:
    """Return the current KST timestamp for false positive rows."""
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()


def _json_dumps(value: Any) -> str:
    """Serialize applied id lists into compact JSON text."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_loads(value: str | None) -> list[Any]:
    """Parse JSON id list text and default to an empty list when malformed."""
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except (TypeError, json.JSONDecodeError):
        return []


def _row_to_dict(row: Any) -> dict[str, Any]:
    """Convert a SQLite row and decode JSON list columns for API responses."""
    payload = dict(row)
    payload["applied_knowledge_ids"] = _json_loads(payload.get("applied_knowledge_ids"))
    payload["applied_memory_ids"] = _json_loads(payload.get("applied_memory_ids"))
    return payload


def _validate_required(**values: Any) -> None:
    """Validate required false positive fields before persistence."""
    missing = [name for name, value in values.items() if value in (None, "")]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")


def record_false_positive(
    trade_date: str,
    symbol: str,
    symbol_name: str,
    false_positive_type: str,
    original_score: float | None = None,
    original_confidence: float | None = None,
    assigned_profile: str | None = None,
    entry_reason: str = "",
    loss_reason: str = "",
    exit_reason: str = "",
    applied_knowledge_ids: list[str] | None = None,
    applied_memory_ids: list[str] | None = None,
    suggested_penalty: float | None = None,
) -> dict:
    """Persist a false positive case for later learning review.

    Args:
        trade_date: YYYY-MM-DD trade date.
        symbol: Stock symbol for the case.
        symbol_name: Display name for the symbol.
        false_positive_type: entry_fail, early_exit, or wrong_profile.
        original_score: Original screening score when available.
        original_confidence: Original AI confidence when available.
        assigned_profile: Risk profile assigned at entry time.
        entry_reason: Entry rationale text.
        loss_reason: Loss rationale text.
        exit_reason: Exit rationale text.
        applied_knowledge_ids: Expert Knowledge ids used in the decision.
        applied_memory_ids: Learning Memory ids used in the decision.
        suggested_penalty: Suggested penalty for future scoring.
    """
    logger.info("START: FalsePositive record symbol=%s trade_date=%s", symbol, trade_date)
    _validate_required(trade_date=trade_date, symbol=symbol, false_positive_type=false_positive_type)
    row_id = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO false_positive_cases
                (id, trade_date, symbol, symbol_name, false_positive_type,
                 original_score, original_confidence, assigned_profile, entry_reason,
                 loss_reason, exit_reason, applied_knowledge_ids, applied_memory_ids,
                 suggested_penalty, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row_id,
                trade_date,
                symbol,
                symbol_name or "",
                false_positive_type,
                original_score,
                original_confidence,
                assigned_profile,
                entry_reason,
                loss_reason,
                exit_reason,
                _json_dumps(applied_knowledge_ids or []),
                _json_dumps(applied_memory_ids or []),
                suggested_penalty,
                _now_kst_iso(),
            ),
        )
        row = conn.execute("SELECT * FROM false_positive_cases WHERE id = ?", (row_id,)).fetchone()
    logger.info("SUCCESS: FalsePositive record id=%s symbol=%s", row_id, symbol)
    return _row_to_dict(row)


def get_today_false_positives(trade_date: str) -> list[dict]:
    """Return false positive cases for one trade date.

    Args:
        trade_date: YYYY-MM-DD trade date.
    """
    logger.info("START: FalsePositive list trade_date=%s", trade_date)
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM false_positive_cases WHERE trade_date = ? ORDER BY created_at DESC",
            (trade_date,),
        ).fetchall()
    logger.info("SUCCESS: FalsePositive list trade_date=%s count=%d", trade_date, len(rows))
    return [_row_to_dict(row) for row in rows]
