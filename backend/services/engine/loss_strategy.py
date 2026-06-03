# backend/services/engine/loss_strategy.py
"""손실 분석 전략의 튜닝 대상 화이트리스트 + 가드레일 clamp + 패턴→설정변경 도출.

자동반영은 여기 정의된 매매 파라미터(flat system_settings)로만 가능하다.
운영 인프라 설정(스케줄/토큰)은 포함하지 않는다. 값은 (min, max)로 clamp한다.
"""
from __future__ import annotations

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
