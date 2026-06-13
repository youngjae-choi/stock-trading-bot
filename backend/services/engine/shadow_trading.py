"""Shadow Trading — 미진입 종목 가상 추적."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection

logger = logging.getLogger("ShadowTrading")


def _now_kst_iso() -> str:
    """Return the current KST timestamp for Shadow Trading rows."""
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()


def _row_to_dict(row: Any) -> dict[str, Any]:
    """Convert a SQLite row into a plain dictionary for API responses."""
    return dict(row)


def _validate_required(**values: Any) -> None:
    """Validate required Shadow Trading input fields before writing to SQLite."""
    missing = [name for name, value in values.items() if value in (None, "")]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")


def create_shadow_trade(
    trade_date: str,
    symbol: str,
    symbol_name: str,
    missed_stage: str,
    entry_price: float,
    entry_time: str,
) -> dict:
    """Create an active shadow trade for a missed entry candidate.

    Args:
        trade_date: YYYY-MM-DD trade date.
        symbol: Stock symbol to track.
        symbol_name: Display name for the symbol.
        missed_stage: Pipeline stage where the symbol was missed.
        entry_price: Virtual entry price.
        entry_time: Virtual entry timestamp.
    """
    logger.info("START: ShadowTrading create symbol=%s trade_date=%s", symbol, trade_date)
    _validate_required(trade_date=trade_date, symbol=symbol, missed_stage=missed_stage, entry_time=entry_time)
    trade_id = str(uuid.uuid4())
    created_at = _now_kst_iso()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO shadow_trades
                (id, trade_date, symbol, symbol_name, missed_stage, entry_price,
                 entry_time, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)
            """,
            (trade_id, trade_date, symbol, symbol_name or "", missed_stage, float(entry_price or 0.0), entry_time, created_at),
        )
        row = conn.execute("SELECT * FROM shadow_trades WHERE id = ?", (trade_id,)).fetchone()
    logger.info("SUCCESS: ShadowTrading create id=%s symbol=%s", trade_id, symbol)
    return _row_to_dict(row)


def update_shadow_trade(
    shadow_trade_id: str,
    exit_price: float,
    exit_time: str,
    shadow_pnl: float,
    max_10m: float | None = None,
    max_30m: float | None = None,
    max_eod: float | None = None,
) -> dict:
    """Close a shadow trade and persist virtual return metrics.

    Args:
        shadow_trade_id: Existing shadow trade id.
        exit_price: Virtual exit price.
        exit_time: Virtual exit timestamp.
        shadow_pnl: Virtual profit/loss percentage.
        max_10m: Maximum return within 10 minutes.
        max_30m: Maximum return within 30 minutes.
        max_eod: Maximum return until end of day.
    """
    logger.info("START: ShadowTrading update id=%s", shadow_trade_id)
    _validate_required(shadow_trade_id=shadow_trade_id, exit_time=exit_time)
    created_at = _now_kst_iso()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE shadow_trades
            SET exit_price = ?,
                exit_time = ?,
                shadow_pnl = ?,
                max_return_10m = ?,
                max_return_30m = ?,
                max_return_eod = ?,
                status = 'closed'
            WHERE id = ?
            """,
            (float(exit_price or 0.0), exit_time, float(shadow_pnl or 0.0), max_10m, max_30m, max_eod, shadow_trade_id),
        )
        conn.execute(
            """
            INSERT INTO shadow_trade_events
                (id, shadow_trade_id, event_type, price, pnl, created_at)
            VALUES (?, ?, 'close', ?, ?, ?)
            """,
            (str(uuid.uuid4()), shadow_trade_id, float(exit_price or 0.0), float(shadow_pnl or 0.0), created_at),
        )
        row = conn.execute("SELECT * FROM shadow_trades WHERE id = ?", (shadow_trade_id,)).fetchone()
    if row is None:
        logger.warning("WARN: ShadowTrading update not_found id=%s", shadow_trade_id)
        raise KeyError(shadow_trade_id)
    logger.info("SUCCESS: ShadowTrading update id=%s", shadow_trade_id)
    return _row_to_dict(row)


def get_today_shadow_trades(trade_date: str) -> list[dict]:
    """Return shadow trades for one trade date.

    Args:
        trade_date: YYYY-MM-DD trade date.
    """
    logger.info("START: ShadowTrading list trade_date=%s", trade_date)
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM shadow_trades WHERE trade_date = ? ORDER BY created_at DESC",
            (trade_date,),
        ).fetchall()
    logger.info("SUCCESS: ShadowTrading list trade_date=%s count=%d", trade_date, len(rows))
    return [_row_to_dict(row) for row in rows]


def get_shadow_trades_range(start_date: str, end_date: str) -> list[dict]:
    """Return shadow trades within an inclusive trade_date range (P4 기간검색).

    Args:
        start_date: YYYY-MM-DD 시작일.
        end_date: YYYY-MM-DD 종료일.
    """
    logger.info("START: ShadowTrading range start=%s end=%s", start_date, end_date)
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM shadow_trades
            WHERE trade_date >= ? AND trade_date <= ?
            ORDER BY trade_date DESC, created_at DESC
            """,
            (start_date, end_date),
        ).fetchall()
    logger.info("SUCCESS: ShadowTrading range count=%d", len(rows))
    return [_row_to_dict(row) for row in rows]


def get_shadow_summary(trade_date: str) -> dict:
    """Aggregate same-day shadow trade performance.

    Args:
        trade_date: YYYY-MM-DD trade date.
    """
    logger.info("START: ShadowTrading summary trade_date=%s", trade_date)
    trades = get_today_shadow_trades(trade_date)
    closed = [trade for trade in trades if trade.get("shadow_pnl") is not None]
    positive_count = sum(1 for trade in closed if float(trade.get("shadow_pnl") or 0.0) > 0)
    avg_pnl = (
        sum(float(trade.get("shadow_pnl") or 0.0) for trade in closed) / len(closed)
        if closed
        else 0.0
    )
    summary = {
        "trade_date": trade_date,
        "total_count": len(trades),
        "active_count": sum(1 for trade in trades if trade.get("status") == "active"),
        "closed_count": len(closed),
        "positive_count": positive_count,
        "positive_rate": positive_count / len(closed) if closed else 0.0,
        "avg_shadow_pnl": avg_pnl,
    }
    logger.info("SUCCESS: ShadowTrading summary trade_date=%s total=%d", trade_date, len(trades))
    return summary
