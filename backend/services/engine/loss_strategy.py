# backend/services/engine/loss_strategy.py
"""손실 분석 전략의 튜닝 대상 화이트리스트 + 가드레일 clamp + 패턴→설정변경 도출.

자동반영은 여기 정의된 매매 파라미터(flat system_settings)로만 가능하다.
운영 인프라 설정(스케줄/토큰)은 포함하지 않는다. 값은 (min, max)로 clamp한다.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

# key -> (min, max). 매매 파라미터만.
TUNABLE_SETTINGS: dict[str, tuple[float, float]] = {
    "engine.min_price_change_pct": (0.5, 8.0),
    "engine.max_price_change_pct": (1.0, 15.0),
    "engine.min_volume_ratio": (1.0, 10.0),
    "risk.max_position_rate_per_stock": (0.01, 0.30),
    "risk.daily_loss_limit_percent": (-10.0, -0.5),
    "risk.max_positions": (1, 20),
}


def is_tunable(key: str) -> bool:
    """자동반영 가능한(화이트리스트) 설정 키인지."""
    return key in TUNABLE_SETTINGS


def clamp_setting(key: str, value: Any) -> float | None:
    """화이트리스트 키면 (min,max)로 clamp한 값을, 아니면 None을 반환한다."""
    if key not in TUNABLE_SETTINGS:
        return None
    low, high = TUNABLE_SETTINGS[key]
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return max(low, min(high, v))


_PATTERN_MIN_SAMPLE = 3


def _pattern_key(case: dict[str, Any]) -> str:
    """손실 원인 패턴 식별자 — 청산사유 기준(없으면 프로파일)."""
    return str(case.get("exit_reason") or case.get("assigned_profile") or "unknown")


def _strategy_for_pattern(pattern: str, cases: list[dict[str, Any]]) -> dict[str, Any] | None:
    """패턴별 설정변경 전략.
    - 초기손절 다발 → 진입 등락률 하한을 0.5%p 올려 추격 진입을 줄인다.
    - 트레일링손절 다발 → 거래량 배수 하한을 0.5 올려 약한 신호를 거른다.
    """
    from ..settings_store import get_setting

    if pattern == "INITIAL_STOP_LOSS":
        cur = float(get_setting("engine.min_price_change_pct", 3.0) or 3.0)
        return {"setting_key": "engine.min_price_change_pct", "new_value": cur + 0.5,
                "reason": f"초기손절 {len(cases)}건 — 추격 진입 축소"}
    if pattern == "TRAILING_STOP":
        cur = float(get_setting("engine.min_volume_ratio", 2.5) or 2.5)
        return {"setting_key": "engine.min_volume_ratio", "new_value": cur + 0.5,
                "reason": f"트레일링손절 {len(cases)}건 — 약신호 필터 강화"}
    return None


def derive_strategies(cases: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    """손실 case 들 → (자동반영 전략, 관찰 보류 전략). 패턴 표본 ≥ 3 만 반영."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for c in cases:
        groups[_pattern_key(c)].append(c)

    applied: list[dict] = []
    observing: list[dict] = []
    for pattern, group in groups.items():
        strat = _strategy_for_pattern(pattern, group)
        if not strat:
            continue
        strat = {**strat, "pattern": pattern, "sample": len(group)}
        if len(group) >= _PATTERN_MIN_SAMPLE and is_tunable(strat["setting_key"]):
            clamped = clamp_setting(strat["setting_key"], strat["new_value"])
            if clamped is not None:
                strat["new_value"] = clamped
                applied.append(strat)
        else:
            observing.append(strat)
    return applied, observing
