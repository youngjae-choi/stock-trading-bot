"""Confidence Calibration — confidence 구간별 실제 성과 분석."""

from __future__ import annotations

import json
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection
from ..settings_store import get_setting

logger = logging.getLogger("ConfidenceCalibration")

BIN_ORDER = ["ge090", "80to90", "70to80", "60to70", "lt060"]
EXPECTED_WIN_RATES = {
    "ge090": 0.90,
    "80to90": 0.80,
    "70to80": 0.70,
    "60to70": 0.60,
    "lt060": 0.50,
}
MIN_RECOMMENDATION_TRADES = 3
UNDERPERFORMANCE_GAP = 0.15
OVERPERFORMANCE_GAP = 0.10


def _now_kst_iso() -> str:
    """Return the current KST timestamp for calibration rows."""
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()


def _safe_float(value: Any) -> float:
    """Convert numeric values to float while treating malformed values as zero."""
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _json_dumps(value: Any) -> str:
    """Serialize confidence learning evidence for S11 memory rows."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


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


def build_confidence_learning_recommendations(
    trade_date: str,
    calibration_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build recommendation-only S11 memories from confidence calibration rows.

    Args:
        trade_date: YYYY-MM-DD trade date.
        calibration_rows: Daily calibration result rows with bin-level outcomes.
    """
    logger.info("START: ConfidenceCalibration learning recommendation build trade_date=%s", trade_date)
    current_min_confidence = _safe_float(get_setting("engine.min_ai_confidence", 0.60))
    current_floor = _safe_float(get_setting("engine.min_confidence_floor", 0.40))
    created_at = _now_kst_iso()
    expires_at = (datetime.fromisoformat(f"{trade_date}T00:00:00") + timedelta(days=7)).date().isoformat()
    recommendations: list[dict[str, Any]] = []

    for row in calibration_rows:
        bin_label = str(row.get("bin_label") or "")
        trade_count = int(row.get("trade_count") or 0)
        if trade_count < MIN_RECOMMENDATION_TRADES:
            continue

        expected_win_rate = _safe_float(row.get("expected_win_rate"))
        actual_win_rate = _safe_float(row.get("actual_win_rate"))
        avg_pnl = _safe_float(row.get("avg_pnl"))
        win_rate_gap = expected_win_rate - actual_win_rate
        target_setting = "engine.min_ai_confidence"
        action = "hold_confidence_threshold"
        proposed_value = current_min_confidence
        rationale = "sample_not_extreme_enough"

        if win_rate_gap >= UNDERPERFORMANCE_GAP or avg_pnl < 0:
            action = "raise_confidence_threshold"
            rationale = "confidence_bin_underperformed"
            if bin_label == "lt060":
                target_setting = "engine.min_confidence_floor"
                proposed_value = max(current_floor, 0.60)
            elif bin_label == "60to70":
                proposed_value = max(current_min_confidence, 0.70)
            elif bin_label == "70to80":
                proposed_value = max(current_min_confidence, 0.80)
            elif bin_label == "80to90":
                proposed_value = max(current_min_confidence, 0.90)
            else:
                action = "hold_confidence_threshold"
                proposed_value = current_min_confidence
                rationale = "highest_bin_underperformed_review_required"
        elif actual_win_rate - expected_win_rate >= OVERPERFORMANCE_GAP and avg_pnl > 0:
            if bin_label in ("60to70", "70to80"):
                action = "lower_confidence_threshold"
                rationale = "confidence_bin_overperformed"
                proposed_value = min(current_min_confidence, 0.60 if bin_label == "60to70" else 0.70)
            elif bin_label == "lt060":
                action = "lower_confidence_threshold"
                rationale = "confidence_bin_overperformed"
                target_setting = "engine.min_confidence_floor"
                proposed_value = min(current_floor, 0.50)

        if action == "hold_confidence_threshold" and rationale == "sample_not_extreme_enough":
            continue

        recommendations.append(
            {
                "memory_id": str(uuid.uuid4()),
                "trade_date": trade_date,
                "scope": "S6_DECISION_ENGINE",
                "category": "confidence_calibration",
                "summary": (
                    f"Confidence bin {bin_label} recommends {action} "
                    f"(actual={actual_win_rate:.2f}, expected={expected_win_rate:.2f}, avg_pnl={avg_pnl:.4f})."
                ),
                "evidence": {
                    "bin_label": bin_label,
                    "trade_count": trade_count,
                    "win_count": int(row.get("win_count") or 0),
                    "avg_pnl": avg_pnl,
                    "expected_win_rate": expected_win_rate,
                    "actual_win_rate": actual_win_rate,
                    "win_rate_gap": win_rate_gap,
                    "current_min_ai_confidence": current_min_confidence,
                    "current_min_confidence_floor": current_floor,
                    "source": "confidence_calibration_daily",
                },
                "recommendation": {
                    "action": action,
                    "target_setting": target_setting,
                    "current_value": current_floor if target_setting.endswith("floor") else current_min_confidence,
                    "proposed_value": proposed_value,
                    "reason": rationale,
                    "application_mode": "recommendation_only",
                },
                "auto_apply_allowed": 0,
                "requires_approval": 1,
                "status": "active",
                "expires_at": expires_at,
                "created_at": created_at,
            }
        )

    logger.info(
        "SUCCESS: ConfidenceCalibration learning recommendation build trade_date=%s count=%d",
        trade_date,
        len(recommendations),
    )
    return recommendations


def persist_confidence_learning_recommendations(
    trade_date: str,
    recommendations: list[dict[str, Any]],
) -> None:
    """Persist confidence calibration recommendations as S11 learning memories.

    Args:
        trade_date: YYYY-MM-DD trade date.
        recommendations: Memory rows from `build_confidence_learning_recommendations`.
    """
    logger.info(
        "START: ConfidenceCalibration learning recommendation persist trade_date=%s count=%d",
        trade_date,
        len(recommendations),
    )
    with get_connection() as conn:
        conn.execute(
            """
            DELETE FROM learning_memories
            WHERE trade_date = ?
              AND scope = 'S6_DECISION_ENGINE'
              AND category = 'confidence_calibration'
            """,
            (trade_date,),
        )
        conn.executemany(
            """
            INSERT INTO learning_memories
                (memory_id, trade_date, scope, category, summary, evidence,
                 recommendation, auto_apply_allowed, requires_approval, status,
                 expires_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item["memory_id"],
                    item["trade_date"],
                    item["scope"],
                    item["category"],
                    item["summary"],
                    _json_dumps(item["evidence"]),
                    _json_dumps(item["recommendation"]),
                    item["auto_apply_allowed"],
                    item["requires_approval"],
                    item["status"],
                    item["expires_at"],
                    item["created_at"],
                )
                for item in recommendations
            ],
        )
    logger.info(
        "SUCCESS: ConfidenceCalibration learning recommendation persist trade_date=%s count=%d",
        trade_date,
        len(recommendations),
    )


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

    recommendations = build_confidence_learning_recommendations(trade_date, results)
    persist_confidence_learning_recommendations(trade_date, recommendations)

    logger.info("SUCCESS: ConfidenceCalibration run trade_date=%s signals=%d", trade_date, len(rows))
    return {"ok": True, "trade_date": trade_date, "bins": results, "recommendations": recommendations}


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
