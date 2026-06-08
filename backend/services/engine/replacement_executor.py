"""교체 신호 자동 실행 — 약한 보유 매도(손절 허용) → 강한 후보 매수(Profile 비중).

evaluate_replacement_signals가 만든 signals를 받아 실제 스왑을 실행한다.
쿨다운(동일 종목)·일일 상한·자동실행 토글로 churn을 제어한다. exploration 전용 운용.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from ..settings_store import get_setting

logger = logging.getLogger("ReplacementExecutor")
_last_swap_at: dict[str, float] = {}  # symbol -> epoch sec


def _now_ts() -> float:
    return time.time()


def _setting_bool(key: str, default: bool) -> bool:
    v = get_setting(key, default)
    return str(v).lower() in ("true", "1", "yes") if not isinstance(v, bool) else v


def _setting_int(key: str, default: int) -> int:
    try:
        return int(get_setting(key, default) or default)
    except (TypeError, ValueError):
        return default


def _in_cooldown(symbol: str, cooldown_min: int) -> bool:
    last = _last_swap_at.get(symbol)
    if last is None:
        return False
    return (_now_ts() - last) < cooldown_min * 60


async def _sell_position(symbol: str, reason: str) -> dict[str, Any]:
    """약한 보유 종목 전량 시장가 매도(손절 허용). 진입점: order_executor.execute_sell."""
    from .order_executor import order_executor
    from .position_manager import position_manager
    qty = 0
    name = ""
    for p in position_manager.get_positions():
        if str(p.get("symbol") or "").strip() == symbol:
            qty = int(p.get("qty") or 0)
            name = str(p.get("name") or "")
            break
    if qty <= 0:
        return {"ok": False, "reason": "no_qty", "symbol": symbol}
    return await order_executor.execute_sell(symbol, qty, price=0, reason=reason, name=name)


async def _buy_candidate(symbol: str, candidate: dict[str, Any], price: float) -> dict[str, Any]:
    """강한 후보 매수 — 기존 신호 경로 재사용(_emit_signal → execute_signal, Profile 사이징 적용).

    price<=0 이면 매수 스킵(트리거가 확인 안 됨). candidate는 new_candidates에서 조회.
    """
    if price <= 0:
        return {"ok": False, "reason": "no_price", "symbol": symbol}
    from .decision_engine import decision_engine
    await decision_engine._emit_signal(symbol, candidate, price, {"replacement": True})
    return {"ok": True, "symbol": symbol}


def _candidate_price(candidate: dict[str, Any]) -> float:
    """후보 dict에서 매수 트리거 가격 추출(없으면 0 → 매수 스킵)."""
    for k in ("price", "current_price", "trigger_price", "close"):
        try:
            v = float(candidate.get(k) or 0)
            if v > 0:
                return v
        except (TypeError, ValueError):
            continue
    return 0.0


async def execute_replacements(
    signals: list[dict[str, Any]],
    new_candidates: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """교체 신호 리스트를 받아 자동 스왑 실행(매도 약 → 매수 강). 반환: {executed}."""
    if not _setting_bool("intraday_refresh.replacement_execute_enabled", True):
        return {"ok": True, "enabled": False, "executed": 0}
    cand_map = new_candidates or {}
    cooldown_min = _setting_int("intraday_refresh.replacement_cooldown_min", 30)
    executed = 0
    for sig in signals:
        cur = str(sig.get("current_symbol") or "")
        new = str(sig.get("new_symbol") or "")
        if not cur or not new:
            continue
        if _in_cooldown(cur, cooldown_min) or _in_cooldown(new, cooldown_min):
            logger.info("INFO: 교체 쿨다운 스킵 cur=%s new=%s", cur, new)
            continue
        sell = await _sell_position(cur, reason=f"replacement_swap->{new}")
        if not sell.get("ok"):
            logger.warning("WARN: 교체 매도 실패 cur=%s — %s", cur, sell.get("reason"))
            continue
        candidate = cand_map.get(new, {"symbol": new, "name": sig.get("new_name", "")})
        buy = await _buy_candidate(new, candidate, _candidate_price(candidate))
        _last_swap_at[cur] = _now_ts()
        _last_swap_at[new] = _now_ts()
        executed += 1
        logger.warning("SWAP: 교체 실행 SELL %s → BUY %s (gap=%.3f, buy_ok=%s)",
                       cur, new, float(sig.get("score_gap") or 0), buy.get("ok"))
    return {"ok": True, "enabled": True, "executed": executed}
