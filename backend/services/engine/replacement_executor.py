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


def _setting_float(key: str, default: float) -> float:
    try:
        return float(get_setting(key, default) or default)
    except (TypeError, ValueError):
        return default


async def _resolve_swap_target(
    cur: str, new: str, sig: dict[str, Any], cand_map: dict[str, dict[str, Any]]
) -> tuple[str, dict[str, Any], float] | None:
    """스왑 대상 결정 — **약체 매도 전** 진입게이트 사전검증(2026-09-05).

    원 대상(고score)이 게이트를 통과하면 그대로 쓰고, 막히면(주로 VWAP 위 추격) cand_map에서
    **게이트를 통과하는 최고 score 대안**(현 종목 대비 threshold 우위 유지)으로 보정한다. 통과
    후보가 없으면 None → 스왑 보류(약체 유지). 이로써 "약체 팔고 대상 못 사서 현금 유휴"를 막고,
    교체 대상을 모멘텀→게이트통과(눌림) 후보로 정렬 보정한다. (PM 결정 2026-09-05: 전 게이트·정렬 포함)
    """
    from .decision_engine import decision_engine
    from .replacement_signal import _candidate_score, _candidate_symbol, _current_score, _today

    cand = cand_map.get(new) or {"symbol": new, "name": sig.get("new_name", "")}
    price = _candidate_price(cand)
    if price > 0:
        ok, reason = decision_engine.entry_precheck(new, cand, price)
        if ok:
            return new, cand, price
        logger.info("INFO: 교체 원대상 게이트 미통과 — 대안 탐색 new=%s reason=%s", new, reason)

    if not cand_map:
        return None
    try:
        cur_score = _current_score({"symbol": cur}, _today())
    except Exception:
        cur_score = 0.0
    threshold = _setting_float("intraday_refresh.replacement_score_gap", 0.15)
    for alt in sorted(cand_map.values(), key=_candidate_score, reverse=True):
        s = _candidate_symbol(alt)
        if not s or s in (cur, new):
            continue
        if cur_score > 0 and _candidate_score(alt) < cur_score + threshold:
            break  # score 내림차순 — 이하는 전부 우위 미달
        p = _candidate_price(alt)
        if p <= 0:
            continue
        ok, _r = decision_engine.entry_precheck(s, alt, p)
        if ok:
            logger.info("SWAP-ALT: 교체 대상 보정 — 게이트 통과 대안 선택 new=%s → %s", new, s)
            return s, alt, p
    return None


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
        # ★ 약체 매도 전에 대상(또는 게이트 통과 대안)을 먼저 확정 — 통과 후보 없으면 스왑 보류
        # (약체 팔고 대상 못 사서 현금 유휴되던 사고 방지, 2026-09-05).
        target = await _resolve_swap_target(cur, new, sig, cand_map)
        if target is None:
            logger.info("INFO: 교체 보류 — 대상·대안 모두 진입게이트 미통과, 약체 유지 cur=%s new=%s", cur, new)
            continue
        buy_symbol, candidate, price = target
        sell = await _sell_position(cur, reason=f"replacement_swap->{buy_symbol}")
        if not sell.get("ok"):
            logger.warning("WARN: 교체 매도 실패 cur=%s — %s", cur, sell.get("reason"))
            continue
        buy = await _buy_candidate(buy_symbol, candidate, price)
        _last_swap_at[cur] = _now_ts()
        _last_swap_at[buy_symbol] = _now_ts()
        executed += 1
        logger.warning("SWAP: 교체 실행 SELL %s → BUY %s (gap=%.3f, buy_ok=%s)",
                       cur, buy_symbol, float(sig.get("score_gap") or 0), buy.get("ok"))
    return {"ok": True, "enabled": True, "executed": executed}
