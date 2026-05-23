"""Regime Set matching service for morning-context based trading parameters."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from .db import get_connection

KST = timezone(timedelta(hours=9))
logger = logging.getLogger("RegimeSetService")


def _now_kst() -> str:
    """Return the current KST timestamp in ISO format."""
    return datetime.now(KST).isoformat()


def _today_kst() -> str:
    """Return today's KST date as YYYY-MM-DD."""
    return datetime.now(KST).strftime("%Y-%m-%d")


def _json_dumps(value: Any) -> str:
    """Serialize JSON text columns with Korean labels preserved."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_loads(value: str | None, fallback: Any) -> Any:
    """Parse a JSON text column and return fallback when legacy data is malformed."""
    try:
        return json.loads(value or "")
    except Exception:
        return fallback


def _row_to_set(row: Any) -> dict[str, Any]:
    """Convert a regime_sets SQLite row into an API/service dictionary."""
    item = dict(row)
    item["trigger_conditions"] = _json_loads(item.get("trigger_conditions"), {})
    item["settings"] = _json_loads(item.get("settings"), {})
    item["is_active"] = bool(item.get("is_active"))
    item["is_prebuilt"] = bool(item.get("is_prebuilt"))
    return item


def _row_to_application(row: Any) -> dict[str, Any]:
    """Convert a regime_set_applications SQLite row into an API dictionary."""
    item = dict(row)
    item["applied_settings"] = _json_loads(item.get("applied_settings"), {})
    return item


def get_all_sets(active_only: bool = True) -> list[dict[str, Any]]:
    """Return all regime sets, optionally filtering to active rows.

    Args:
        active_only: When true, hide inactive sets from API callers and matchers.
    """
    logger.info("START: RegimeSetService.get_all_sets active_only=%s", active_only)
    query = "SELECT * FROM regime_sets"
    params: tuple[Any, ...] = ()
    if active_only:
        query += " WHERE is_active = 1"
    query += " ORDER BY is_prebuilt DESC, priority DESC, created_at ASC"
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    items = [_row_to_set(row) for row in rows]
    logger.info("SUCCESS: RegimeSetService.get_all_sets count=%d", len(items))
    return items


def get_today_application(trade_date: str) -> dict[str, Any] | None:
    """Return the active set application already recorded for a trade date.

    Args:
        trade_date: Trading day in YYYY-MM-DD format.
    """
    logger.info("START: RegimeSetService.get_today_application trade_date=%s", trade_date)
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM regime_set_applications
            WHERE trade_date = ? AND current_flag = 1
            ORDER BY applied_at DESC, created_at DESC
            LIMIT 1
            """,
            (trade_date,),
        ).fetchone()
    if row is None:
        logger.info("SUCCESS: RegimeSetService.get_today_application empty trade_date=%s", trade_date)
        return None
    logger.info("SUCCESS: RegimeSetService.get_today_application found trade_date=%s", trade_date)
    return _row_to_application(row)


def get_today_transitions(trade_date: str) -> list[dict[str, Any]]:
    """Return all regime SET transitions for a trading day in application order.

    Args:
        trade_date: Trading day in YYYY-MM-DD format.
    """
    logger.info("START: RegimeSetService.get_today_transitions trade_date=%s", trade_date)
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM regime_set_applications
            WHERE trade_date = ?
            ORDER BY applied_at ASC, created_at ASC
            """,
            (trade_date,),
        ).fetchall()
    items = [_row_to_application(row) for row in rows]
    logger.info("SUCCESS: RegimeSetService.get_today_transitions count=%d", len(items))
    return items


def _to_float(value: Any) -> float | None:
    """Return a float for numeric input values, otherwise None."""
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _condition_passes(value: float | None, minimum: Any = None, maximum: Any = None) -> tuple[bool, bool]:
    """Evaluate optional numeric min/max conditions.

    Args:
        value: Runtime numeric value to compare.
        minimum: Optional lower bound.
        maximum: Optional upper bound.
    """
    min_value = _to_float(minimum)
    max_value = _to_float(maximum)
    has_condition = min_value is not None or max_value is not None
    if not has_condition:
        return True, False
    if value is None:
        return False, True
    if min_value is not None and value < min_value:
        return False, True
    if max_value is not None and value > max_value:
        return False, True
    return True, True


def _score_set(
    candidate: dict[str, Any],
    regime_label: str,
    vix: float | None,
    kospi_change_pct: float | None,
) -> tuple[bool, float, str]:
    """Return whether a candidate matches and its score/reason."""
    conditions = candidate.get("trigger_conditions") or {}
    expected_regime = conditions.get("regime_label")
    score = 0.0
    reasons: list[str] = []
    if expected_regime:
        if expected_regime != regime_label:
            return False, 0.0, f"regime 불일치: expected={expected_regime}, actual={regime_label}"
        score += 0.5
        reasons.append(f"regime={regime_label} 일치")
    else:
        score += 0.2
        reasons.append("regime wildcard")

    vix_ok, has_vix_condition = _condition_passes(vix, conditions.get("vix_min"), conditions.get("vix_max"))
    if not vix_ok:
        return False, 0.0, f"VIX 조건 불충족: vix={vix}, conditions={conditions}"
    if has_vix_condition:
        score += 0.2
        reasons.append(f"VIX 조건 충족({vix})")

    kospi_ok, has_kospi_condition = _condition_passes(
        kospi_change_pct,
        conditions.get("kospi_change_min"),
        conditions.get("kospi_change_max"),
    )
    if not kospi_ok:
        return False, 0.0, f"KOSPI 조건 불충족: kospi_change_pct={kospi_change_pct}, conditions={conditions}"
    if has_kospi_condition:
        score += 0.2
        reasons.append(f"KOSPI 조건 충족({kospi_change_pct})")

    if candidate.get("is_prebuilt"):
        score += min(float(candidate.get("priority") or 0) / 100.0, 0.2)
        reasons.append("prebuilt priority 가중치")

    return True, min(score, 1.0), "; ".join(reasons)


def _apply_feedback_scores(candidates: list[dict[str, Any]], conn: Any) -> list[dict[str, Any]]:
    """Apply regime_set_feedback good/bad history to candidate scores.

    Args:
        candidates: Matched set payloads containing set_id and score.
        conn: Active SQLite connection used for feedback lookups.
    """
    try:
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='regime_set_feedback'"
        ).fetchone()
        if not table_exists:
            return candidates
        for candidate in candidates:
            set_id = candidate.get("set_id") or candidate.get("id")
            bad_count = conn.execute(
                "SELECT COUNT(*) FROM regime_set_feedback WHERE set_id=? AND evaluation='bad'",
                (set_id,),
            ).fetchone()[0]
            good_count = conn.execute(
                "SELECT COUNT(*) FROM regime_set_feedback WHERE set_id=? AND evaluation='good'",
                (set_id,),
            ).fetchone()[0]
            candidate["score"] = float(candidate.get("score") or 0.0) - (bad_count * 5) + (good_count * 3)
    except Exception as exc:
        logger.warning("WARN: RegimeSetService feedback score skipped reason=%s", exc)
    return candidates


def _find_best_set(
    regime_label: str,
    vix: float | None,
    kospi_change_pct: float | None,
    trade_date: str,
) -> dict[str, Any] | None:
    """Find the best matching set without writing application state."""
    sets = get_all_sets(active_only=True)
    ordered_sets = sorted(
        sets,
        key=lambda item: (
            item.get("is_prebuilt") and item.get("prebuilt_target_date") == trade_date,
            int(item.get("priority") or 0),
            item.get("created_at") or "",
        ),
        reverse=True,
    )
    candidates: list[dict[str, Any]] = []
    for candidate in ordered_sets:
        if candidate.get("is_prebuilt") and candidate.get("prebuilt_target_date") not in (None, trade_date):
            continue
        matched, score, reason = _score_set(candidate, regime_label, vix, kospi_change_pct)
        if not matched:
            continue
        payload = {
            "set_id": candidate["id"],
            "set_name": candidate["name"],
            "match_reason": reason,
            "match_score": round(score, 4),
            "score": score,
            "applied_settings": candidate.get("settings", {}),
            "is_new": False,
            "is_prebuilt": bool(candidate.get("is_prebuilt")),
        }
        candidates.append(payload)
    if not candidates:
        return None
    with get_connection() as conn:
        candidates = _apply_feedback_scores(candidates, conn)
    candidates.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    best = candidates[0]
    best["match_score"] = round(float(best.get("score") or 0.0), 4)
    best.pop("score", None)
    return best


def _auto_settings_for_regime(regime_label: str) -> dict[str, Any]:
    """Return conservative default settings for an auto-created set."""
    if regime_label == "risk_on":
        return {
            "max_positions": 8,
            "stop_loss_rate": -0.02,
            "take_profit_rate": 0.05,
            "new_entry_allowed": True,
            "trailing_activate_profit": 0.03,
            "trailing_stop_rate": 0.015,
        }
    if regime_label in ("risk_off", "volatile"):
        return {
            "max_positions": 3,
            "stop_loss_rate": -0.015,
            "take_profit_rate": 0.03,
            "new_entry_allowed": regime_label != "volatile",
            "trailing_activate_profit": 0.02,
            "trailing_stop_rate": 0.01,
        }
    return {
        "max_positions": 6,
        "stop_loss_rate": -0.02,
        "take_profit_rate": 0.04,
        "new_entry_allowed": True,
        "trailing_activate_profit": 0.025,
        "trailing_stop_rate": 0.012,
    }


def auto_create_set(regime_label: str, vix: float | None, kospi_change_pct: float | None) -> dict[str, Any]:
    """Create and persist a new regime set when no existing set matches.

    Args:
        regime_label: Morning-context regime label.
        vix: VIX value from morning market data, when available.
        kospi_change_pct: KOSPI percentage change from morning market data, when available.
    """
    logger.warning(
        "WARN: RegimeSetService.auto_create_set regime=%s vix=%s kospi_change_pct=%s",
        regime_label,
        vix,
        kospi_change_pct,
    )
    now = _now_kst()
    set_id = f"SET-AUTO-{datetime.now(KST).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
    conditions: dict[str, Any] = {"regime_label": regime_label}
    if vix is not None:
        conditions["vix_min"] = round(max(vix - 3, 0), 2)
        conditions["vix_max"] = round(vix + 3, 2)
    if kospi_change_pct is not None:
        conditions["kospi_change_min"] = round(kospi_change_pct - 0.5, 2)
        conditions["kospi_change_max"] = round(kospi_change_pct + 0.5, 2)
    settings = _auto_settings_for_regime(regime_label)
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO regime_sets
                (id, name, description, trigger_conditions, settings,
                 is_active, is_prebuilt, priority, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, 0, 1, ?, ?)
            """,
            (
                set_id,
                f"자동 생성 Set - {regime_label}",
                "매칭 가능한 기존 Regime Set이 없어 자동 생성됨",
                _json_dumps(conditions),
                _json_dumps(settings),
                now,
                now,
            ),
        )
    logger.info("SUCCESS: RegimeSetService.auto_create_set set_id=%s", set_id)
    return {
        "set_id": set_id,
        "set_name": f"자동 생성 Set - {regime_label}",
        "match_reason": "기존 Set 조건 불일치로 자동 생성",
        "match_score": 0.4,
        "applied_settings": settings,
        "is_new": True,
        "is_prebuilt": False,
    }


def record_application(
    trade_date: str,
    matched_set: dict[str, Any],
    regime_label: str,
    vix: float | None,
    kospi_change_pct: float | None,
    trigger: str = "morning",
) -> None:
    """Record the selected regime set for a trade date as a new transition row.

    Args:
        trade_date: Trading day in YYYY-MM-DD format.
        matched_set: Match payload from _find_best_set or auto_create_set.
        regime_label: Runtime regime label.
        vix: Runtime VIX value.
        kospi_change_pct: Runtime KOSPI change percentage.
        trigger: Source of the SET application, either morning or intraday.
    """
    set_id = matched_set.get("set_id")
    if not set_id:
        raise ValueError("matched_set.set_id is required to record a regime application")
    logger.info(
        "START: RegimeSetService.record_application trade_date=%s set_id=%s trigger=%s",
        trade_date,
        set_id,
        trigger,
    )
    now = _now_kst()
    clean_trigger = trigger if trigger in ("morning", "intraday") else "morning"
    with get_connection() as conn:
        conn.execute("UPDATE regime_set_applications SET current_flag = 0 WHERE trade_date = ?", (trade_date,))
        conn.execute(
            """
            INSERT INTO regime_set_applications
                (id, trade_date, applied_at, set_id, set_name, match_reason,
                 match_score, applied_settings, regime_label, vix_value,
                 kospi_change_pct, trigger, current_flag, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                str(uuid.uuid4()),
                trade_date,
                now,
                set_id,
                matched_set.get("set_name", ""),
                matched_set.get("match_reason", ""),
                float(matched_set.get("match_score") or 0.0),
                _json_dumps(matched_set.get("applied_settings", {})),
                regime_label,
                vix,
                kospi_change_pct,
                clean_trigger,
                now,
            ),
        )
        conn.execute(
            """
            UPDATE regime_sets
            SET total_applications = total_applications + 1,
                updated_at = ?
            WHERE id = ?
            """,
            (now, set_id),
        )
    logger.info("SUCCESS: RegimeSetService.record_application trade_date=%s", trade_date)


def match_set(
    regime_label: str,
    vix: float | None,
    kospi_change_pct: float | None,
    trade_date: str,
) -> dict[str, Any]:
    """Find, record, and return the best matching regime set.

    Args:
        regime_label: Morning-context regime label.
        vix: VIX value when available.
        kospi_change_pct: KOSPI percentage change when available.
        trade_date: Trading day in YYYY-MM-DD format.
    """
    logger.info(
        "START: RegimeSetService.match_set trade_date=%s regime=%s vix=%s kospi=%s",
        trade_date,
        regime_label,
        vix,
        kospi_change_pct,
    )
    safe_regime = regime_label if regime_label in ("risk_on", "neutral", "risk_off", "volatile") else "neutral"
    matched = _find_best_set(safe_regime, _to_float(vix), _to_float(kospi_change_pct), trade_date)
    if matched is None:
        matched = auto_create_set(safe_regime, _to_float(vix), _to_float(kospi_change_pct))
    record_application(trade_date, matched, safe_regime, _to_float(vix), _to_float(kospi_change_pct))
    logger.info(
        "SUCCESS: RegimeSetService.match_set trade_date=%s set_id=%s score=%s",
        trade_date,
        matched.get("set_id"),
        matched.get("match_score"),
    )
    return matched


def update_set_result(trade_date: str, total_trades: int, win_count: int, total_pnl: float) -> None:
    """Update a day's realized result and refresh aggregate set statistics.

    Args:
        trade_date: Trading day whose application result is now known.
        total_trades: Number of completed trades.
        win_count: Number of winning trades.
        total_pnl: Realized PnL for the day.
    """
    logger.info("START: RegimeSetService.update_set_result trade_date=%s", trade_date)
    now = _now_kst()
    with get_connection() as conn:
        app = conn.execute(
            """
            SELECT set_id FROM regime_set_applications
            WHERE trade_date = ? AND current_flag = 1
            ORDER BY applied_at DESC, created_at DESC
            LIMIT 1
            """,
            (trade_date,),
        ).fetchone()
        if app is None:
            logger.warning("WARN: RegimeSetService.update_set_result application missing trade_date=%s", trade_date)
            return
        conn.execute(
            """
            UPDATE regime_set_applications
            SET total_trades = ?, win_count = ?, total_pnl = ?, result_updated_at = ?
            WHERE trade_date = ? AND current_flag = 1
            """,
            (total_trades, win_count, total_pnl, now, trade_date),
        )
        stats = conn.execute(
            """
            SELECT
                COUNT(*) AS total_applications,
                COALESCE(SUM(win_count), 0) AS win_count,
                COALESCE(SUM(total_pnl), 0.0) AS total_pnl
            FROM regime_set_applications
            WHERE set_id = ?
            """,
            (app["set_id"],),
        ).fetchone()
        conn.execute(
            """
            UPDATE regime_sets
            SET total_applications = ?, win_count = ?, total_pnl = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                int(stats["total_applications"] or 0),
                int(stats["win_count"] or 0),
                float(stats["total_pnl"] or 0.0),
                now,
                app["set_id"],
            ),
        )
    logger.info("SUCCESS: RegimeSetService.update_set_result trade_date=%s", trade_date)


def get_set_history(days: int = 30) -> list[dict[str, Any]]:
    """Return recent regime set application history.

    Args:
        days: Maximum number of recent rows to return.
    """
    safe_days = max(1, min(int(days or 30), 365))
    logger.info("START: RegimeSetService.get_set_history days=%s", safe_days)
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM regime_set_applications
            ORDER BY trade_date DESC
            LIMIT ?
            """,
            (safe_days,),
        ).fetchall()
    items = [_row_to_application(row) for row in rows]
    logger.info("SUCCESS: RegimeSetService.get_set_history count=%d", len(items))
    return items


def get_match_preview(
    regime_label: str,
    vix: float | None,
    kospi_change_pct: float | None,
    trade_date: str | None = None,
) -> dict[str, Any]:
    """Preview the regime set match without writing to the database.

    Args:
        regime_label: Candidate regime label.
        vix: Candidate VIX value.
        kospi_change_pct: Candidate KOSPI percentage change.
        trade_date: Optional target trade date. Defaults to today's KST date.
    """
    target_date = trade_date or _today_kst()
    logger.info("START: RegimeSetService.get_match_preview trade_date=%s", target_date)
    safe_regime = regime_label if regime_label in ("risk_on", "neutral", "risk_off", "volatile") else "neutral"
    matched = _find_best_set(safe_regime, _to_float(vix), _to_float(kospi_change_pct), target_date)
    if matched is None:
        matched = {
            "set_id": None,
            "set_name": "자동 생성 예정",
            "match_reason": "기존 Set 조건 불일치로 적용 시 자동 생성",
            "match_score": 0.0,
            "applied_settings": _auto_settings_for_regime(safe_regime),
            "is_new": True,
            "is_prebuilt": False,
        }
    logger.info("SUCCESS: RegimeSetService.get_match_preview set_id=%s", matched.get("set_id"))
    return matched
