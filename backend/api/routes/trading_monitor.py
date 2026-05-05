"""Trading Monitor API — 매수 대기 후보 + 보유 포지션 + 매수 준비도 조회."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any
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


def _latest_stop_states() -> dict[str, dict[str, Any]]:
    """Return the newest persisted stop state by symbol code."""
    states: dict[str, dict[str, Any]] = {}
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM position_stop_states
            ORDER BY last_updated_at DESC
            """
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
    raw_candidates: list[dict] = []
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
    try:
        account_payload = _build_balance_payload(await get_kis_balance())
        account_positions = account_payload.get("positions", [])
    except Exception as exc:
        logger.warning("WARN: TradingMonitor KIS holdings lookup failed reason=%s", exc)
        account_positions = []

    stop_states = _latest_stop_states()
    submitted_orders = _latest_submitted_orders()
    memory_positions = {p.get("symbol"): p for p in position_manager.get_positions()}

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
        memory_pos = memory_positions.get(symbol, {})
        order = submitted_orders.get(symbol, {})
        stop_state = stop_states.get(symbol) or _fallback_stop_state(symbol, entry_price)

        positions.append({
            "position_id": stop_state.get("position_id") or memory_pos.get("position_id") or f"{symbol}-account",
            "symbol": symbol,
            "name": holding.get("name") or memory_pos.get("name") or order.get("name") or "",
            "qty": qty,
            "entry_price": entry_price,
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
            "source": "kis_account",
        })

    return {"ok": True, "payload": {"positions": positions, "count": len(positions)}}


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
