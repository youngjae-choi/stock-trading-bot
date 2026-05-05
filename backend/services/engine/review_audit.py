"""S10 Review & Audit — 당일 매매 결과 분석 서비스."""

from __future__ import annotations

import json
import logging
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection

logger = logging.getLogger("ReviewAudit")


def _now_kst_iso() -> str:
    """Return the current KST timestamp for audit rows."""
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()


def _json_dumps(value: Any) -> str:
    """Serialize review payloads into compact JSON text."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_loads(value: str | None, default: Any) -> Any:
    """Parse JSON text columns and return a stable default on malformed data."""
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _table_columns(table_name: str) -> set[str]:
    """Read SQLite column names for defensive compatibility with older schemas."""
    with get_connection() as conn:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row["name"]) for row in rows}


def _signal_value(row: dict[str, Any], column: str, default: Any) -> Any:
    """Return a signal field only when the current trading_signals schema exposes it."""
    value = row.get(column)
    return default if value in (None, "") else value


def _safe_float(value: Any) -> float:
    """Convert numeric DB values to float while treating missing values as zero."""
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _load_review_signals(trade_date: str) -> list[dict[str, Any]]:
    """Load filled or blocked trading signals for the requested trade date.

    Args:
        trade_date: YYYY-MM-DD trade date to review.
    """
    columns = _table_columns("trading_signals")
    select_columns = [
        "id",
        "trade_date",
        "symbol",
        "status",
        "created_at",
    ]
    for optional in ("realized_pnl", "risk_profile", "profile_assigned", "exit_reason", "entry_price", "trigger_price"):
        if optional in columns:
            select_columns.append(optional)

    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT {", ".join(select_columns)}
            FROM trading_signals
            WHERE trade_date = ?
              AND status IN ('filled', 'partial_fill', 'preflight_blocked', 'cancelled')
            ORDER BY created_at ASC
            """,
            (trade_date,),
        ).fetchall()
    return [dict(row) for row in rows]


def _replace_daily_rows(table_name: str, trade_date: str, rows: list[tuple[Any, ...]], columns: str) -> None:
    """Replace date-scoped aggregate rows in one transaction.

    Args:
        table_name: Target aggregate table name.
        trade_date: YYYY-MM-DD trade date whose rows should be replaced.
        rows: Positional values matching ``columns``.
        columns: Comma-separated target columns for the INSERT statement.
    """
    placeholders = ",".join("?" for _ in columns.split(","))
    with get_connection() as conn:
        conn.execute(f"DELETE FROM {table_name} WHERE trade_date = ?", (trade_date,))
        if rows:
            conn.executemany(
                f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})",
                rows,
            )


async def run_review_audit(trade_date: str) -> dict:
    """Run S10 daily review aggregation and persist the report.

    Args:
        trade_date: YYYY-MM-DD trade date to analyze.
    """
    logger.info("START: [S10] Review & Audit trade_date=%s", trade_date)
    now_iso = _now_kst_iso()
    signals = _load_review_signals(trade_date)

    total_trades = len(signals)
    total_pnl = 0.0
    win_count = 0
    loss_count = 0
    profile_bucket: dict[str, dict[str, float]] = defaultdict(lambda: {"count": 0, "win": 0, "pnl": 0.0})
    exit_bucket: dict[str, dict[str, float]] = defaultdict(lambda: {"count": 0, "pnl": 0.0})
    trailing_recovery_rates: list[float] = []
    early_trailing_count = 0

    for signal in signals:
        pnl = _safe_float(signal.get("realized_pnl"))
        total_pnl += pnl
        if pnl > 0:
            win_count += 1
        else:
            loss_count += 1

        profile = str(
            _signal_value(signal, "risk_profile", _signal_value(signal, "profile_assigned", "UNKNOWN"))
        )
        profile_bucket[profile]["count"] += 1
        profile_bucket[profile]["pnl"] += pnl
        if pnl > 0:
            profile_bucket[profile]["win"] += 1

        exit_reason = str(_signal_value(signal, "exit_reason", "unknown")).lower()
        exit_bucket[exit_reason]["count"] += 1
        exit_bucket[exit_reason]["pnl"] += pnl

        if exit_reason == "trailing_stop":
            entry_price = _safe_float(_signal_value(signal, "entry_price", _signal_value(signal, "trigger_price", 0.0)))
            recovery_rate = (pnl / entry_price * 100.0) if entry_price > 0 else 0.0
            trailing_recovery_rates.append(recovery_rate)
            if recovery_rate < 0.5:
                early_trailing_count += 1

    profile_summary = {
        profile: {"count": int(data["count"]), "win": int(data["win"]), "pnl": data["pnl"]}
        for profile, data in profile_bucket.items()
    }
    exit_summary = {
        reason: {
            "count": int(data["count"]),
            "avg_pnl": data["pnl"] / data["count"] if data["count"] else 0.0,
        }
        for reason, data in exit_bucket.items()
    }
    trailing_quality = {
        "avg_recovery_rate": sum(trailing_recovery_rates) / len(trailing_recovery_rates)
        if trailing_recovery_rates
        else 0.0,
        "early_exit_rate": early_trailing_count / len(trailing_recovery_rates)
        if trailing_recovery_rates
        else 0.0,
    }

    profile_rows = [
        (
            str(uuid.uuid4()),
            trade_date,
            profile,
            int(data["count"]),
            int(data["win"]),
            data["pnl"],
            data["pnl"] / data["count"] if data["count"] else 0.0,
            now_iso,
        )
        for profile, data in profile_bucket.items()
    ]
    _replace_daily_rows(
        "profile_performance_daily",
        trade_date,
        profile_rows,
        "id,trade_date,profile,trade_count,win_count,total_pnl,avg_pnl,created_at",
    )

    exit_rows = [
        (
            str(uuid.uuid4()),
            trade_date,
            reason,
            int(data["count"]),
            data["pnl"] / data["count"] if data["count"] else 0.0,
            now_iso,
        )
        for reason, data in exit_bucket.items()
    ]
    _replace_daily_rows(
        "exit_reason_performance_daily",
        trade_date,
        exit_rows,
        "id,trade_date,exit_reason,trade_count,avg_pnl,created_at",
    )

    _replace_daily_rows(
        "trailing_quality_daily",
        trade_date,
        [
            (
                str(uuid.uuid4()),
                trade_date,
                trailing_quality["avg_recovery_rate"],
                trailing_quality["early_exit_rate"],
                len(trailing_recovery_rates),
                now_iso,
            )
        ],
        "id,trade_date,avg_recovery_rate,early_exit_rate,total_trailing_exits,created_at",
    )

    no_trade_count = 1 if total_trades == 0 else 0
    with get_connection() as conn:
        conn.execute("DELETE FROM no_trade_daily_reasons WHERE trade_date = ?", (trade_date,))
        if no_trade_count:
            conn.execute(
                """
                INSERT INTO no_trade_daily_reasons (id, trade_date, reason, detail, created_at)
                VALUES (?, ?, 'no_candidates', ?, ?)
                """,
                (str(uuid.uuid4()), trade_date, "S10 review found no completed trading signals.", now_iso),
            )
        conn.execute("DELETE FROM daily_review_reports WHERE trade_date = ?", (trade_date,))
        conn.execute(
            """
            INSERT INTO daily_review_reports
                (id, trade_date, total_trades, win_count, loss_count, total_pnl,
                 profile_summary, exit_summary, trailing_quality, no_trade_count,
                 memory_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                str(uuid.uuid4()),
                trade_date,
                total_trades,
                win_count,
                loss_count,
                total_pnl,
                _json_dumps(profile_summary),
                _json_dumps(exit_summary),
                _json_dumps(trailing_quality),
                no_trade_count,
                now_iso,
            ),
        )

    result = {
        "ok": True,
        "trade_date": trade_date,
        "total_trades": total_trades,
        "win_count": win_count,
        "loss_count": loss_count,
        "total_pnl": total_pnl,
        "profile_summary": profile_summary,
        "exit_summary": exit_summary,
        "trailing_quality": trailing_quality,
        "no_trade_count": no_trade_count,
    }
    logger.info(
        "SUCCESS: [S10] Review & Audit trade_date=%s trades=%d pnl=%.4f",
        trade_date,
        total_trades,
        total_pnl,
    )
    return result


def get_review_report(trade_date: str) -> dict | None:
    """Return the persisted S10 review report for a trade date.

    Args:
        trade_date: YYYY-MM-DD trade date to fetch.
    """
    logger.info("START: [S10] get_review_report trade_date=%s", trade_date)
    with get_connection() as conn:
        report = conn.execute(
            "SELECT * FROM daily_review_reports WHERE trade_date = ? ORDER BY created_at DESC LIMIT 1",
            (trade_date,),
        ).fetchone()
        if not report:
            logger.info("INFO: [S10] report not found trade_date=%s", trade_date)
            return None

        profile_rows = conn.execute(
            "SELECT * FROM profile_performance_daily WHERE trade_date = ? ORDER BY profile ASC",
            (trade_date,),
        ).fetchall()
        exit_rows = conn.execute(
            "SELECT * FROM exit_reason_performance_daily WHERE trade_date = ? ORDER BY exit_reason ASC",
            (trade_date,),
        ).fetchall()
        trailing_row = conn.execute(
            "SELECT * FROM trailing_quality_daily WHERE trade_date = ? ORDER BY created_at DESC LIMIT 1",
            (trade_date,),
        ).fetchone()

    payload = dict(report)
    payload["profile_summary"] = _json_loads(payload.get("profile_summary"), {})
    payload["exit_summary"] = _json_loads(payload.get("exit_summary"), {})
    payload["trailing_quality"] = _json_loads(payload.get("trailing_quality"), {})
    payload["profile_performance"] = [dict(row) for row in profile_rows]
    payload["exit_reason_performance"] = [dict(row) for row in exit_rows]
    payload["trailing_quality_daily"] = dict(trailing_row) if trailing_row else None
    logger.info("SUCCESS: [S10] get_review_report trade_date=%s", trade_date)
    return payload
