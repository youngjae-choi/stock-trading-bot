"""상시 모멘텀 스캐너 — 3분마다 현재 movers 스캔 → 신규 적격 종목 발굴(LLM 없음).

발굴된 신규 종목은 decision_engine watchlist에 병합 추가되어 S6가 매수 판정한다.
exploration_mode 전용. 레짐 재선별(intraday_refresh)과 별개로 상시 동작.
설계서: docs/superpowers/specs/2026-06-08-continuous-momentum-scanner-design.md
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from ..settings_store import get_setting
from .exploration_gate import is_exploration_allowed

logger = logging.getLogger("MomentumScanner")
_recent_exit_at: dict[str, float] = {}  # symbol -> epoch (당일 청산 쿨다운)
_COOLDOWN_MIN = 10


def _now_ts() -> float:
    return time.time()


def _in_cooldown(symbol: str) -> bool:
    t = _recent_exit_at.get(symbol)
    return t is not None and (_now_ts() - t) < _COOLDOWN_MIN * 60


def note_exit(symbol: str) -> None:
    """포지션 청산 시 호출 — 당일 즉시 재편입 churn 방지(쿨다운 등록)."""
    _recent_exit_at[symbol] = _now_ts()


def _setting_bool(key: str, default: bool) -> bool:
    v = get_setting(key, default)
    return v if isinstance(v, bool) else str(v).lower() in ("true", "1", "yes")


def _pick_new_symbols(movers: list[dict[str, Any]], existing: set[str], held: set[str]) -> list[dict[str, Any]]:
    """현재 movers 중 신규(미감시·미보유·쿨다운 외) 적격 종목만 반환."""
    out: list[dict[str, Any]] = []
    for m in movers:
        sym = str(m.get("symbol") or "").strip()
        if not sym or sym in existing or sym in held or _in_cooldown(sym):
            continue
        if float(m.get("volume") or 0) <= 0:   # sanity: 거래 없는 종목 제외
            continue
        out.append(m)
    return out


async def _fetch_current_movers() -> list[dict[str, Any]]:
    """현재 등락률·거래량급증 상위 movers를 경량 조회(persist/LLM 없음).

    universe_filter의 merge 헬퍼(_merge_and_deduplicate)를 재사용한다.
    get_volume_rank/get_price_rank 은 {"items": [...], "count": N} 형태를 반환하므로
    ["items"] 를 추출해 병합 헬퍼에 전달한다(헬퍼는 list[dict] 를 반환).
    """
    from ..kis.domestic.universe_service import get_price_rank, get_volume_rank
    from .universe_filter import _merge_and_deduplicate
    _MAX = 60
    volume_result, change_result = await asyncio.gather(
        get_volume_rank(market_code="J", top_n=_MAX),
        get_price_rank(sort_by="change_rate", market_code="J", top_n=_MAX),
    )
    volume_items = volume_result.get("items", []) if isinstance(volume_result, dict) else list(volume_result)
    change_items = change_result.get("items", []) if isinstance(change_result, dict) else list(change_result)
    merged = _merge_and_deduplicate(volume_items, change_items)
    items = list(merged.values()) if isinstance(merged, dict) else list(merged)
    return items


async def run_momentum_scan() -> dict[str, Any]:
    """3분 틱 진입점. exploration 전용. 신규 적격 종목을 decision_engine에 추가."""
    if not is_exploration_allowed():
        return {"ok": True, "enabled": False, "reason": "exploration_off", "added": 0}
    if not _setting_bool("momentum_scan.enabled", True):
        return {"ok": True, "enabled": False, "reason": "disabled", "added": 0}
    try:
        movers = await _fetch_current_movers()
    except Exception as exc:
        logger.warning("WARN: [MomentumScan] movers 조회 실패 — %s", exc)
        return {"ok": False, "reason": str(exc), "added": 0}

    from .decision_engine import decision_engine
    from .position_manager import position_manager
    existing = set(getattr(decision_engine, "_candidates", {}).keys())
    held = {str(p.get("symbol") or "").strip() for p in position_manager.get_positions()}
    fresh = _pick_new_symbols(movers, existing=existing, held=held)
    if not fresh:
        logger.info("INFO: [MomentumScan] 신규 적격 0 (movers=%d existing=%d held=%d)", len(movers), len(existing), len(held))
        return {"ok": True, "enabled": True, "added": 0, "movers": len(movers)}

    result = await decision_engine.add_momentum_candidates(fresh)
    logger.info("INFO: [MomentumScan] movers=%d 신규편입=%s 구독=%s",
                len(movers), result.get("added"), result.get("subscribed"))
    return {"ok": True, "enabled": True, "added": result.get("added", 0),
            "subscribed": result.get("subscribed"), "movers": len(movers)}
