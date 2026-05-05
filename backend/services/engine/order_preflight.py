"""S6-P Order Pre-Flight Check — KIS 주문 직전 안전 검증."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection
from ..settings_store import get_setting

logger = logging.getLogger("OrderPreflight")

PREFLIGHT_OK = "ok"
PREFLIGHT_BLOCK = "block"


def _now_kst() -> datetime:
    """Return the current Asia/Seoul datetime for market-hour checks."""
    return datetime.now(ZoneInfo("Asia/Seoul"))


def _now_utc_iso() -> str:
    """Return a UTC ISO timestamp for persisted preflight records."""
    return datetime.now(timezone.utc).isoformat()


def _to_float(value: Any, default: float = 0.0) -> float:
    """Convert rule and signal numeric values to float with a safe fallback."""
    try:
        return float(str(value).replace(",", "").strip() or default)
    except (TypeError, ValueError):
        return default


def _to_float_or_none(value: Any) -> float | None:
    """Convert DB values to float only when the source contains a real number.

    Args:
        value: Raw SQLite or KIS-derived numeric value.
    """
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _today_kst() -> str:
    """Return today's Asia/Seoul date for daily risk lookups."""
    return _now_kst().strftime("%Y-%m-%d")


def _table_exists(conn: Any, table_name: str) -> bool:
    """Return whether a SQLite table exists before optional source queries.

    Args:
        conn: Open SQLite connection.
        table_name: Table name to check.
    """
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _table_columns(conn: Any, table_name: str) -> set[str]:
    """Return a table's column names for compatibility with older schemas.

    Args:
        conn: Open SQLite connection.
        table_name: Table name to inspect.
    """
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _daily_loss_limit_percent(final_rule: dict[str, Any]) -> float:
    """Read the active daily-loss percent from final_rule or Settings.

    Args:
        final_rule: Resolved symbol rule from S5/S6.
    """
    for key in ("daily_loss_limit", "daily_loss_limit_rate", "daily_loss_limit_pct"):
        rule_value = _to_float_or_none(final_rule.get(key))
        if rule_value is not None:
            return _normalize_loss_limit_percent(rule_value, positive_is_loss=key == "daily_loss_limit_pct")
    try:
        setting_value = _to_float_or_none(get_setting("risk.daily_loss_limit_percent", -2.0))
    except Exception as exc:
        logger.warning("WARN: [S6-P] daily loss setting read failed; using default reason=%s", exc)
        setting_value = None
    return _normalize_loss_limit_percent(setting_value) if setting_value is not None else -2.0


def _normalize_loss_limit_percent(value: float, positive_is_loss: bool = False) -> float:
    """Normalize daily loss limit rates and percent values to signed percent.

    Args:
        value: Daily loss limit from RulePack or Settings. Values like -0.02 are
            rates, while values like -2 are already percent.
        positive_is_loss: Whether positive percent inputs represent max loss
            magnitude from an explicit pct schema.
    """
    if -1.0 < value < 1.0 and value != 0:
        normalized = value * 100.0
    else:
        normalized = value
    if positive_is_loss and normalized > 0:
        return -normalized
    return normalized


def _percent_from_krw(realized_pnl_krw: float | None, equity_krw: float | None) -> float | None:
    """Convert realized KRW PnL to percent only when equity is known.

    Args:
        realized_pnl_krw: Realized profit/loss in KRW.
        equity_krw: Account equity or total evaluated amount in KRW.
    """
    if realized_pnl_krw is None or equity_krw is None or equity_krw <= 0:
        return None
    return realized_pnl_krw / equity_krw * 100.0


def _latest_account_snapshot_loss(
    conn: Any,
    trade_date: str,
) -> tuple[float | None, float | None, float | None, str, str]:
    """Return account-level daily PnL percent from the latest account snapshot.

    Args:
        conn: Open SQLite connection.
        trade_date: YYYY-MM-DD date used for account snapshot lookup.
    """
    if not _table_exists(conn, "account_snapshots"):
        return None, None, None, "account_snapshots.missing", "account_snapshot_table_missing"

    columns = _table_columns(conn, "account_snapshots")
    row = conn.execute(
        """
        SELECT * FROM account_snapshots
        WHERE date(captured_at) = ?
        ORDER BY captured_at DESC
        LIMIT 1
        """,
        (trade_date,),
    ).fetchone()
    if not row:
        return None, None, None, "account_snapshots.empty", "account_snapshot_missing_for_date"

    observed_krw = _to_float_or_none(row["day_pnl"]) if "day_pnl" in columns else None
    equity_krw = _to_float_or_none(row["equity"]) if "equity" in columns else None
    observed_percent = _percent_from_krw(observed_krw, equity_krw)
    reason = "account_day_pnl_equity_available" if observed_percent is not None else "account_equity_or_day_pnl_missing"
    return observed_percent, observed_krw, equity_krw, "account_snapshots.day_pnl/equity", reason


def evaluate_daily_loss_limit(final_rule: dict[str, Any], trade_date: str | None = None) -> dict[str, Any]:
    """Evaluate whether today's realized PnL has breached the configured loss limit.

    Args:
        final_rule: Resolved symbol rule containing risk settings.
        trade_date: Optional YYYY-MM-DD date used by tests and historical checks.
    """
    logger.info("START: [S6-P] daily loss guard evaluation")
    safe_trade_date = trade_date or _today_kst()
    limit_percent = _daily_loss_limit_percent(final_rule)
    if limit_percent >= 0:
        logger.warning(
            "WARN: [S6-P] daily loss limit is non-negative; guard will not block limit=%.4f",
            limit_percent,
        )
        return {
            "breached": False,
            "limit_percent": limit_percent,
            "observed_percent": None,
            "source": "settings_invalid_non_negative",
            "reason": "daily_loss_limit_percent_non_negative",
        }

    observed_percent: float | None = None
    observed_krw: float | None = None
    equity_krw: float | None = None
    source = "missing"
    reason = "no_realized_pnl_source"

    try:
        with get_connection() as conn:
            observed_percent, observed_krw, equity_krw, source, reason = _latest_account_snapshot_loss(
                conn,
                safe_trade_date,
            )

            if observed_percent is None and equity_krw is not None and _table_exists(conn, "daily_trade_summary"):
                columns = _table_columns(conn, "daily_trade_summary")
                order_column = "updated_at" if "updated_at" in columns else "trade_date"
                row = conn.execute(
                    f"SELECT * FROM daily_trade_summary WHERE trade_date = ? ORDER BY {order_column} DESC LIMIT 1",
                    (safe_trade_date,),
                ).fetchone()
                if row and "realized_pnl" in columns:
                    observed_krw = _to_float_or_none(row["realized_pnl"])
                    observed_percent = _percent_from_krw(observed_krw, equity_krw)
                    source = "daily_trade_summary.realized_pnl/equity"
                    reason = (
                        "summary_krw_equity_source_available"
                        if observed_percent is not None
                        else "summary_krw_missing"
                    )

            if observed_percent is None and _table_exists(conn, "trading_signals"):
                columns = _table_columns(conn, "trading_signals")
                if "realized_pnl" in columns and equity_krw is not None:
                    row = conn.execute(
                        """
                        SELECT SUM(realized_pnl) AS realized_pnl
                        FROM trading_signals
                        WHERE trade_date = ?
                          AND realized_pnl IS NOT NULL
                        """,
                        (safe_trade_date,),
                    ).fetchone()
                    observed_krw = _to_float_or_none(row["realized_pnl"] if row else None)
                    observed_percent = _percent_from_krw(observed_krw, equity_krw)
                    source = "trading_signals.realized_pnl/equity"
                    reason = "signal_krw_equity_source_available" if observed_percent is not None else "signal_equity_missing"
                elif "realized_pnl" in columns:
                    source = "trading_signals.realized_pnl"
                    reason = "signal_krw_available_but_equity_missing"
    except Exception as exc:
        logger.error("FAIL: [S6-P] daily loss guard source query failed reason=%s", exc)
        return {
            "breached": False,
            "limit_percent": limit_percent,
            "observed_percent": None,
            "observed_krw": observed_krw,
            "equity_krw": equity_krw,
            "source": "query_failed",
            "reason": str(exc),
        }

    breached = observed_percent is not None and observed_percent <= limit_percent
    if breached:
        logger.warning(
            "BLOCK: [S6-P] daily loss limit breached source=%s observed=%.4f limit=%.4f",
            source,
            observed_percent,
            limit_percent,
        )
    elif observed_percent is None:
        logger.warning(
            "WARN: [S6-P] daily loss guard non-blocking missing percent source=%s reason=%s limit=%.4f",
            source,
            reason,
            limit_percent,
        )
    else:
        logger.info(
            "SUCCESS: [S6-P] daily loss guard ok source=%s observed=%.4f limit=%.4f",
            source,
            observed_percent,
            limit_percent,
        )

    return {
        "breached": breached,
        "limit_percent": limit_percent,
        "observed_percent": observed_percent,
        "observed_krw": observed_krw,
        "equity_krw": equity_krw,
        "source": source,
        "reason": reason,
    }


def _position_size_pct(final_rule: dict[str, Any]) -> float:
    """Return position size percent from flat final_rule keys."""
    if "position_size_pct" in final_rule:
        return _to_float(final_rule.get("position_size_pct"), 100.0)
    max_position_rate = _to_float(final_rule.get("max_position_rate"), 0.0)
    if 0 < max_position_rate <= 1:
        return max_position_rate * 100
    if max_position_rate > 1:
        return max_position_rate
    return 100.0


def _time_from_rule(value: Any, fallback: tuple[int, int]) -> tuple[int, int]:
    """Return hour and minute parsed from an HH:MM or HH:MM:SS rule value."""
    text = str(value or "").strip()
    parts = text.split(":")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return int(parts[0]), int(parts[1])
    return fallback


def is_new_buy_blocked_by_emergency_halt() -> tuple[bool, str]:
    """Return whether emergency halt state must block a new BUY order.

    The guard is fail-closed for new entries: persistent Settings and the
    console cached fallback are both checked, and any lookup uncertainty blocks
    only new BUY orders while leaving SELL/liquidation paths outside this guard.
    """
    setting_enabled = False
    setting_error: Exception | None = None
    cached_enabled = False
    cached_error: Exception | None = None

    try:
        emergency_halt = get_setting("risk.emergency_halt_enabled", False)
        setting_enabled = emergency_halt is True or str(emergency_halt).lower() == "true"
    except Exception as exc:
        setting_error = exc
        logger.error("FAIL: [S6-P] emergency halt persistent setting read failed reason=%s", exc)

    try:
        from ..console_state import get_cached_emergency_halt_state

        cached_enabled = get_cached_emergency_halt_state()
    except Exception as exc:
        cached_error = exc
        logger.error("FAIL: [S6-P] emergency halt console fallback read failed reason=%s", exc)

    if setting_enabled or cached_enabled:
        return True, "emergency_halt_active"
    if setting_error is not None or cached_error is not None:
        logger.warning(
            "BLOCK: [S6-P] emergency halt status uncertain; fail-closed for new BUY setting_error=%s cached_error=%s",
            bool(setting_error),
            bool(cached_error),
        )
        return True, "emergency_halt_status_uncertain"
    return False, ""


def run_preflight(
    signal: dict[str, Any],
    final_rule: dict[str, Any],
    current_positions_count: int = 0,
) -> dict[str, Any]:
    """주문 직전 안전 검증. 반환값: {ok, preflight_id, checks, block_reason}."""
    logger.info("START: [S6-P] preflight signal_id=%s symbol=%s", signal.get("id"), signal.get("symbol"))
    checks: dict[str, str] = {}
    block_reasons: list[str] = []

    now = _now_kst()

    # 1. 긴급정지 상태 확인. 활성화 시 신규 BUY 주문은 무조건 차단한다.
    emergency_halt_blocked, emergency_halt_reason = is_new_buy_blocked_by_emergency_halt()
    if emergency_halt_blocked:
        checks["emergency_halt"] = PREFLIGHT_BLOCK
        if emergency_halt_reason == "emergency_halt_status_uncertain":
            block_reasons.append("긴급정지 상태 확인 불가 — 신규 주문 안전 차단")
        else:
            block_reasons.append("긴급정지 활성화 — 신규 주문 차단")
    else:
        checks["emergency_halt"] = PREFLIGHT_OK

    # 2. 장 운영 시간 및 설정된 신규매수 금지 시간 확인
    market_open = now.replace(hour=9, minute=0, second=0, microsecond=0)
    cutoff_hour, cutoff_minute = _time_from_rule(final_rule.get("new_entry_cutoff_time"), (15, 20))
    entry_cutoff = now.replace(hour=cutoff_hour, minute=cutoff_minute, second=0, microsecond=0)
    if not (market_open <= now < entry_cutoff):
        checks["market_hours"] = PREFLIGHT_BLOCK
        block_reasons.append(f"신규매수 시간 외 (09:00~{cutoff_hour:02d}:{cutoff_minute:02d})")
    else:
        checks["market_hours"] = PREFLIGHT_OK

    # 3. 종목당 최대 비중 (final_rule에서 position_size_pct 한도 확인)
    position_size_pct = _position_size_pct(final_rule)
    if position_size_pct > 30.0:
        checks["position_size"] = PREFLIGHT_BLOCK
        block_reasons.append(f"position_size_pct={position_size_pct} 초과 (최대 30%)")
    else:
        checks["position_size"] = PREFLIGHT_OK

    # 4. 최대 보유 종목 수 초과
    max_positions = int(_to_float(final_rule.get("max_positions"), 10.0) or 10)
    if current_positions_count >= max_positions:
        checks["max_positions"] = PREFLIGHT_BLOCK
        block_reasons.append(f"최대 보유 종목 도달 ({current_positions_count}/{max_positions})")
    else:
        checks["max_positions"] = PREFLIGHT_OK

    # 5. 트리거 가격 유효성
    trigger_price = _to_float(signal.get("trigger_price"))
    if trigger_price <= 0:
        checks["price_valid"] = PREFLIGHT_BLOCK
        block_reasons.append("trigger_price 유효하지 않음")
    else:
        checks["price_valid"] = PREFLIGHT_OK

    # 6. 신뢰도 최소값 (final_rule)
    ai_conf_min = _to_float(final_rule.get("ai_confidence_min"), 0.0)
    confidence = _to_float(signal.get("confidence"), 0.0)
    if confidence < ai_conf_min:
        checks["ai_confidence"] = PREFLIGHT_BLOCK
        block_reasons.append(f"confidence={confidence:.2f} < 최소 {ai_conf_min:.2f}")
    else:
        checks["ai_confidence"] = PREFLIGHT_OK

    # 7. 당일 실현손실 한도. 증명 가능한 percent breach가 있을 때만 신규 BUY를 차단한다.
    daily_loss = evaluate_daily_loss_limit(final_rule)
    if daily_loss["breached"]:
        checks["daily_loss_limit"] = PREFLIGHT_BLOCK
        block_reasons.append(
            "일일 손실한도 도달 "
            f"({daily_loss['observed_percent']:.2f}% <= {daily_loss['limit_percent']:.2f}%)"
        )
    else:
        checks["daily_loss_limit"] = PREFLIGHT_OK

    passed = len(block_reasons) == 0
    preflight_id = str(uuid.uuid4())
    created_at = _now_utc_iso()

    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO order_preflight_checks
                    (id, signal_id, symbol, checks, block_reasons, result, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    preflight_id,
                    str(signal.get("id") or ""),
                    str(signal.get("symbol") or ""),
                    json.dumps(checks, ensure_ascii=False),
                    "|".join(block_reasons),
                    PREFLIGHT_OK if passed else PREFLIGHT_BLOCK,
                    created_at,
                ),
            )
    except Exception as exc:
        logger.warning("WARN: [S6-P] preflight DB save failed reason=%s", exc)

    if passed:
        logger.info("SUCCESS: [S6-P] preflight ok signal_id=%s symbol=%s", signal.get("id"), signal.get("symbol"))
    else:
        logger.warning(
            "BLOCK: [S6-P] preflight signal_id=%s symbol=%s reasons=%s",
            signal.get("id"),
            signal.get("symbol"),
            block_reasons,
        )

    return {
        "ok": passed,
        "preflight_id": preflight_id,
        "checks": checks,
        "block_reason": block_reasons[0] if block_reasons else None,
        "block_reasons": block_reasons,
    }
