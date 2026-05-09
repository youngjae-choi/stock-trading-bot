"""Trading Monitor API — 매수 대기 후보 + 보유 포지션 + 매수 준비도 조회."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, cast
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from ...api.routes.account import _build_balance_payload
from ...services.engine.daily_plan import get_today_daily_plan
from ...services.engine.rule_cache import get_all_cached, get_rule
from ...services.engine.position_manager import position_manager
from ...services.kis.domestic.service import get_balance as get_kis_balance
from ...services.kis.realtime_ws import realtime_ws_manager
from ...services.db import get_connection

router = APIRouter(prefix="/api/v1/trading-monitor", tags=["trading-monitor"])
logger = logging.getLogger("TradingMonitorAPI")


def _today_kst() -> str:
    """Return today's Asia/Seoul date as YYYY-MM-DD."""
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


def _compute_buy_readiness(candidate: dict[str, Any], rule: dict[str, Any] | None) -> dict[str, Any]:
    """매수 준비도 계산.

    조건 목록과 임계치는 rule + candidate에서 동적으로 구성한다.
    각 조건은 {name, label, current_value, threshold_label, score_pct, met} 형태.
    score_pct: 0.0~100.0 (조건 근접 정도)
    """
    conditions: list[dict[str, Any]] = []

    # AI 신뢰도
    ai_conf = float(candidate.get("suitability_score") or candidate.get("confidence") or 0.0)
    ai_min = float((rule or {}).get("ai_confidence_min", 0.65))
    ai_score = min(ai_conf / ai_min, 1.0) * 100 if ai_min > 0 else 100.0
    conditions.append({
        "name": "ai_confidence",
        "label": "AI 신뢰도",
        "current_value": round(ai_conf, 3),
        "threshold_label": f">= {ai_min:.2f}",
        "score_pct": round(ai_score, 1),
        "met": ai_conf >= ai_min,
    })

    # 거래량 배수 (candidate에 volume_ratio 있으면 사용)
    vol_ratio = float(candidate.get("volume_ratio") or candidate.get("vol_ratio") or 0.0)
    vol_min = float((rule or {}).get("volume_ratio_min", 2.0))
    if vol_ratio > 0:
        vol_score = min(vol_ratio / vol_min, 1.0) * 100 if vol_min > 0 else 100.0
        conditions.append({
            "name": "volume_ratio",
            "label": "거래량 배수",
            "current_value": round(vol_ratio, 2),
            "threshold_label": f">= {vol_min:.1f}x",
            "score_pct": round(vol_score, 1),
            "met": vol_ratio >= vol_min,
        })

    # 등락률 (과도한 급등은 제외)
    change_rate = float(candidate.get("change_rate") or candidate.get("chg_rate") or 0.0)
    if change_rate != 0:
        # 양수 등락이 좋지만 너무 높으면 리스크 (>15% 이상이면 위험)
        rate_score = max(0.0, min(change_rate / 10.0, 1.0)) * 100 if change_rate > 0 else 0.0
        conditions.append({
            "name": "change_rate",
            "label": "등락률",
            "current_value": round(change_rate, 2),
            "threshold_label": "0% ~ 15%",
            "score_pct": round(rate_score, 1),
            "met": 0 < change_rate < 15,
        })

    # VWAP (candidate에 vwap_position 있으면 표시)
    vwap_pos = candidate.get("vwap_position")
    if vwap_pos is not None:
        vwap_met = str(vwap_pos).lower() in ("above", "상단", "위")
        conditions.append({
            "name": "vwap_position",
            "label": "VWAP 상단",
            "current_value": str(vwap_pos),
            "threshold_label": "상단",
            "score_pct": 100.0 if vwap_met else 0.0,
            "met": vwap_met,
        })

    # 종합 점수 계산 (단순 평균)
    if conditions:
        overall = sum(c["score_pct"] for c in conditions) / len(conditions)
    else:
        overall = 0.0

    return {
        "overall_pct": round(overall, 1),
        "met_count": sum(1 for c in conditions if c["met"]),
        "total_count": len(conditions),
        "conditions": conditions,
    }


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
    buy_condition_text = (
        f"{buy_prefix}. AI confidence {entry_rules['min_ai_confidence']:.2f} 이상이고 "
        f"등락률 {entry_rules['min_price_change_pct']:.1f}%~{entry_rules['max_price_change_pct']:.1f}% 범위의 후보만 검토합니다."
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
    result = []
    for c in raw_candidates:
        code = str(c.get("symbol") or c.get("ticker") or "").strip()
        if not code or code in excluded:
            continue
        assignment = assignments.get(code, {})
        rule = all_rules.get(code) or {}
        latest_tick = latest_ticks.get(code, {})

        # daily_overrides로 rule 보완
        if overrides.get("min_ai_confidence"):
            rule["ai_confidence_min"] = overrides["min_ai_confidence"]
        if overrides.get("volume_filter_multiplier"):
            rule["volume_ratio_min"] = overrides["volume_filter_multiplier"]

        readiness = _compute_buy_readiness(c, rule)
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
            "buy_readiness": readiness,
        })

    result.sort(key=lambda x: x["buy_readiness"]["overall_pct"], reverse=True)
    return {"ok": True, "payload": {
        "candidates": result,
        "plan_id": plan.get("id"),
        "daily_overrides": overrides,
    }}


@router.get("/positions")
async def get_positions():
    """Return actual KIS holdings with persisted trailing-stop state."""
    endpoint = "/api/v1/trading-monitor/positions"
    logger.info("START: GET %s", endpoint)
    try:
        account_payload = _build_balance_payload(await get_kis_balance())
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
