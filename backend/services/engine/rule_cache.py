"""Rule Cache — 장 시작 시 종목별 최종 룰을 메모리에 캐시.

WS tick 처리 시 DB 접근 없이 O(1)로 룰 조회.
09:00 load_daily_rules() → 장중 get_rule() → 장마감 clear_cache()
"""

from __future__ import annotations

import logging
from typing import Any

from ..settings_store import get_setting
from .rule_resolver import (
    get_active_base_rulepack,
    get_active_daily_plan,
    get_active_profile_pack,
    get_symbol_overrides,
    resolve_symbol_rule,
)

logger = logging.getLogger("RuleCache")

_cache: dict[str, dict[str, Any]] = {}   # {symbol_code: final_rule}
_meta: dict[str, Any] = {}               # 오늘 로드된 메타 정보


def _global_risk() -> dict[str, Any]:
    """system_settings에서 Global Risk Guard 값 조회."""
    return {
        "daily_loss_limit": float(get_setting("risk.daily_loss_limit_percent", -2.0) or -2.0),
        "max_positions": int(get_setting("risk.max_positions", 5) or 5),
        "max_position_rate_per_stock": float(get_setting("risk.max_position_rate_per_stock", 0.10) or 0.10),
        "force_exit_time": _clock_with_seconds(get_setting("risk.force_exit_time", "15:20") or "15:20", "15:20:00"),
        "new_entry_cutoff_time": _clock_with_seconds(
            get_setting("risk.new_entry_cutoff_time", "15:10") or "15:10",
            "15:10:00",
        ),
    }


def _clock_with_seconds(value: Any, default: str) -> str:
    """Normalize HH:MM settings into HH:MM:SS rule values."""
    text = str(value or "").strip()
    parts = text.split(":")
    if len(parts) == 2 and all(part.isdigit() for part in parts):
        return f"{int(parts[0]):02d}:{int(parts[1]):02d}:00"
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        return f"{int(parts[0]):02d}:{int(parts[1]):02d}:{int(parts[2]):02d}"
    return default


def load_daily_rules(trade_date: str, symbol_codes: list[str]) -> int:
    """S6 시작 시 호출 — 오늘 전체 후보 종목 룰을 메모리에 캐시.

    Returns:
        캐시된 종목 수.
    """
    global _cache, _meta
    _cache = {}

    base = get_active_base_rulepack()
    pack = get_active_profile_pack()
    plan = get_active_daily_plan(trade_date)
    overrides = get_symbol_overrides()
    risk = _global_risk()

    for code in symbol_codes:
        _cache[code] = resolve_symbol_rule(
            symbol_code=code,
            base_rulepack=base,
            profile_pack=pack,
            daily_plan=plan,
            symbol_overrides=overrides,
            global_risk=risk,
            trade_date=trade_date,
        )

    _meta = {
        "trade_date": trade_date,
        "base_rulepack_id": base.get("id", ""),
        "risk_profile_pack_id": pack.get("id", ""),
        "daily_plan_id": plan.get("id", "") if plan else "",
        "cached_count": len(_cache),
    }
    logger.info("SUCCESS: [RuleCache] loaded symbols=%d date=%s base=%s pack=%s",
                len(_cache), trade_date, _meta["base_rulepack_id"], _meta["risk_profile_pack_id"])
    return len(_cache)


def get_rule(symbol_code: str) -> dict[str, Any] | None:
    """WS tick 처리 시 호출 — DB 접근 없이 캐시에서 반환."""
    return _cache.get(symbol_code)


def get_meta() -> dict[str, Any]:
    """현재 캐시 메타 정보 반환."""
    return dict(_meta)


def clear_cache() -> None:
    """장마감 후 호출 — 캐시 초기화."""
    global _cache, _meta
    count = len(_cache)
    _cache = {}
    _meta = {}
    logger.info("SUCCESS: [RuleCache] cleared count=%d", count)


def get_all_cached() -> dict[str, dict[str, Any]]:
    """전체 캐시 반환 (API 조회용)."""
    return dict(_cache)
