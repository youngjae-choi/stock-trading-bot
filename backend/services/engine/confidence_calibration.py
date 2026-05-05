"""Confidence Calibration — confidence 구간별 실제 성과 분석."""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection

logger = logging.getLogger("ConfidenceCalibration")

BIN_ORDER = ["ge090", "80to90", "70to80", "60to70", "lt060"]
EXPECTED_WIN_RATES = {
    "ge090": 0.90,
    "80to90": 0.80,
    "70to80": 0.70,
    "60to70": 0.60,
    "lt060": 0.50,
}


def _now_kst_iso() -> str:
    """Return the current KST timestamp for calibration rows."""
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()


def _safe_float(value: Any) -> float:
    """Convert numeric values to float while treating malformed values as zero."""
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _table_columns(table_name: str) -> set[str]:
    """Read SQLite column names for compatibility with older local schemas."""
    with get_connection() as conn:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row["name"]) for row in rows}


def get_confidence_bin(confidence: float) -> str:
    """Return the configured calibration bin label for a confidence value.

    Args:
        confidence: AI confidence score between 0.0 and 1.0.
    """
    confidence_value = _safe_float(confidence)
    if confidence_value >= 0.90:
        return "ge090"
    if confidence_value >= 0.80:
        return "80to90"
    if confidence_value >= 0.70:
        return "70to80"
    if confidence_value >= 0.60:
        return "60to70"
    return "lt060"


def _load_signal_results(trade_date: str) -> list[dict[str, Any]]:
    """Load confidence and realized PnL fields required for calibration.

    Args:
        trade_date: YYYY-MM-DD trade date.
    """
    columns = _table_columns("trading_signals")
    if "realized_pnl" not in columns:
        logger.warning("WARN: ConfidenceCalibration realized_pnl column missing; returning empty result")
        return []
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT confidence, realized_pnl
            FROM trading_signals
            WHERE trade_date = ?
              AND realized_pnl IS NOT NULL
            """,
            (trade_date,),
        ).fetchall()
    return [dict(row) for row in rows]


def _update_cumulative_bin(
    conn: Any,
    bin_label: str,
    trade_count: int,
    win_count: int,
    avg_pnl: float,
    now_iso: str,
) -> None:
    """Merge one daily calibration row into the cumulative bin table."""
    current = conn.execute(
        "SELECT * FROM confidence_calibration_bins WHERE bin_label = ?",
        (bin_label,),
    ).fetchone()
    if current is None:
        return
    previous_trades = int(current["cumulative_trades"] or 0)
    previous_avg = _safe_float(current["cumulative_avg_pnl"])
    new_trades = previous_trades + trade_count
    new_avg = (
        ((previous_avg * previous_trades) + (avg_pnl * trade_count)) / new_trades
        if new_trades
        else 0.0
    )
    conn.execute(
        """
        UPDATE confidence_calibration_bins
        SET cumulative_trades = ?,
            cumulative_wins = ?,
            cumulative_avg_pnl = ?,
            last_updated = ?
        WHERE bin_label = ?
        """,
        (
            new_trades,
            int(current["cumulative_wins"] or 0) + win_count,
            new_avg,
            now_iso,
            bin_label,
        ),
    )


def run_confidence_calibration(trade_date: str) -> dict:
    """Run daily confidence calibration and persist bin-level performance.

    Args:
        trade_date: YYYY-MM-DD trade date to calibrate.
    """
    logger.info("START: ConfidenceCalibration run trade_date=%s", trade_date)
    now_iso = _now_kst_iso()
    rows = _load_signal_results(trade_date)
    buckets: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        buckets[get_confidence_bin(_safe_float(row.get("confidence")))].append(_safe_float(row.get("realized_pnl")))

    daily_rows: list[tuple[Any, ...]] = []
    results: list[dict[str, Any]] = []
    for bin_label in BIN_ORDER:
        pnl_values = buckets.get(bin_label, [])
        trade_count = len(pnl_values)
        win_count = sum(1 for pnl in pnl_values if pnl > 0)
        avg_pnl = sum(pnl_values) / trade_count if trade_count else 0.0
        expected_win_rate = EXPECTED_WIN_RATES[bin_label]
        actual_win_rate = win_count / trade_count if trade_count else 0.0
        daily_rows.append(
            (
                str(uuid.uuid4()),
                trade_date,
                bin_label,
                trade_count,
                win_count,
                avg_pnl,
                expected_win_rate,
                actual_win_rate,
                now_iso,
            )
        )
        results.append(
            {
                "bin_label": bin_label,
                "trade_count": trade_count,
                "win_count": win_count,
                "avg_pnl": avg_pnl,
                "expected_win_rate": expected_win_rate,
                "actual_win_rate": actual_win_rate,
            }
        )

    with get_connection() as conn:
        conn.execute("DELETE FROM confidence_calibration_daily WHERE trade_date = ?", (trade_date,))
        conn.executemany(
            """
            INSERT INTO confidence_calibration_daily
                (id, trade_date, bin_label, trade_count, win_count, avg_pnl,
                 expected_win_rate, actual_win_rate, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            daily_rows,
        )
        for result in results:
            _update_cumulative_bin(
                conn,
                result["bin_label"],
                result["trade_count"],
                result["win_count"],
                result["avg_pnl"],
                now_iso,
            )

    logger.info("SUCCESS: ConfidenceCalibration run trade_date=%s signals=%d", trade_date, len(rows))
    return {"ok": True, "trade_date": trade_date, "bins": results}


def get_calibration_summary(trade_date: str) -> list[dict]:
    """Return persisted confidence calibration rows for one trade date.

    Args:
        trade_date: YYYY-MM-DD trade date.
    """
    logger.info("START: ConfidenceCalibration summary trade_date=%s", trade_date)
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM confidence_calibration_daily
            WHERE trade_date = ?
            ORDER BY CASE bin_label
                WHEN 'ge090' THEN 1
                WHEN '80to90' THEN 2
                WHEN '70to80' THEN 3
                WHEN '60to70' THEN 4
                ELSE 5
            END
            """,
            (trade_date,),
        ).fetchall()
    logger.info("SUCCESS: ConfidenceCalibration summary trade_date=%s count=%d", trade_date, len(rows))
    return [dict(row) for row in rows]
