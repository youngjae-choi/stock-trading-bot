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
from .daily_capital import get_baseline, get_active_budget_rate, get_cumulative_buy_amount

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


def _deployment_blocked(deployed: float, total_eval: float, target: float) -> bool:
    """탐색 배포 한도 게이트: 배포율(deployed/total_eval) >= target 이면 True."""
    if total_eval <= 0:
        return False
    return (deployed / total_eval) >= target


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


def _is_market_hours(now: datetime | None = None) -> bool:
    """KST 정규장(09:00~15:30) 여부 — fail-closed 차단 판단에만 사용한다.

    Args:
        now: 테스트 주입용 현재 시각. 기본은 KST now.
    """
    current = now or _now_kst()
    open_time = current.replace(hour=9, minute=0, second=0, microsecond=0)
    close_time = current.replace(hour=15, minute=30, second=0, microsecond=0)
    return open_time <= current < close_time


def _realized_daily_pnl(trade_date: str) -> dict[str, Any]:
    """당일 실현손익 관측 (snapshot → daily_trade_summary → trading_signals 순).

    '조회 성공·데이터 없음'은 data_found=False로 반환하며 예외가 아니다.
    DB 조회 예외는 호출자에게 전파한다 (fail-closed 판단용).

    Args:
        trade_date: YYYY-MM-DD 조회 일자.

    Returns:
        {pnl_krw, equity_krw, source, data_found, includes_unrealized}
    """
    with get_connection() as conn:
        snap_pct, snap_krw, equity_krw, snap_source, _snap_reason = _latest_account_snapshot_loss(
            conn,
            trade_date,
        )
        if snap_pct is not None:
            # 계좌단위 day_pnl은 평가손익 포함 가능성이 있어 그대로 전체 관측치로 사용한다.
            return {
                "pnl_krw": snap_krw,
                "equity_krw": equity_krw,
                "source": snap_source,
                "data_found": True,
                "includes_unrealized": True,
            }

        if _table_exists(conn, "daily_trade_summary"):
            columns = _table_columns(conn, "daily_trade_summary")
            order_column = "updated_at" if "updated_at" in columns else "trade_date"
            row = conn.execute(
                f"SELECT * FROM daily_trade_summary WHERE trade_date = ? ORDER BY {order_column} DESC LIMIT 1",
                (trade_date,),
            ).fetchone()
            if row and "realized_pnl" in columns:
                realized_krw = _to_float_or_none(row["realized_pnl"])
                if realized_krw is not None:
                    return {
                        "pnl_krw": realized_krw,
                        "equity_krw": equity_krw,
                        "source": "daily_trade_summary.realized_pnl",
                        "data_found": True,
                        "includes_unrealized": False,
                    }

        if _table_exists(conn, "trading_signals"):
            columns = _table_columns(conn, "trading_signals")
            if "realized_pnl" in columns:
                row = conn.execute(
                    """
                    SELECT SUM(realized_pnl) AS realized_pnl
                    FROM trading_signals
                    WHERE trade_date = ?
                      AND realized_pnl IS NOT NULL
                    """,
                    (trade_date,),
                ).fetchone()
                realized_krw = _to_float_or_none(row["realized_pnl"] if row else None)
                if realized_krw is not None:
                    return {
                        "pnl_krw": realized_krw,
                        "equity_krw": equity_krw,
                        "source": "trading_signals.realized_pnl",
                        "data_found": True,
                        "includes_unrealized": False,
                    }

    return {
        "pnl_krw": None,
        "equity_krw": equity_krw,
        "source": "no_realized_pnl_source",
        "data_found": False,
        "includes_unrealized": False,
    }


def _unrealized_pnl_krw() -> tuple[float | None, int, int]:
    """보유 포지션 평가손익 합계(KRW) — 메모리 가격만 사용, 신규 KIS 호출 없음.

    가격 출처: position dict의 current_price/last_price 필드(있으면) →
    decision_engine._bar_engine.get_last_price(WS tick 기반 10초봉 종가).

    Returns:
        (unrealized_krw, priced_count, position_count).
        포지션 없음 → (0.0, 0, 0). 포지션은 있으나 가격 전부 미확보 → (None, 0, n).
    """
    from .position_manager import position_manager

    positions = position_manager.get_positions()
    if not positions:
        return 0.0, 0, 0

    bar_engine = None
    try:
        from .decision_engine import decision_engine

        bar_engine = getattr(decision_engine, "_bar_engine", None)
    except Exception as exc:
        logger.warning("WARN: [S6-P] bar engine unavailable for unrealized pnl reason=%s", exc)

    total_krw = 0.0
    priced = 0
    for position in positions:
        symbol = str(position.get("symbol") or "").strip()
        qty = _to_float(position.get("qty"))
        entry_price = _to_float(position.get("entry_price"))
        if not symbol or qty <= 0 or entry_price <= 0:
            continue
        price = _to_float_or_none(position.get("current_price")) or _to_float_or_none(position.get("last_price"))
        if (price is None or price <= 0) and bar_engine is not None:
            try:
                price = _to_float_or_none(bar_engine.get_last_price(symbol))
            except Exception:
                price = None
        if price is None or price <= 0:
            continue
        total_krw += (price - entry_price) * qty
        priced += 1

    if priced == 0:
        return None, 0, len(positions)
    return total_krw, priced, len(positions)


def _observed_daily_loss_percent(trade_date: str) -> tuple[float | None, str]:
    """당일 관측 손실률(%)과 출처 라벨을 반환한다.

    분자 = 실현손익 + 보유 포지션 평가손익, 분모 = equity(스냅샷) 또는 baseline(장개시 예수금).

    Returns:
        (percent, label). percent가 None인 경우 label 의미:
        - "query_failed": 실현손익 소스 전부 예외 (fail-closed 후보 — '조회 실패')
        - "no_equity_or_baseline": 분모 부재 (정상 결측 — '데이터 없음')
    """
    try:
        realized = _realized_daily_pnl(trade_date)
    except Exception as exc:
        logger.error("FAIL: [S6-P] daily loss guard source query failed reason=%s", exc)
        return None, "query_failed"

    equity_krw = realized.get("equity_krw")
    baseline_krw: float | None = None
    try:
        baseline_krw = get_baseline(trade_date)
    except Exception as exc:
        logger.warning("WARN: [S6-P] baseline lookup failed for loss guard reason=%s", exc)

    denominator: float | None = None
    denom_label = ""
    if equity_krw is not None and equity_krw > 0:
        denominator = equity_krw
        denom_label = "equity"
    elif baseline_krw is not None and baseline_krw > 0:
        denominator = baseline_krw
        denom_label = "baseline"
    if denominator is None:
        return None, "no_equity_or_baseline"

    if realized["includes_unrealized"] and realized["pnl_krw"] is not None:
        # 계좌 스냅샷 day_pnl은 이미 평가손익 포함 — 이중 합산 금지.
        return realized["pnl_krw"] / denominator * 100.0, f"{realized['source']}/{denom_label}"

    realized_krw = realized["pnl_krw"] if realized["pnl_krw"] is not None else 0.0
    source_label = realized["source"] if realized["data_found"] else f"{realized['source']}(no_data=0)"

    try:
        unrealized_krw, priced_count, position_count = _unrealized_pnl_krw()
    except Exception as exc:
        logger.warning("WARN: [S6-P] unrealized pnl computation failed; realized-only reason=%s", exc)
        unrealized_krw, priced_count, position_count = None, 0, -1

    if unrealized_krw is None:
        # 평가손익 산출 불가 — realized-only 폴백을 라벨에 명시한다.
        label = f"{source_label}+unrealized_unavailable(realized_only)/{denom_label}"
        return realized_krw / denominator * 100.0, label

    if position_count > 0:
        label = f"{source_label}+positions_unrealized({priced_count}/{position_count})/{denom_label}"
    else:
        label = f"{source_label}/{denom_label}"
    return (realized_krw + unrealized_krw) / denominator * 100.0, label


def _should_fail_closed(trade_date: str) -> bool:
    """모든 손실 소스 조회 실패 시 차단해야 하는지 판단한다.

    baseline이 존재하고(또는 baseline 조회 자체가 예외 = '조회 실패'로 안전측 간주)
    거래 시간 중일 때만 True. baseline 미기록(조회 성공·데이터 없음)은 정상 결측으로
    차단하지 않는다 — 아침 첫 매수를 막으면 안 된다.

    Args:
        trade_date: YYYY-MM-DD 조회 일자.
    """
    if not _is_market_hours():
        return False
    try:
        baseline_krw = get_baseline(trade_date)
    except Exception as exc:
        logger.warning("WARN: [S6-P] baseline lookup failed during fail-closed check reason=%s", exc)
        return True
    return baseline_krw is not None and baseline_krw > 0


def evaluate_daily_loss_limit(final_rule: dict[str, Any], trade_date: str | None = None) -> dict[str, Any]:
    """당일 손실(실현+평가)이 설정 한도를 넘었는지 평가한다.

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
            "fail_closed": False,
            "limit_percent": limit_percent,
            "observed_percent": None,
            "source": "settings_invalid_non_negative",
            "reason": "daily_loss_limit_percent_non_negative",
        }

    observed_percent, source = _observed_daily_loss_percent(safe_trade_date)

    fail_closed = False
    reason = source
    if observed_percent is None and source == "query_failed":
        fail_closed = _should_fail_closed(safe_trade_date)
        reason = "loss_sources_query_failed" + ("_fail_closed" if fail_closed else "")

    breached = observed_percent is not None and observed_percent <= limit_percent
    if breached:
        logger.warning(
            "BLOCK: [S6-P] daily loss limit breached source=%s observed=%.4f limit=%.4f",
            source,
            observed_percent,
            limit_percent,
        )
    elif fail_closed:
        logger.warning(
            "BLOCK: [S6-P] daily loss guard fail-closed — sources unavailable during market hours limit=%.4f",
            limit_percent,
        )
    elif observed_percent is None:
        logger.warning(
            "WARN: [S6-P] daily loss guard non-blocking missing percent source=%s limit=%.4f",
            source,
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
        "fail_closed": fail_closed,
        "limit_percent": limit_percent,
        "observed_percent": observed_percent,
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

    The guard is fail-closed for new entries: persistent Settings is checked,
    and any lookup uncertainty blocks only new BUY orders while leaving
    SELL/liquidation paths outside this guard.
    """
    setting_enabled = False
    setting_error: Exception | None = None
    try:
        emergency_halt = get_setting("risk.emergency_halt_enabled", False)
        setting_enabled = emergency_halt is True or str(emergency_halt).lower() == "true"
    except Exception as exc:
        setting_error = exc
        logger.error("FAIL: [S6-P] emergency halt persistent setting read failed reason=%s", exc)

    if setting_enabled:
        return True, "emergency_halt_active"
    if setting_error is not None:
        logger.warning(
            "BLOCK: [S6-P] emergency halt status uncertain; fail-closed for new BUY setting_error=%s",
            bool(setting_error),
        )
        return True, "emergency_halt_status_uncertain"
    return False, ""


def _budget_cap_check(trade_date: str | None = None) -> tuple[bool, str]:
    """당일 누적 매수액이 baseline×budget_rate 도달 시 (True, 사유). baseline 없으면 (False, '')."""
    baseline = get_baseline(trade_date)
    if not baseline or baseline <= 0:
        return False, ""
    budget = baseline * get_active_budget_rate(trade_date)
    used = get_cumulative_buy_amount(trade_date)
    if used >= budget > 0:
        return True, f"일일 투입예산 소진 ({used:,.0f}/{budget:,.0f}원)"
    return False, ""


def run_preflight(
    signal: dict[str, Any],
    final_rule: dict[str, Any],
    current_positions_count: int = 0,
    deployed_value: float = 0.0,
    total_eval: float = 0.0,
    deploy_target_rate: float = 0.0,
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

    # 4. 배포 한도/보유 종목 수
    if deploy_target_rate > 0 and total_eval > 0:
        # 탐색: 95% 배포 게이트(보유수 무관, 현금 한도로 제어)
        if _deployment_blocked(deployed_value, total_eval, deploy_target_rate):
            checks["max_positions"] = PREFLIGHT_BLOCK
            block_reasons.append(f"배포 한도 도달 ({deployed_value/total_eval*100:.0f}%/{deploy_target_rate*100:.0f}%)")
        else:
            checks["max_positions"] = PREFLIGHT_OK
    else:
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

    # 6. AI confidence(정성 점수)는 2026-06-01(209faa9) 매수 게이트에서 분리되어
    #    preflight 차단 기준에서도 제외한다. 정량 지표만으로 진입을 판단한다.
    #    관찰·랭킹 호환을 위해 값은 기록하되 절대 차단하지 않는다.
    checks["ai_confidence"] = PREFLIGHT_OK

    # 7. 당일 손실한도 (실현+평가). breach 또는 '조회 실패' fail-closed 시 신규 BUY 차단.
    #    '조회 성공·데이터 없음'(아침 첫 매수 등 정상 결측)은 차단하지 않는다.
    daily_loss = evaluate_daily_loss_limit(final_rule)
    if daily_loss["breached"]:
        checks["daily_loss_limit"] = PREFLIGHT_BLOCK
        block_reasons.append(
            "일일 손실한도 도달 "
            f"({daily_loss['observed_percent']:.2f}% <= {daily_loss['limit_percent']:.2f}%)"
        )
    elif daily_loss.get("fail_closed"):
        checks["daily_loss_limit"] = PREFLIGHT_BLOCK
        block_reasons.append("손실한도 산출 불가 — 안전 차단")
    else:
        checks["daily_loss_limit"] = PREFLIGHT_OK

    # 8. 데이터 품질 상태 확인 — DEGRADED 이상이면 신규 BUY 차단
    _DQ_BLOCK_LEVELS = {"DEGRADED", "BLOCK_NEW_ENTRY", "EMERGENCY"}
    try:
        from .data_quality_guard import get_current_status as _dq_status
        dq_status = _dq_status()
        if dq_status in _DQ_BLOCK_LEVELS:
            checks["data_quality"] = PREFLIGHT_BLOCK
            block_reasons.append(f"데이터 품질 저하 ({dq_status}) — 신규 주문 차단")
        else:
            checks["data_quality"] = PREFLIGHT_OK
    except Exception as exc:
        logger.warning("WARN: [S6-P] DQ status check failed; fail-open reason=%s", exc)
        checks["data_quality"] = PREFLIGHT_OK

    # 9. 일일 투입예산 상한 (baseline×budget_rate 도달 시 신규매수 차단)
    #    누적매수 기준이라 매도해도 룸이 회복되지 않음 — 배포 게이트(현재 배포액 기준)가
    #    활성인 탐색모드에선 풀배포·교체매매와 충돌하므로 생략한다 (PM 결정 2026-06-10).
    if deploy_target_rate > 0:
        checks["budget_cap"] = "skipped_deploy_gate"
    else:
        _budget_date = _today_kst()  # _today_kst() already returns str "%Y-%m-%d"
        budget_blocked, budget_reason = _budget_cap_check(_budget_date)
        if budget_blocked:
            checks["budget_cap"] = PREFLIGHT_BLOCK
            block_reasons.append(budget_reason)
        else:
            checks["budget_cap"] = PREFLIGHT_OK

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
