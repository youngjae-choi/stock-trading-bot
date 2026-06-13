"""Trading Monitor API — 매수 대기 후보 + 보유 포지션 + 매수 준비도 조회."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any, cast
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from ...api.routes.account import _build_balance_payload
from ...services.engine.buy_condition_framework import (
    evaluate_condition,
    load_conditions,
    load_groups,
)
from ...services.engine.daily_plan import get_today_daily_plan
from ...services.engine.trade_tagging import build_selection_reason
from ...services.engine.rule_cache import get_all_cached, get_rule
from ...services.engine.position_manager import position_manager
from ...services.kis.domestic.service import get_balance as get_kis_balance
from ...services.kis.realtime_ws import realtime_ws_manager
from ...services.db import get_connection

# KIS balance 캐시 — Trading Monitor 화면 폴링이 rate limit을 소진하지 않도록 10초 TTL
_balance_cache: dict[str, Any] = {}
_balance_cache_at: float = 0.0
_BALANCE_CACHE_TTL = 10.0  # seconds

router = APIRouter(prefix="/api/v1/trading-monitor", tags=["trading-monitor"])
admin_router = APIRouter(prefix="/api/v1/trading", tags=["trading-admin"])
logger = logging.getLogger("TradingMonitorAPI")


def _today_kst() -> str:
    """Return today's Asia/Seoul date as YYYY-MM-DD."""
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


# ── 매수 준비도: 설정된 조건 GROUP들(OR of AND-그룹) 기반 ──
# 2026-06-06: 레거시 고정 3조건(거래량/등락률/TSI 평균%) 폐기.
# 매수엔진(buy_condition_framework)과 동일하게 enabled 그룹들을 평가하고,
# ANY 그룹 완전충족 시 "매수 가능(OR)"로 표시한다.

# state dict 키 → 사람이 읽는 현재값 (조건 ctype별)
def _condition_current_value(ctype: str, state: dict[str, Any]) -> Any:
    """조건 ctype이 평가하는 state 키의 현재값을 표시용으로 반환."""
    if ctype == "change_rate_band":
        return round(float(state.get("change_rate") or 0.0), 2)
    if ctype == "chegyeol_gangdo_min":
        return round(float(state.get("체결강도") or 0.0), 2)
    if ctype == "tick_volume_mult_min":
        return round(float(state.get("tick_vol_mult") or 0.0), 2)
    if ctype == "tsi_positive":
        tsi = state.get("tsi")
        return round(float(tsi), 1) if tsi is not None else "—"
    if ctype == "vwap_above":
        pos = state.get("vwap_position")
        return str(pos) if pos is not None else "—"
    if ctype == "day_high_breakout":
        return "돌파" if state.get("day_high_breakout") else "미돌파"
    if ctype == "pullback_rebound":
        return "반등" if state.get("pullback_rebound") else "—"
    if ctype == "momentum_rising_bars":
        return int(float(state.get("rising_bars") or 0))
    if ctype == "time_window":
        return str(state.get("time_hhmm") or "—")
    return "—"


def _condition_threshold_label(ctype: str, params: dict[str, Any]) -> str:
    """조건 params를 사람이 읽는 기준 문구로 변환."""
    p = params or {}
    if ctype == "change_rate_band":
        return f"{float(p.get('min', 0)):.1f}% ~ {float(p.get('max', 999)):.1f}%"
    if ctype == "chegyeol_gangdo_min":
        return f">= {float(p.get('min', 0)) * 100:.0f}%"
    if ctype == "tick_volume_mult_min":
        return f">= {float(p.get('min', 0)):.1f}x"
    if ctype == "tsi_positive":
        return f"> {float(p.get('min', 0)):.0f}"
    if ctype == "vwap_above":
        margin = float(p.get("margin_pct", 0) or 0)
        return "VWAP 상단" if margin == 0 else f"VWAP +{margin:.1f}% 위"
    if ctype == "day_high_breakout":
        buf = float(p.get("buffer_pct", 0) or 0)
        return "당일고가 돌파" if buf == 0 else f"당일고가 +{buf:.1f}% 돌파"
    if ctype == "pullback_rebound":
        return "눌림 후 반등"
    if ctype == "momentum_rising_bars":
        return f">= {int(float(p.get('min_bars', 1)))}연속 상승"
    if ctype == "time_window":
        return f"{p.get('start', '00:00')} ~ {p.get('end', '23:59')}"
    return ""


def _compute_group_readiness(
    state: dict[str, Any],
    groups: list[dict[str, Any]],
    conditions_by_id: dict[str, Any],
) -> dict[str, Any]:
    """설정된 조건 GROUP들(OR of AND-groups) 기반 매수 준비도.

    - 각 그룹: 소속 조건들을 evaluate_condition으로 평가(AND).
    - any_met: 어느 한 그룹이라도 완전충족(OR).
    - overall_pct: 가장 근접한 그룹의 met_count/total * 100.
    """
    out_groups: list[dict[str, Any]] = []
    for g in groups:
        cond_ids = g.get("condition_ids") or []
        conds: list[dict[str, Any]] = []
        met_count = 0
        for cid in cond_ids:
            cond = conditions_by_id.get(cid)
            if cond is None:
                continue
            ctype = str(cond.get("ctype") or "")
            params = cond.get("params") or {}
            met = bool(evaluate_condition(cond, state))
            if met:
                met_count += 1
            conds.append({
                "name": cond.get("name") or cid,
                "label": cond.get("name") or cid,
                "ctype": ctype,
                "met": met,
                "current_value": _condition_current_value(ctype, state),
                "threshold_label": _condition_threshold_label(ctype, params),
            })
        total = len(conds)
        group_met = total > 0 and met_count == total
        out_groups.append({
            "name": g.get("name") or g.get("id") or "",
            "met": group_met,
            "met_count": met_count,
            "total": total,
            "conditions": conds,
        })

    any_met = any(g["met"] for g in out_groups)
    ratios = [
        (g["met_count"] / g["total"]) for g in out_groups if g["total"] > 0
    ]
    overall_pct = round(max(ratios) * 100, 1) if ratios else 0.0
    return {
        "mode": "or_groups",
        "any_met": any_met,
        "groups": out_groups,
        "overall_pct": overall_pct,
    }


def _build_readiness_state(
    candidate: dict[str, Any],
    tick: dict[str, Any] | None,
    live_state: dict[str, Any] | None,
) -> dict[str, Any]:
    """live_state(엔진 신호) + candidate/tick을 병합해 평가용 state 생성.

    - 시작점은 live_state(compute_signal_state 결과) 또는 {}.
    - change_rate: tick.change_rate > candidate.change_rate 순으로 보정.
    - tsi: candidate.tsi (live_state의 tsi는 항상 None — 일봉 외부값).
    - time_hhmm: 비어있으면 현재 KST HH:MM.
    - 체결강도/tick_vol_mult: live_state에 없을 때만 0 폴백.
    """
    tick = tick or {}
    state: dict[str, Any] = dict(live_state or {})

    # change_rate: realtime tick 우선, candidate 폴백
    change_rate = float(tick.get("change_rate") or 0.0)
    if change_rate == 0.0:
        change_rate = float(
            candidate.get("change_rate") or candidate.get("chg_rate") or 0.0
        )
    if change_rate != 0.0 or "change_rate" not in state:
        state["change_rate"] = change_rate

    # tsi: 일봉 TSI는 candidate에서만 옴(live_state는 None)
    tsi_val = candidate.get("tsi")
    if tsi_val is not None:
        try:
            state["tsi"] = float(tsi_val)
        except (TypeError, ValueError):
            pass

    # time_hhmm: 비어있으면 현재 KST
    if not state.get("time_hhmm"):
        state["time_hhmm"] = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%H:%M")

    # 체결강도/tick_vol_mult: live 데이터 없으면 0 폴백
    if "체결강도" not in state:
        state["체결강도"] = 0.0
    if "tick_vol_mult" not in state:
        state["tick_vol_mult"] = 0.0

    return state


def _latest_ticks_by_symbol() -> dict[str, dict[str, Any]]:
    """Return the latest cached realtime tick for each symbol."""
    latest: dict[str, dict[str, Any]] = {}
    for item in realtime_ws_manager.get_latest(200):
        symbol = str(item.get("symbol") or "").strip()
        if symbol:
            latest[symbol] = item
    return latest


def _to_float(value: Any, default: float = 0.0) -> float:
    """Convert numeric API and DB values to float with a safe fallback."""
    try:
        return float(str(value).replace(",", "").strip() or default)
    except (TypeError, ValueError):
        return default


def _table_exists(conn: Any, table_name: str) -> bool:
    """Return whether a SQLite table exists.

    Args:
        conn: Open SQLite connection.
        table_name: Table name to check.
    """
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _safe_json_loads(value: Any, default: Any) -> Any:
    """Parse JSON text with a caller-provided fallback.

    Args:
        value: JSON string or already-decoded object.
        default: Value returned when parsing fails.
    """
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str) or not value.strip():
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _to_bool(value: Any, default: bool = True) -> bool:
    """Convert DB and JSON boolean-like values to bool.

    Args:
        value: Raw boolean-like value.
        default: Fallback value when conversion is ambiguous.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y", "on"):
        return True
    if text in ("0", "false", "no", "n", "off"):
        return False
    return default


def _latest_market_tone(trade_date: str) -> dict[str, Any] | None:
    """Return today's newest market tone result without raising on missing tables.

    Args:
        trade_date: YYYY-MM-DD trade date.
    """
    try:
        with get_connection() as conn:
            if not _table_exists(conn, "market_tone_results"):
                return None
            row = conn.execute(
                "SELECT * FROM market_tone_results WHERE trade_date = ? ORDER BY created_at DESC LIMIT 1",
                (trade_date,),
            ).fetchone()
        return dict(row) if row else None
    except Exception as exc:
        logger.warning("WARN: TradingMonitor policy-summary market tone lookup failed reason=%s", exc)
        return None


def _latest_screening(trade_date: str) -> dict[str, Any] | None:
    """Return today's newest hybrid screening result without raising on missing tables.

    Args:
        trade_date: YYYY-MM-DD trade date.
    """
    try:
        with get_connection() as conn:
            if not _table_exists(conn, "hybrid_screening_results"):
                return None
            row = conn.execute(
                "SELECT * FROM hybrid_screening_results WHERE trade_date = ? ORDER BY created_at DESC LIMIT 1",
                (trade_date,),
            ).fetchone()
        if not row:
            return None
        data = dict(row)
        data["candidates"] = _safe_json_loads(data.get("candidates"), [])
        data["skipped"] = _safe_json_loads(data.get("skipped"), [])
        return data
    except Exception as exc:
        logger.warning("WARN: TradingMonitor policy-summary screening lookup failed reason=%s", exc)
        return None


def _latest_rulepack_rules(trade_date: str) -> dict[str, Any]:
    """Return active RulePack machine rules generated for the trade date.

    Args:
        trade_date: YYYY-MM-DD trade date.
    """
    try:
        with get_connection() as conn:
            if not _table_exists(conn, "rulepacks"):
                return {}
            row = conn.execute(
                "SELECT machine_rules FROM rulepacks WHERE trade_date = ? AND status = 'active' ORDER BY created_at DESC LIMIT 1",
                (trade_date,),
            ).fetchone()
        if not row:
            return {}
        rules = _safe_json_loads(row["machine_rules"], {})
        return rules if isinstance(rules, dict) else {}
    except Exception as exc:
        logger.warning("WARN: TradingMonitor policy-summary rulepack lookup failed reason=%s", exc)
        return {}


def _build_entry_rules(plan: dict[str, Any] | None, screening: dict[str, Any] | None, rulepack: dict[str, Any]) -> dict[str, float]:
    """Build display-ready entry rule values from today's AI outputs.

    Args:
        plan: Daily trading plan row decoded by get_today_daily_plan().
        screening: Hybrid screening result row.
        rulepack: Active RulePack machine_rules generated from screening.
    """
    overrides = cast(dict[str, Any], (plan or {}).get("daily_overrides") or {})
    rulepack_entry = cast(dict[str, Any], rulepack.get("entry_rules") if isinstance(rulepack.get("entry_rules"), dict) else {})
    candidates = cast(list[dict[str, Any]], screening.get("candidates", []) if screening else [])
    change_rates = [_to_float(c.get("change_rate") or c.get("chg_rate")) for c in candidates if isinstance(c, dict)]
    return {
        "min_ai_confidence": _to_float(
            rulepack_entry.get("min_ai_confidence") or overrides.get("min_ai_confidence"),
            0.60,
        ),
        "min_price_change_pct": _to_float(
            rulepack_entry.get("min_price_change_pct"),
            min(change_rates) if change_rates else 0.5,
        ),
        "max_price_change_pct": _to_float(
            rulepack_entry.get("max_price_change_pct"),
            max(change_rates) if change_rates else 8.0,
        ),
    }


def _cash_usage_hint(tone: str, confidence: float, trading_intensity: str, new_entry_allowed: bool) -> str:
    """Create a Korean cash-usage hint from today's market and plan state.

    Args:
        tone: Market tone label.
        confidence: Market tone confidence score.
        trading_intensity: Daily plan trading intensity.
        new_entry_allowed: Whether new entries are allowed today.
    """
    if not new_entry_allowed:
        return "신규 진입이 차단되어 현금 보존을 우선합니다."
    if trading_intensity == "aggressive" and confidence >= 0.65 and tone in ("bullish", "positive", "risk_on"):
        return "시장톤 신뢰도가 높아 평소보다 적극적인 현금 사용이 가능합니다."
    if trading_intensity == "defensive" or confidence < 0.55 or tone in ("bearish", "negative", "risk_off"):
        return "시장 확신이 낮거나 방어 모드라 보수적 현금 사용을 권장합니다."
    return "선별된 후보 중심으로 중립적인 현금 사용을 권장합니다."


def _build_policy_texts(
    entry_rules: dict[str, float],
    rulepack: dict[str, Any],
    trading_intensity: str,
    new_entry_allowed: bool,
    cash_usage_text: str,
) -> dict[str, str]:
    """Build human-readable Korean buy, sell, and cash usage texts.

    Args:
        entry_rules: Entry rule thresholds selected for today.
        rulepack: Active RulePack machine_rules generated from AI outputs.
        trading_intensity: Daily plan trading intensity.
        new_entry_allowed: Whether new entries are allowed today.
        cash_usage_text: Precomputed cash-usage sentence.
    """
    buy_prefix = "신규 진입 허용" if new_entry_allowed else "신규 진입 차단"
    # 2026-06-01: AI confidence 게이트 분리 — 매수 문구는 정량 기준(등락률)만 안내한다.
    buy_condition_text = (
        f"{buy_prefix}. 등락률 {entry_rules['min_price_change_pct']:.1f}%~"
        f"{entry_rules['max_price_change_pct']:.1f}% 범위의 후보만 검토합니다."
    )
    exit_rules = cast(dict[str, Any], rulepack.get("exit_rules") if isinstance(rulepack.get("exit_rules"), dict) else {})
    force_close = exit_rules.get("force_close_at") or "15:20"
    stop_loss = exit_rules.get("stop_loss_trigger") or "손절 기준"
    trailing = exit_rules.get("take_profit_trigger") or "트레일링 스탑"
    sell_condition_text = f"매도는 {stop_loss}, {trailing}, {force_close} 전후 당일 청산 조건을 우선 적용합니다."
    return {
        "buy_condition_text": buy_condition_text,
        "sell_condition_text": sell_condition_text,
        "cash_usage_text": f"{cash_usage_text} 오늘 매매 강도는 {trading_intensity}입니다.",
    }


def _latest_stop_states() -> dict[str, dict[str, Any]]:
    """Return today's newest persisted stop state by symbol code."""
    states: dict[str, dict[str, Any]] = {}
    today = _today_kst()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM position_stop_states
            WHERE substr(last_updated_at, 1, 10) = ?
            ORDER BY last_updated_at DESC
            """,
            (today,),
        ).fetchall()
    for row in rows:
        data = dict(row)
        symbol = str(data.get("symbol_code") or "").strip()
        if symbol and symbol not in states:
            states[symbol] = data
    return states


def _latest_submitted_orders() -> dict[str, dict[str, Any]]:
    """Return today's latest submitted buy order by symbol code."""
    today = _today_kst()
    orders: dict[str, dict[str, Any]] = {}
    with get_connection() as conn:
        if not _table_exists(conn, "trading_orders"):
            return orders
        rows = conn.execute(
            """
            SELECT *
            FROM trading_orders
            WHERE trade_date = ?
              AND side = 'buy'
              AND status = 'submitted'
            ORDER BY created_at DESC
            """,
            (today,),
        ).fetchall()
    for row in rows:
        data = dict(row)
        symbol = str(data.get("symbol") or "").strip()
        if symbol and symbol not in orders:
            orders[symbol] = data
    return orders


def _monitoring_status(symbol: str, memory_positions: dict[str, dict[str, Any]], subscribed_symbols: set[str], stop_state_source: str) -> dict[str, Any]:
    """Classify whether a KIS holding is actually protected by S8 automation.

    Args:
        symbol: KIS holding symbol.
        memory_positions: PositionManager in-memory positions by symbol.
        subscribed_symbols: Realtime websocket subscription symbols.
        stop_state_source: Source of stop-state values shown on the screen.
    """
    managed = symbol in memory_positions
    subscribed = symbol in subscribed_symbols
    if managed and subscribed:
        status = "자동감시중"
        detail = "PositionManager 등록 및 실시간 구독 확인"
    elif managed:
        status = "상태불일치"
        detail = "PositionManager에는 있지만 실시간 구독 대상이 아님"
    elif subscribed:
        status = "상태불일치"
        detail = "실시간 구독은 있으나 PositionManager 포지션이 없음"
    else:
        status = "미감시"
        detail = "KIS 실보유에는 있으나 자동 손절/트레일링 감시 대상이 아님"

    if stop_state_source == "fallback" and status == "자동감시중":
        status = "상태불일치"
        detail = "자동감시 상태이나 오늘 stop state 저장값이 없어 fallback 손절선 표시"

    return {
        "auto_monitoring": status == "자동감시중",
        "monitoring_status": status,
        "monitoring_detail": detail,
        "ws_subscribed": subscribed,
        "position_manager_registered": managed,
    }


def _fallback_stop_state(symbol: str, entry_price: float) -> dict[str, Any]:
    """Build conservative stop values when no persisted stop state exists."""
    rule = get_rule(symbol) or {}
    initial_stop_loss = _to_float(rule.get("initial_stop_loss"), -0.03)
    if initial_stop_loss > 0:
        initial_stop_loss = -initial_stop_loss
    initial_stop = entry_price * (1 + initial_stop_loss) if entry_price > 0 else 0.0
    return {
        "position_id": f"{symbol}-account",
        "profile_assigned": rule.get("profile_assigned", "MID_VOL"),
        "highest_price_since_entry": entry_price,
        "initial_stop_price": initial_stop,
        "trailing_stop_price": initial_stop,
        "active_stop_price": initial_stop,
        "trailing_active": 0,
    }


@router.get("/candidates")
def get_candidates():
    """매수 대기 후보 종목 목록 + Profile + 매수 준비도."""
    today = _today_kst()
    plan = get_today_daily_plan(today)
    if not plan:
        return {"ok": True, "payload": {"candidates": [], "plan_id": None}}

    all_rules = get_all_cached()
    assignments = {a["code"]: a for a in plan.get("symbol_assignments", [])}
    excluded = {e["code"] for e in plan.get("excluded_symbols", [])}

    # hybrid_screening_results에서 오늘 후보 조회
    with get_connection() as conn:
        row = conn.execute(
            "SELECT candidates FROM hybrid_screening_results WHERE trade_date = ? ORDER BY created_at DESC LIMIT 1",
            (today,),
        ).fetchone()

    import json as _json
    raw_candidates: list[dict[str, Any]] = []
    if row:
        try:
            raw_candidates = _json.loads(row["candidates"] or "[]")
        except Exception:
            raw_candidates = []

    # daily_overrides 조건 읽기
    overrides = plan.get("daily_overrides", {})

    latest_ticks = _latest_ticks_by_symbol()

    # 매수 준비도: 설정된 조건 그룹들(OR of AND-그룹)을 1회 로드.
    # 엔진이 활성이면 라이브 신호(BarEngine.compute_signal_state)를 종목별로 사용.
    readiness_groups = load_groups(enabled_only=True)
    readiness_conds = load_conditions(enabled_only=False)
    from ...services.engine.decision_engine import decision_engine
    bar_engine = getattr(decision_engine, "_bar_engine", None)
    engine_live = bool(decision_engine.is_active()) and bar_engine is not None

    # 이미 보유 중인 종목은 매수 대기 목록에서 제외한다.
    # 엔진은 종목당 1회 진입(single-entry)이라 보유 종목은 재매수하지 않으므로
    # (decision_engine._on_tick: `if symbol in managed_symbols: return`),
    # 매수 준비도를 계산·표시하는 것은 낭비이자 오해 소지다. 보유 패널엔 그대로 남는다.
    held_symbols = {
        str(p.get("symbol") or "").strip()
        for p in position_manager.get_positions()
        if p.get("symbol")
    }
    result = []
    for c in raw_candidates:
        code = str(c.get("symbol") or c.get("ticker") or "").strip()
        if not code or code in excluded or code in held_symbols:
            continue
        assignment = assignments.get(code, {})
        rule = all_rules.get(code) or {}
        latest_tick = latest_ticks.get(code, {})

        # daily_overrides로 rule 보완
        if overrides.get("min_ai_confidence"):
            rule["ai_confidence_min"] = overrides["min_ai_confidence"]
        if overrides.get("volume_filter_multiplier"):
            rule["volume_ratio_min"] = overrides["volume_filter_multiplier"]

        if engine_live:
            try:
                live_state = bar_engine.compute_signal_state(code)
            except Exception:
                live_state = {}
        else:
            live_state = {}
        state = _build_readiness_state(c, latest_tick, live_state)
        readiness = _compute_group_readiness(state, readiness_groups, readiness_conds)
        result.append({
            "code": code,
            "name": c.get("name") or "",
            "profile": assignment.get("profile") or rule.get("profile_assigned") or "MID_VOL",
            "assignment_reason": assignment.get("reason") or "",
            "score": c.get("suitability_score") or c.get("score") or 0,
            "change_rate": c.get("change_rate") or 0,
            "ws_subscribed": code in all_rules,
            "latest_price": latest_tick.get("price"),
            "latest_trade_time": latest_tick.get("trade_time"),
            "latest_volume": latest_tick.get("trade_volume"),
            "latest_received_at": latest_tick.get("received_at"),
            "selection_reason": build_selection_reason(c),
            "buy_readiness": readiness,
        })

    result.sort(key=lambda x: x["buy_readiness"]["overall_pct"], reverse=True)
    return {"ok": True, "payload": {
        "candidates": result,
        "plan_id": plan.get("id"),
        "daily_overrides": overrides,
    }}


async def _get_cached_balance() -> dict[str, Any]:
    """Return KIS balance using a 10-second server-side cache.

    Trading Monitor UI polls this endpoint every ~1 second.
    Without caching this causes EGW00201 rate-limit errors that also corrupt
    concurrent sell order responses (ODNO missing from output).
    """
    global _balance_cache, _balance_cache_at
    now = time.monotonic()
    if now - _balance_cache_at > _BALANCE_CACHE_TTL or not _balance_cache:
        _balance_cache = await get_kis_balance()
        _balance_cache_at = now
        logger.info("INFO: TradingMonitor balance cache refreshed")
    return _balance_cache


@router.get("/positions")
async def get_positions():
    """Return actual KIS holdings with persisted trailing-stop state."""
    endpoint = "/api/v1/trading-monitor/positions"
    logger.info("START: GET %s", endpoint)
    try:
        account_payload = _build_balance_payload(await _get_cached_balance())
        account_positions = account_payload.get("positions", [])
    except Exception as exc:
        logger.warning("WARN: TradingMonitor KIS holdings lookup failed reason=%s", exc)
        account_positions = []

    stop_states = _latest_stop_states()
    submitted_orders = _latest_submitted_orders()
    memory_positions = {str(p.get("symbol") or ""): p for p in position_manager.get_positions()}
    subscribed_symbols = {str(symbol) for symbol in getattr(realtime_ws_manager, "_symbols", [])}

    positions: list[dict[str, Any]] = []
    for holding in account_positions:
        symbol = str(holding.get("symbol") or "").strip()
        if not symbol:
            continue
        qty = int(holding.get("qty") or 0)
        if qty <= 0:
            continue

        entry_price = _to_float(holding.get("avg_price"))
        current_price = _to_float(holding.get("current_price"), entry_price)
        purchase_amount = _to_float(holding.get("purchase_amount"), entry_price * qty)
        memory_pos = memory_positions.get(symbol, {})
        order = submitted_orders.get(symbol, {})
        persisted_stop_state = stop_states.get(symbol)
        stop_state_source = "persisted" if persisted_stop_state else "fallback"
        stop_state = persisted_stop_state or _fallback_stop_state(symbol, entry_price)
        monitoring = _monitoring_status(symbol, memory_positions, subscribed_symbols, stop_state_source)

        positions.append({
            "position_id": stop_state.get("position_id") or memory_pos.get("position_id") or f"{symbol}-account",
            "symbol": symbol,
            "name": holding.get("name") or memory_pos.get("name") or order.get("name") or "",
            "qty": qty,
            "entry_price": entry_price,
            "purchase_amount": purchase_amount,
            "entry_time": memory_pos.get("entry_time") or order.get("created_at") or "",
            "market_price": current_price,
            "pnl_pct": holding.get("pnl_pct"),
            "profile_assigned": stop_state.get("profile_assigned") or memory_pos.get("profile_assigned") or "MID_VOL",
            "initial_stop_price": _to_float(stop_state.get("initial_stop_price")),
            "active_stop_price": _to_float(stop_state.get("active_stop_price")),
            "highest_price_since_entry": _to_float(stop_state.get("highest_price_since_entry"), entry_price),
            "trailing_active": bool(stop_state.get("trailing_active")),
            "trailing_stop_price": _to_float(stop_state.get("trailing_stop_price")),
            "trailing_activate_profit": memory_pos.get("trailing_activate_profit"),
            "trailing_stop_rate": memory_pos.get("trailing_stop_rate"),
            "max_holding_minutes": memory_pos.get("max_holding_minutes"),
            "force_exit_time": memory_pos.get("force_exit_time") or "15:20:00",
            "stop_state_source": stop_state_source,
            "timed_liquidation_target": True,
            "timed_liquidation_status": "시간청산 대상",
            **monitoring,
            "source": "kis_account",
        })

    logger.info("SUCCESS: GET %s count=%d", endpoint, len(positions))
    return {"ok": True, "payload": {"positions": positions, "count": len(positions)}}


@router.get("/policy-summary")
def get_policy_summary():
    """Return today's AI-generated policy summary for operator display."""
    endpoint = "/api/v1/trading-monitor/policy-summary"
    trade_date = _today_kst()
    logger.info("START: GET %s trade_date=%s", endpoint, trade_date)
    try:
        market = _latest_market_tone(trade_date) or {}
        screening = _latest_screening(trade_date) or {}
        plan = get_today_daily_plan(trade_date) or {}
        rulepack = _latest_rulepack_rules(trade_date)

        tone = str(market.get("tone") or plan.get("market_tone") or "mixed")
        confidence = _to_float(market.get("confidence"), _to_float(screening.get("overall_confidence"), 0.0))
        trading_intensity = str(plan.get("trading_intensity") or "defensive")
        new_entry_allowed = _to_bool(plan.get("new_entry_allowed"), True)
        entry_rules = _build_entry_rules(plan, screening, rulepack)
        cash_usage_text = _cash_usage_hint(tone, confidence, trading_intensity, new_entry_allowed)
        policy_texts = _build_policy_texts(
            entry_rules=entry_rules,
            rulepack=rulepack,
            trading_intensity=trading_intensity,
            new_entry_allowed=new_entry_allowed,
            cash_usage_text=cash_usage_text,
        )

        payload: dict[str, Any] = {
            "trade_date": trade_date,
            "market_tone": {
                "tone": tone,
                "confidence": confidence,
                "summary": str(market.get("summary") or "오늘 시장톤 AI 결과가 없어 보수적 기준으로 표시합니다."),
                "cash_usage_hint": cash_usage_text,
            },
            "entry_rules": entry_rules,
            "daily_plan": {
                "id": plan.get("id") or "",
                "status": plan.get("status") or "none",
                "trading_intensity": trading_intensity,
                "new_entry_allowed": new_entry_allowed,
                "buy_condition_text": policy_texts["buy_condition_text"],
                "sell_condition_text": policy_texts["sell_condition_text"],
                "cash_usage_text": policy_texts["cash_usage_text"],
            },
        }
        logger.info("SUCCESS: GET %s trade_date=%s status=%s", endpoint, trade_date, payload["daily_plan"]["status"])
        return {"ok": True, "payload": payload}
    except Exception as exc:
        logger.error("FAIL: GET %s — %s", endpoint, exc)
        fallback_rules = {"min_ai_confidence": 0.60, "min_price_change_pct": 0.5, "max_price_change_pct": 8.0}
        return {
            "ok": True,
            "payload": {
                "trade_date": trade_date,
                "market_tone": {
                    "tone": "mixed",
                    "confidence": 0.0,
                    "summary": "정책 요약 데이터를 읽지 못해 보수적 기준으로 표시합니다.",
                    "cash_usage_hint": "데이터 확인 전까지 보수적 현금 사용을 권장합니다.",
                },
                "entry_rules": fallback_rules,
                "daily_plan": {
                    "id": "",
                    "status": "fallback",
                    "trading_intensity": "defensive",
                    "new_entry_allowed": False,
                    "buy_condition_text": "정책 데이터 확인 전까지 신규 진입을 보류합니다.",
                    "sell_condition_text": "보유 포지션은 손절, 트레일링, 당일 청산 기준을 우선 확인합니다.",
                    "cash_usage_text": "데이터 확인 전까지 현금 보존을 우선합니다.",
                },
            },
        }


@router.get("/stream")
async def stream_monitor_events():
    """Stream realtime monitor events to the browser using Server-Sent Events."""

    async def event_generator():
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)

        async def on_tick(tick: dict[str, Any]) -> None:
            try:
                queue.put_nowait({
                    "type": "tick",
                    "symbol": tick.get("symbol"),
                    "price": tick.get("price"),
                    "volume": tick.get("volume"),
                    "time": tick.get("time"),
                })
            except asyncio.QueueFull:
                logger.warning("WARN: TradingMonitor stream queue full; dropping tick")

        realtime_ws_manager.register_tick_callback(on_tick)
        try:
            yield "event: connected\ndata: {\"ok\":true}\n\n"
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=3.0)
                    yield f"event: tick\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    heartbeat = {
                        "type": "heartbeat",
                        "connected": realtime_ws_manager.is_connected,
                        "symbols": len(getattr(realtime_ws_manager, "_symbols", [])),
                    }
                    yield f"event: heartbeat\ndata: {json.dumps(heartbeat, ensure_ascii=False)}\n\n"
        finally:
            realtime_ws_manager.unregister_tick_callback(on_tick)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/daily-results")
def get_daily_results(start_date: str | None = None, end_date: str | None = None):
    """일자별 매매결과 — daily_review_reports + daily_trade_summary 조인.

    start_date / end_date (YYYY-MM-DD): 범위 지정 시 해당 구간만 반환. 미지정 시 전체 반환.
    """
    from collections import defaultdict
    with get_connection() as conn:
        # equity_pnl 컬럼은 S10 마이그레이션(_ensure_review_integrity_columns) 이후에만 존재 —
        # 미적용 DB에서도 라우트가 깨지지 않도록 존재 확인 후 선택한다.
        drr_columns = {
            str(r["name"]) for r in conn.execute("PRAGMA table_info(daily_review_reports)").fetchall()
        }
        equity_select = "drr.equity_pnl" if "equity_pnl" in drr_columns else "NULL"
        # P&L은 daily_trade_summary(주문 가격 기반 계산)가 더 정확함
        base_select = f"""
                SELECT
                    drr.trade_date,
                    drr.missed_entries_count,
                    drr.integrity_warnings,
                    drr.false_positive_count,
                    {equity_select} AS equity_pnl,
                    COALESCE(dts.buy_orders, drr.total_trades, 0) AS trade_count,
                    COALESCE(dts.realized_pnl, 0.0) AS total_pnl,
                    COALESCE(dts.realized_pnl_pct, 0.0) AS pnl_rate,
                    dts.net_pnl,
                    dts.net_pnl_pct,
                    COALESCE(dts.pnl_status, drr.pnl_status, 'unverified') AS pnl_status,
                    mtr.tone AS market_tone,
                    mtr.confidence AS tone_confidence
                FROM daily_review_reports drr
                LEFT JOIN daily_trade_summary dts ON drr.trade_date = dts.trade_date
                -- market_tone_results는 장중 슬롯마다 기록되어 날짜당 여러 행이다.
                -- 날짜당 장 마감 최신 톤 1건만 조인해 일별 결과가 fan-out되지 않게 한다.
                LEFT JOIN market_tone_results mtr ON mtr.id = (
                    SELECT m2.id FROM market_tone_results m2
                    WHERE m2.trade_date = drr.trade_date
                    ORDER BY m2.created_at DESC LIMIT 1
                )
                """
        if start_date and end_date:
            rows = conn.execute(
                base_select + "WHERE drr.trade_date >= ? AND drr.trade_date <= ? ORDER BY drr.trade_date DESC",
                (start_date, end_date),
            ).fetchall()
        else:
            rows = conn.execute(
                base_select + "ORDER BY drr.trade_date DESC",
            ).fetchall()

        dates = [r["trade_date"] for r in rows]
        order_rows: list[Any] = []
        if dates:
            placeholders = ",".join("?" * len(dates))
            order_rows = conn.execute(
                f"""
                SELECT trade_date, symbol, side, price, qty, status
                FROM trading_orders
                WHERE trade_date IN ({placeholders})
                  AND status IN ('filled', 'submitted', 'submitted_without_order_no')
                ORDER BY trade_date, symbol, side
                """,
                dates,
            ).fetchall()

    # 심볼별 매수/매도 쌍으로 승/패 계산
    date_wins: dict[str, int] = defaultdict(int)
    date_losses: dict[str, int] = defaultdict(int)
    by_date_symbol: dict[str, dict[str, dict]] = defaultdict(
        lambda: defaultdict(lambda: {"buys": [], "sells": []})
    )
    for o in order_rows:
        od = dict(o)
        by_date_symbol[od["trade_date"]][od["symbol"]][od["side"] + "s"].append(od)

    for trade_date, symbols in by_date_symbol.items():
        for symbol, sides in symbols.items():
            buys = sides.get("buys", [])
            sells = sides.get("sells", [])
            if not buys or not sells:
                continue
            avg_buy = sum(float(b.get("price") or 0) for b in buys) / len(buys)
            valid_sell_prices = [
                float(s.get("price") or 0)
                for s in sells
                if float(s.get("price") or 0) > 0
            ]
            if not valid_sell_prices or avg_buy == 0:
                continue
            avg_sell = sum(valid_sell_prices) / len(valid_sell_prices)
            if avg_sell > avg_buy:
                date_wins[trade_date] += 1
            else:
                date_losses[trade_date] += 1

    from datetime import datetime as _dt, timedelta as _td

    from ...services.engine.trading_calendar import is_trading_day, non_trading_reason

    result = []
    for row in rows:
        d = dict(row)
        td = d["trade_date"]
        wins = date_wins.get(td, 0)
        losses = date_losses.get(td, 0)
        total_closed = wins + losses
        d["win_count"] = wins
        d["loss_count"] = losses
        d["win_rate"] = round(wins / total_closed * 100, 1) if total_closed > 0 else 0
        # 비거래일(주말·공휴일)이면 휴장 표식 — 과거에 쌓인 노이즈 행도 휴장으로 덮어 표시한다.
        if not is_trading_day(td):
            d["non_trading"] = True
            d["non_trading_reason"] = non_trading_reason(td) or "휴장"
        result.append(d)

    # 범위 내 리뷰 행이 없는 비거래일은 "휴장" 행으로 합성한다.
    existing_dates = {d["trade_date"] for d in result}
    try:
        if start_date and end_date:
            range_start, range_end = start_date, end_date
        elif existing_dates:
            range_start, range_end = min(existing_dates), _today_kst()
        else:
            range_start = range_end = None
        if range_start and range_end:
            cur = _dt.strptime(range_start, "%Y-%m-%d").date()
            last = _dt.strptime(range_end, "%Y-%m-%d").date()
            while cur <= last:
                ds = cur.isoformat()
                if ds not in existing_dates and not is_trading_day(ds):
                    result.append({
                        "trade_date": ds, "non_trading": True,
                        "non_trading_reason": non_trading_reason(ds) or "휴장",
                        "trade_count": 0, "win_count": 0, "loss_count": 0, "win_rate": 0,
                        "total_pnl": 0.0, "pnl_rate": 0.0, "equity_pnl": None, "pnl_status": "non_trading",
                        "missed_entries_count": 0, "integrity_warnings": 0, "market_tone": None,
                    })
                cur += _td(days=1)
            result.sort(key=lambda r: r["trade_date"], reverse=True)
    except Exception as exc:
        logger.warning("WARN: daily-results 휴장 행 합성 실패 — %s", exc)

    return {"ok": True, "payload": result}


@router.get("/intraday-refresh-status")
def get_intraday_refresh_status():
    """오늘 장중 재선별 이력 반환 (Trading Monitor UI용)."""
    from ...services.engine.intraday_refresh import get_today_refresh_status
    logs = get_today_refresh_status()
    return {"ok": True, "payload": logs}


@router.get("/reselection-stats")
async def get_reselection_stats(trade_date: str | None = Query(None, description="YYYY-MM-DD (기본값: 오늘)")):
    """Return intraday reselection slot logs, sector rotations, and replacement signals.

    Args:
        trade_date: Optional trade date. Empty data is returned as arrays, not errors.
    """
    target_date = trade_date or _today_kst()
    endpoint = "/api/v1/trading-monitor/reselection-stats"
    logger.info("START: GET %s trade_date=%s", endpoint, target_date)
    try:
        from ...services.engine.intraday_refresh import get_today_refresh_status
        from ...services.engine.replacement_signal import get_replacement_signals
        from ...services.engine.sector_rotation import get_sector_rotation_logs

        logs = get_today_refresh_status(target_date)
        slots = []
        for log in logs:
            reselection = log.get("reselection") if isinstance(log.get("reselection"), dict) else {}
            s6 = reselection.get("s6", {}) if isinstance(reselection, dict) else {}
            s4 = reselection.get("s4", {}) if isinstance(reselection, dict) else {}
            slots.append(
                {
                    "slot": log.get("slot", ""),
                    "triggered": bool(log.get("triggered")),
                    "reason": log.get("reason", ""),
                    "avg_change": log.get("avg_change"),
                    "new_candidates": s6.get("new_count", s4.get("output_count", 0)),
                    "market_triggered": bool(log.get("market_triggered", log.get("triggered", False))),
                    "sector_rotation_triggered": bool((log.get("sector_rotation") or {}).get("triggered"))
                    if isinstance(log.get("sector_rotation"), dict)
                    else False,
                }
            )
        payload = {
            "trade_date": target_date,
            "slots": slots,
            "sector_rotations": get_sector_rotation_logs(target_date),
            "replacement_signals": _format_replacement_signals(get_replacement_signals(target_date)),
        }
        logger.info("SUCCESS: GET %s trade_date=%s slots=%d", endpoint, target_date, len(slots))
        return {"ok": True, "payload": payload}
    except Exception as exc:
        logger.error("FAIL: GET %s trade_date=%s reason=%s", endpoint, target_date, exc)
        return {"ok": True, "payload": {"trade_date": target_date, "slots": [], "sector_rotations": [], "replacement_signals": []}}


def _format_replacement_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Shape DB replacement signal rows for the Trading Monitor API contract."""
    formatted = []
    for signal in signals:
        formatted.append(
            {
                "id": signal.get("id"),
                "slot": signal.get("slot", ""),
                "current": {
                    "symbol": signal.get("current_symbol", ""),
                    "name": signal.get("current_name", ""),
                    "score": signal.get("current_score", 0),
                    "pnl_pct": signal.get("current_pnl_pct"),
                },
                "new": {
                    "symbol": signal.get("new_symbol", ""),
                    "name": signal.get("new_name", ""),
                    "score": signal.get("new_score", 0),
                },
                "score_gap": round(_to_float(signal.get("score_gap")) * 100, 1),
                "reason": signal.get("reason", ""),
                "created_at": signal.get("created_at", ""),
            }
        )
    return formatted


@router.get("/replacement-signals")
async def get_replacement_signal_list(trade_date: str | None = Query(None, description="YYYY-MM-DD (기본값: 오늘)")):
    """Return replacement signals for one trade date.

    Args:
        trade_date: Optional trade date. Missing data returns an empty signals array.
    """
    target_date = trade_date or _today_kst()
    endpoint = "/api/v1/trading-monitor/replacement-signals"
    logger.info("START: GET %s trade_date=%s", endpoint, target_date)
    try:
        from ...services.engine.replacement_signal import get_replacement_signals

        signals = _format_replacement_signals(get_replacement_signals(target_date))
        logger.info("SUCCESS: GET %s trade_date=%s count=%d", endpoint, target_date, len(signals))
        return {"ok": True, "payload": {"signals": signals}}
    except Exception as exc:
        logger.error("FAIL: GET %s trade_date=%s reason=%s", endpoint, target_date, exc)
        return {"ok": True, "payload": {"signals": []}}


def _backfill_sell_order_names(trade_date: str) -> int:
    """Fill missing sell order names from the local symbols master table.

    Args:
        trade_date: YYYY-MM-DD trade date whose sell orders should be repaired.
    """
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE trading_orders
            SET name = COALESCE(
                (
                    SELECT symbols.name
                    FROM symbols
                    WHERE symbols.symbol = trading_orders.symbol
                      AND symbols.name IS NOT NULL
                      AND symbols.name != ''
                    LIMIT 1
                ),
                (
                    SELECT source_orders.name
                    FROM trading_orders AS source_orders
                    WHERE source_orders.trade_date = trading_orders.trade_date
                      AND source_orders.symbol = trading_orders.symbol
                      AND source_orders.name IS NOT NULL
                      AND source_orders.name != ''
                    ORDER BY CASE WHEN source_orders.side = 'buy' THEN 0 ELSE 1 END, source_orders.created_at DESC
                    LIMIT 1
                ),
                (
                    SELECT trading_signals.name
                    FROM trading_signals
                    WHERE trading_signals.symbol = trading_orders.symbol
                      AND trading_signals.name IS NOT NULL
                      AND trading_signals.name != ''
                    ORDER BY trading_signals.created_at DESC
                    LIMIT 1
                ),
                ''
            )
            WHERE trade_date = ?
              AND side = 'sell'
              AND (name IS NULL OR name = '')
              AND EXISTS (
                  SELECT 1
                  FROM trading_orders AS buy_orders
                  WHERE buy_orders.trade_date = trading_orders.trade_date
                    AND buy_orders.symbol = trading_orders.symbol
                    AND buy_orders.name IS NOT NULL
                    AND buy_orders.name != ''
                  UNION
                  SELECT 1
                  FROM symbols
                  WHERE symbols.symbol = trading_orders.symbol
                    AND symbols.name IS NOT NULL
                    AND symbols.name != ''
                  UNION
                  SELECT 1
                  FROM trading_signals
                  WHERE trading_signals.symbol = trading_orders.symbol
                    AND trading_signals.name IS NOT NULL
                    AND trading_signals.name != ''
              )
            """,
            (trade_date,),
        )
        updated = int(cursor.rowcount or 0)
    return updated


@admin_router.post("/admin/recover-fills")
@router.post("/admin/recover-fills")
async def recover_fills(trade_date: str | None = Query(None, description="YYYY-MM-DD (기본값: 오늘)")):
    """오늘 submitted 매도주문 fill 재폴링 + S10 재실행.

    Args:
        trade_date: Optional YYYY-MM-DD trade date. Defaults to today's KST date.

    장 종료 후 fill_poller가 sell 주문 체결을 놓쳤을 때 수동으로 복구한다.
    """
    from ...services.engine.fill_poller import poll_once
    from ...services.scheduler import job_review_audit

    today = trade_date or datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    logger.info("START: POST /api/v1/trading/admin/recover-fills date=%s", today)

    try:
        names_updated = _backfill_sell_order_names(today)
        logger.info("SUCCESS: recover-fills sell order names backfilled updated=%d date=%s", names_updated, today)
    except Exception as exc:
        names_updated = 0
        logger.warning("WARN: recover-fills sell order name backfill failed date=%s reason=%s", today, exc)

    try:
        fill_result = await poll_once(today)
        logger.info("SUCCESS: recover-fills fill 폴링 완료 filled=%d", fill_result.get("filled", 0))
    except Exception as exc:
        logger.warning("WARN: recover-fills fill 폴링 실패 (S10 계속) reason=%s", exc)
        fill_result = {"filled": 0, "error": str(exc)}

    try:
        from ...services.engine.daily_summary import run_daily_summary

        summary_result = await run_daily_summary(today)
        logger.info(
            "SUCCESS: recover-fills Daily Summary 재실행 완료 orders=%d pnl_status=%s",
            summary_result.get("total_orders", 0),
            summary_result.get("pnl_status", "unknown"),
        )
    except Exception as exc:
        logger.warning("WARN: recover-fills Daily Summary 재실행 실패 (S10 계속) reason=%s", exc)
        summary_result = {"ok": False, "error": str(exc)}

    try:
        await job_review_audit()
        logger.info("SUCCESS: recover-fills S10 재실행 완료")
        s10_ok = True
    except Exception as exc:
        logger.error("FAIL: recover-fills S10 재실행 실패 reason=%s", exc)
        s10_ok = False

    return {
        "ok": True,
        "trade_date": today,
        "names_updated": names_updated,
        "fill_result": fill_result,
        "daily_summary": summary_result,
        "s10_rerun": s10_ok,
    }
