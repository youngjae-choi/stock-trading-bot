"""Missed Opportunity Tracker."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection

logger = logging.getLogger("MissedOpportunity")


def _now_kst_iso() -> str:
    """Return the current KST timestamp for missed opportunity rows."""
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()


def _row_to_dict(row: Any) -> dict[str, Any]:
    """Convert a SQLite row into a plain dictionary for API responses."""
    return dict(row)


def _validate_required(**values: Any) -> None:
    """Validate required missed opportunity fields before persistence."""
    missing = [name for name, value in values.items() if value in (None, "")]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")


def record_missed_opportunity(
    trade_date: str,
    symbol: str,
    symbol_name: str,
    missed_stage: str,
    missed_reason: str,
    price_at_missed: float,
    max_10m: float | None = None,
    max_30m: float | None = None,
    max_eod: float | None = None,
    improvement_candidate: bool = False,
) -> dict:
    """Persist a missed opportunity and its post-miss return evidence.

    Args:
        trade_date: YYYY-MM-DD trade date.
        symbol: Stock symbol that was missed.
        symbol_name: Display name for the symbol.
        missed_stage: Pipeline stage where the symbol was missed.
        missed_reason: Human-readable missed reason.
        price_at_missed: Price observed when the opportunity was missed.
        max_10m: Maximum return after 10 minutes.
        max_30m: Maximum return after 30 minutes.
        max_eod: Maximum return until end of day.
        improvement_candidate: Whether this row should be reviewed for improvement.
    """
    logger.info("START: MissedOpportunity record symbol=%s trade_date=%s", symbol, trade_date)
    _validate_required(
        trade_date=trade_date,
        symbol=symbol,
        missed_stage=missed_stage,
        missed_reason=missed_reason,
    )
    row_id = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO missed_opportunities
                (id, trade_date, symbol, symbol_name, missed_stage, missed_reason,
                 price_at_missed, max_return_after_10m, max_return_after_30m,
                 max_return_until_eod, improvement_candidate, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row_id,
                trade_date,
                symbol,
                symbol_name or "",
                missed_stage,
                missed_reason,
                float(price_at_missed or 0.0),
                max_10m,
                max_30m,
                max_eod,
                1 if improvement_candidate else 0,
                _now_kst_iso(),
            ),
        )
        row = conn.execute("SELECT * FROM missed_opportunities WHERE id = ?", (row_id,)).fetchone()
    logger.info("SUCCESS: MissedOpportunity record id=%s symbol=%s", row_id, symbol)
    return _row_to_dict(row)


def get_today_missed(trade_date: str) -> list[dict]:
    """Return missed opportunities for one trade date.

    Args:
        trade_date: YYYY-MM-DD trade date.
    """
    logger.info("START: MissedOpportunity list trade_date=%s", trade_date)
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM missed_opportunities WHERE trade_date = ? ORDER BY created_at DESC",
            (trade_date,),
        ).fetchall()
    logger.info("SUCCESS: MissedOpportunity list trade_date=%s count=%d", trade_date, len(rows))
    return [_row_to_dict(row) for row in rows]


def get_improvement_candidates(trade_date: str) -> list[dict]:
    """Return same-day missed opportunities marked as improvement candidates.

    Args:
        trade_date: YYYY-MM-DD trade date.
    """
    logger.info("START: MissedOpportunity candidates trade_date=%s", trade_date)
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM missed_opportunities
            WHERE trade_date = ? AND improvement_candidate = 1
            ORDER BY created_at DESC
            """,
            (trade_date,),
        ).fetchall()
    logger.info("SUCCESS: MissedOpportunity candidates trade_date=%s count=%d", trade_date, len(rows))
    return [_row_to_dict(row) for row in rows]
