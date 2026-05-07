"""S10 Review & Audit — deterministic 당일 매매 결과 분석 서비스.

1600_opus_review.md는 향후/수동 LLM 복기 템플릿이며, 이 서비스는 배포 안전을
우선해 외부 LLM을 새로 호출하지 않고 DB 집계 기반 리포트를 생성한다.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection
from .order_executor import get_today_orders
from .position_integrity import create_integrity_alert_once, json_compact, summarize_order_integrity

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


def _table_exists(table_name: str) -> bool:
    """Return whether a SQLite table exists before optional review queries.

    Args:
        table_name: Table name to inspect.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
    return row is not None


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


def _safe_int(value: Any) -> int:
    """Convert numeric DB values to int while treating missing values as zero."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _load_review_signals(trade_date: str) -> list[dict[str, Any]]:
    """Load reviewable trading signals for the requested trade date.

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
              AND status IN (
                  'executed', 'failed', 'preflight_blocked',
                  'filled', 'partial_fill', 'cancelled'
              )
            ORDER BY created_at ASC
            """,
            (trade_date,),
        ).fetchall()
    return [dict(row) for row in rows]


def _load_daily_trade_summary(trade_date: str) -> dict[str, Any]:
    """Load S10 order summary values when daily_trade_summary already exists.

    Args:
        trade_date: YYYY-MM-DD trade date to load.
    """
    with get_connection() as conn:
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='daily_trade_summary'"
        ).fetchone()
        if not table_exists:
            return {}
        row = conn.execute(
            "SELECT * FROM daily_trade_summary WHERE trade_date = ? ORDER BY updated_at DESC LIMIT 1",
            (trade_date,),
        ).fetchone()
    summary = dict(row) if row else {}
    summary["symbols_traded"] = _json_loads(summary.get("symbols_traded"), [])
    summary["integrity_warnings"] = _json_loads(summary.get("integrity_warnings"), [])
    return summary


def _ensure_review_integrity_columns() -> None:
    """Add S10 integrity columns when a DB predates the latest migration."""
    migrations = [
        ("pnl_status", "ALTER TABLE daily_review_reports ADD COLUMN pnl_status TEXT NOT NULL DEFAULT 'unverified'"),
        ("pnl_source", "ALTER TABLE daily_review_reports ADD COLUMN pnl_source TEXT NOT NULL DEFAULT 'orders_without_fills'"),
        ("integrity_warnings", "ALTER TABLE daily_review_reports ADD COLUMN integrity_warnings TEXT NOT NULL DEFAULT '[]'"),
        (
            "legacy_residual_positions",
            "ALTER TABLE daily_review_reports ADD COLUMN legacy_residual_positions TEXT NOT NULL DEFAULT '[]'",
        ),
    ]
    with get_connection() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(daily_review_reports)").fetchall()}
        for column, statement in migrations:
            if column not in columns:
                conn.execute(statement)


def _order_summary(trade_date: str) -> dict[str, Any]:
    """Summarize trading_orders for Review & Audit card compatibility.

    Args:
        trade_date: YYYY-MM-DD trade date to summarize.
    """
    orders = get_today_orders(trade_date)
    status_counts: dict[str, int] = defaultdict(int)
    for order in orders:
        status_counts[str(order.get("status") or "unknown")] += 1

    return {
        "total_orders": len(orders),
        "buy_orders": sum(1 for order in orders if order.get("side") == "buy"),
        "sell_orders": sum(1 for order in orders if order.get("side") == "sell"),
        "failed_orders": status_counts.get("failed", 0),
        "submitted_orders": status_counts.get("submitted", 0),
        "filled_orders": status_counts.get("filled", 0) + status_counts.get("partial_fill", 0),
        "order_status_counts": dict(status_counts),
        "symbols_traded": sorted({str(order.get("symbol")) for order in orders if order.get("symbol")}),
    }


def _signal_status_counts(signals: list[dict[str, Any]]) -> dict[str, int]:
    """Count review signal statuses for diagnostics and UI detail text."""
    counts: dict[str, int] = defaultdict(int)
    for signal in signals:
        counts[str(signal.get("status") or "unknown")] += 1
    return dict(counts)


def _load_missed_entries(trade_date: str) -> list[dict[str, Any]]:
    """Load Missed Entries and shadow missed-entry evidence for S10 review.

    Args:
        trade_date: YYYY-MM-DD trade date to analyze.
    """
    missed: list[dict[str, Any]] = []
    with get_connection() as conn:
        if _table_exists("missed_opportunities"):
            rows = conn.execute(
                """
                SELECT id, symbol, symbol_name, missed_stage, missed_reason,
                       price_at_missed, max_return_after_10m, max_return_after_30m,
                       max_return_until_eod, improvement_candidate, created_at
                FROM missed_opportunities
                WHERE trade_date = ?
                ORDER BY created_at DESC
                """,
                (trade_date,),
            ).fetchall()
            for row in rows:
                item = dict(row)
                item["source"] = "missed_opportunities"
                missed.append(item)
        if _table_exists("shadow_trades"):
            rows = conn.execute(
                """
                SELECT id, symbol, symbol_name, missed_stage, entry_price,
                       max_return_10m, max_return_30m, max_return_eod,
                       shadow_pnl, status, created_at
                FROM shadow_trades
                WHERE trade_date = ?
                ORDER BY created_at DESC
                """,
                (trade_date,),
            ).fetchall()
            for row in rows:
                item = dict(row)
                item["source"] = "shadow_trades"
                item["missed_reason"] = item.get("status") or "shadow_tracking"
                item["price_at_missed"] = item.get("entry_price")
                item["max_return_until_eod"] = item.get("max_return_eod")
                missed.append(item)
    return missed


def _load_false_positives(trade_date: str) -> list[dict[str, Any]]:
    """Load False Positive validation cases for S10 review.

    Args:
        trade_date: YYYY-MM-DD trade date to analyze.
    """
    if not _table_exists("false_positive_cases"):
        return []
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, symbol, symbol_name, false_positive_type, original_score,
                   original_confidence, assigned_profile, entry_reason, loss_reason,
                   exit_reason, suggested_penalty, created_at
            FROM false_positive_cases
            WHERE trade_date = ?
            ORDER BY created_at DESC
            """,
            (trade_date,),
        ).fetchall()
    return [dict(row) for row in rows]


def _fallback_exit_reason(signal: dict[str, Any]) -> str:
    """Derive an actionable exit bucket when exit_reason is absent from the signal schema."""
    explicit = str(_signal_value(signal, "exit_reason", "")).strip().lower()
    if explicit:
        return explicit
    status = str(signal.get("status") or "unknown").lower()
    if status == "executed":
        return "executed_no_exit"
    if status == "failed":
        return "signal_failed"
    if status == "preflight_blocked":
        return "preflight_blocked"
    return status or "unknown"


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
    logger.info(
        "START: [S10] deterministic Review & Audit trade_date=%s prompt_template=1600_opus_review.md",
        trade_date,
    )
    _ensure_review_integrity_columns()
    now_iso = _now_kst_iso()
    signals = _load_review_signals(trade_date)
    orders = _order_summary(trade_date)
    integrity = summarize_order_integrity(trade_date)
    missed_entries = _load_missed_entries(trade_date)
    false_positives = _load_false_positives(trade_date)
    status_counts = _signal_status_counts(signals)
    if integrity.get("pnl_status") == "unverified":
        create_integrity_alert_once(
            trade_date,
            alert_type="fill_missing",
            severity="WARNING",
            title="체결/손익 검증 미완료",
            detail=json_compact(
                {
                    "pnl_source": integrity.get("pnl_source"),
                    "submitted_only_orders": integrity.get("submitted_only_orders"),
                    "pending_buy_orders": integrity.get("pending_buy_orders", []),
                    "submitted_without_order_no": integrity.get("submitted_without_order_no"),
                    "incomplete_fill_orders": integrity.get("incomplete_fill_orders", []),
                    "net_negative_positions": integrity.get("net_negative_positions", []),
                    "duplicate_sell_orders": integrity.get("duplicate_sell_orders", []),
                    "sell_qty_exceeds_buy_qty": integrity.get("sell_qty_exceeds_buy_qty", []),
                    "warnings": integrity.get("warnings", []),
                }
            ),
        )
    if (
        integrity.get("net_negative_positions")
        or integrity.get("duplicate_sell_orders")
        or integrity.get("sell_qty_exceeds_buy_qty")
    ):
        create_integrity_alert_once(
            trade_date,
            alert_type="risk_guard",
            severity="WARNING",
            title="중복 매도/순매도 이상 감지",
            detail=json_compact(
                {
                    "net_negative_positions": integrity.get("net_negative_positions", []),
                    "duplicate_sell_orders": integrity.get("duplicate_sell_orders", []),
                    "sell_qty_exceeds_buy_qty": integrity.get("sell_qty_exceeds_buy_qty", []),
                    "warnings": integrity.get("warnings", []),
                }
            ),
        )

    total_trades = len(signals)
    total_pnl = 0.0
    win_count = 0
    loss_count = 0
    profile_bucket: dict[str, dict[str, float]] = defaultdict(
        lambda: {"count": 0, "win": 0, "pnl": 0.0, "executed": 0, "failed": 0, "preflight_blocked": 0}
    )
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
        status = str(signal.get("status") or "").lower()
        if status in profile_bucket[profile]:
            profile_bucket[profile][status] += 1
        if pnl > 0:
            profile_bucket[profile]["win"] += 1

        exit_reason = _fallback_exit_reason(signal)
        exit_bucket[exit_reason]["count"] += 1
        exit_bucket[exit_reason]["pnl"] += pnl

        if exit_reason == "trailing_stop":
            entry_price = _safe_float(_signal_value(signal, "entry_price", _signal_value(signal, "trigger_price", 0.0)))
            recovery_rate = (pnl / entry_price * 100.0) if entry_price > 0 else 0.0
            trailing_recovery_rates.append(recovery_rate)
            if recovery_rate < 0.5:
                early_trailing_count += 1

    profile_summary = {
        profile: {
            "count": int(data["count"]),
            "win": int(data["win"]),
            "pnl": data["pnl"],
            "executed_count": int(data["executed"]),
            "failed_count": int(data["failed"]),
            "preflight_blocked_count": int(data["preflight_blocked"]),
        }
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
                 profile_summary, exit_summary, trailing_quality, missed_entries,
                 false_positives, missed_entries_count, false_positive_count,
                 no_trade_count, memory_count, pnl_status, pnl_source, integrity_warnings,
                 legacy_residual_positions, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
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
                _json_dumps(missed_entries),
                _json_dumps(false_positives),
                len(missed_entries),
                len(false_positives),
                no_trade_count,
                integrity.get("pnl_status", "unverified"),
                integrity.get("pnl_source", "orders_without_fills"),
                json_compact(integrity.get("warnings", [])),
                json_compact(integrity.get("legacy_residual_positions", [])),
                now_iso,
            ),
        )

    result = {
        "ok": True,
        "trade_date": trade_date,
        "total_trades": total_trades,
        "total_orders": orders["total_orders"],
        "buy_orders": orders["buy_orders"],
        "sell_orders": orders["sell_orders"],
        "failed_orders": orders["failed_orders"],
        "submitted_orders": orders["submitted_orders"],
        "filled_orders": orders["filled_orders"],
        "order_status_counts": orders["order_status_counts"],
        "signal_status_counts": status_counts,
        "win_count": win_count,
        "loss_count": loss_count,
        "total_pnl": total_pnl,
        "realized_pnl": total_pnl,
        "realized_pnl_pct": 0.0,
        "pnl_status": integrity.get("pnl_status", "unverified"),
        "pnl_source": integrity.get("pnl_source", "orders_without_fills"),
        "integrity_warnings": integrity.get("warnings", []),
        "pending_buy_orders": integrity.get("pending_buy_orders", []),
        "incomplete_fill_orders": integrity.get("incomplete_fill_orders", []),
        "net_negative_positions": integrity.get("net_negative_positions", []),
        "duplicate_sell_orders": integrity.get("duplicate_sell_orders", []),
        "sell_qty_exceeds_buy_qty": integrity.get("sell_qty_exceeds_buy_qty", []),
        "legacy_residual_positions": integrity.get("legacy_residual_positions", []),
        "profile_summary": profile_summary,
        "exit_summary": exit_summary,
        "trailing_quality": trailing_quality,
        "missed_entries": missed_entries,
        "false_positives": false_positives,
        "missed_entries_count": len(missed_entries),
        "false_positive_count": len(false_positives),
        "no_trade_count": no_trade_count,
    }
    logger.info(
        "SUCCESS: [S10] Review & Audit trade_date=%s trades=%d orders=%d missed=%d fp=%d pnl=%.4f pnl_status=%s",
        trade_date,
        total_trades,
        orders["total_orders"],
        len(missed_entries),
        len(false_positives),
        total_pnl,
        integrity.get("pnl_status"),
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
    daily_summary = _load_daily_trade_summary(trade_date)
    orders = _order_summary(trade_date)
    payload["profile_summary"] = _json_loads(payload.get("profile_summary"), {})
    payload["exit_summary"] = _json_loads(payload.get("exit_summary"), {})
    payload["trailing_quality"] = _json_loads(payload.get("trailing_quality"), {})
    payload["missed_entries"] = _json_loads(payload.get("missed_entries"), [])
    payload["false_positives"] = _json_loads(payload.get("false_positives"), [])
    payload["integrity_warnings"] = _json_loads(payload.get("integrity_warnings"), [])
    payload["legacy_residual_positions"] = _json_loads(payload.get("legacy_residual_positions"), [])
    payload["total_orders"] = _safe_int(daily_summary.get("total_orders") or orders.get("total_orders"))
    payload["buy_orders"] = _safe_int(daily_summary.get("buy_orders") or orders.get("buy_orders"))
    payload["sell_orders"] = _safe_int(daily_summary.get("sell_orders") or orders.get("sell_orders"))
    payload["failed_orders"] = _safe_int(daily_summary.get("failed_orders") or orders.get("failed_orders"))
    payload["submitted_orders"] = _safe_int(orders.get("submitted_orders"))
    payload["filled_orders"] = _safe_int(orders.get("filled_orders"))
    payload["order_status_counts"] = orders.get("order_status_counts", {})
    payload["signal_status_counts"] = _signal_status_counts(_load_review_signals(trade_date))
    payload["realized_pnl"] = _safe_float(daily_summary.get("realized_pnl") or payload.get("total_pnl"))
    payload["realized_pnl_pct"] = _safe_float(daily_summary.get("realized_pnl_pct"))
    payload["pnl_status"] = daily_summary.get("pnl_status") or payload.get("pnl_status") or "unverified"
    payload["pnl_source"] = daily_summary.get("pnl_source") or payload.get("pnl_source") or "orders_without_fills"
    if daily_summary.get("integrity_warnings"):
        payload["integrity_warnings"] = daily_summary.get("integrity_warnings")
    payload["symbols_traded"] = daily_summary.get("symbols_traded") or orders.get("symbols_traded", [])
    payload["market_tone"] = daily_summary.get("market_tone", "")
    payload["rulepack_id"] = daily_summary.get("rulepack_id", "")
    payload["profile_performance"] = []
    for row in profile_rows:
        profile_row = dict(row)
        profile_stats = payload["profile_summary"].get(str(profile_row.get("profile")), {})
        payload["profile_performance"].append(
            {
                **profile_row,
                "total_orders": _safe_int(profile_row.get("trade_count")),
                "filled_orders": _safe_int(profile_stats.get("executed_count")),
                "failed_orders": _safe_int(profile_stats.get("failed_count")),
                "preflight_blocked_orders": _safe_int(profile_stats.get("preflight_blocked_count")),
                "avg_pnl_pct": _safe_float(profile_row.get("avg_pnl")),
            }
        )
    payload["exit_reason_performance"] = [
        {
            **dict(row),
            "count": _safe_int(dict(row).get("trade_count")),
            "avg_pnl_pct": _safe_float(dict(row).get("avg_pnl")),
        }
        for row in exit_rows
    ]
    payload["trailing_quality_daily"] = dict(trailing_row) if trailing_row else None
    logger.info("SUCCESS: [S10] get_review_report trade_date=%s", trade_date)
    return payload
