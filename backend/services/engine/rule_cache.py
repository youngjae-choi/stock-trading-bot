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

# 장중 유입 종목(모멘텀 스캔·장중 재선별)의 휴리스틱 프로파일 오버레이.
# load_daily_rules가 재호출될 때마다 캐시가 통째로 재구성되므로,
# 여기 등록된 배정을 로드 시 재적용한다. S5 plan 배정 종목은 절대 덮어쓰지 않는다.
_intraday_profiles: dict[str, dict[str, str]] = {}  # {symbol: {profile, reason}}
_plan_assigned: set[str] = set()                    # 오늘 plan symbol_assignments 코드

_PROFILES = ("LOW_VOL", "MID_VOL", "HIGH_VOL", "THEME_SPIKE")


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

    # 거래일이 바뀌면 전일 장중 프로파일 오버레이는 무효
    if _meta.get("trade_date") and _meta.get("trade_date") != trade_date:
        _intraday_profiles.clear()

    base = get_active_base_rulepack()
    pack = get_active_profile_pack()
    plan = get_active_daily_plan(trade_date)
    overrides = get_symbol_overrides()
    risk = _global_risk()

    _plan_assigned.clear()
    if plan:
        for a in plan.get("symbol_assignments", []) or []:
            code = str(a.get("code") or "").strip()
            if code:
                _plan_assigned.add(code)

    for code in symbol_codes:
        plan_for_symbol = plan
        intraday = _intraday_profiles.get(code)
        if intraday and code not in _plan_assigned:
            # plan 미배정 장중 유입 종목 → 휴리스틱 배정을 synthetic assignment로 주입.
            # resolve_symbol_rule의 레이어 병합(프로파일 사이징·청산 파라미터 포함)을 그대로 재사용한다.
            synthetic = dict(plan) if plan else {}
            assignments = list((plan or {}).get("symbol_assignments") or [])
            assignments.append(
                {"code": code, "profile": intraday["profile"], "reason": intraday["reason"]}
            )
            synthetic["symbol_assignments"] = assignments
            plan_for_symbol = synthetic
        _cache[code] = resolve_symbol_rule(
            symbol_code=code,
            base_rulepack=base,
            profile_pack=pack,
            daily_plan=plan_for_symbol,
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


def set_intraday_profile(symbol_code: str, profile: str, reason: str) -> bool:
    """장중 유입 종목의 휴리스틱 Risk Profile 배정을 등록한다.

    다음 load_daily_rules 재로드에서도 유지된다(오버레이).
    S5 plan symbol_assignments에 이미 배정된 종목은 거부한다(절대 미덮어쓰기).

    Args:
        symbol_code: 종목코드.
        profile: LOW_VOL/MID_VOL/HIGH_VOL/THEME_SPIKE.
        reason: 배정 사유 (assignment_reason으로 전파).

    Returns:
        등록 여부. plan 배정 종목이거나 profile이 유효하지 않으면 False.
    """
    code = str(symbol_code or "").strip()
    if not code or profile not in _PROFILES:
        return False
    if code in _plan_assigned:
        logger.info("INFO: [RuleCache] intraday profile 거부 — plan 배정 종목 symbol=%s", code)
        return False
    _intraday_profiles[code] = {"profile": profile, "reason": str(reason or "")}
    # 이미 캐시에 룰이 있으면 즉시 반영 대신 다음 load에서 일괄 적용해도 되지만,
    # add_momentum_candidates는 등록 직후 load_daily_rules를 호출하므로 별도 처리 불필요.
    return True


def get_intraday_profiles() -> dict[str, dict[str, str]]:
    """현재 등록된 장중 프로파일 오버레이 반환 (조회용 사본)."""
    return {k: dict(v) for k, v in _intraday_profiles.items()}


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
    _intraday_profiles.clear()
    _plan_assigned.clear()
    logger.info("SUCCESS: [RuleCache] cleared count=%d", count)


def get_all_cached() -> dict[str, dict[str, Any]]:
    """전체 캐시 반환 (API 조회용)."""
    return dict(_cache)
