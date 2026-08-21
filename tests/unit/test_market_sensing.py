"""시장감지 엔진 — 5장세 판정 + 전환(방향) 감지 검증 (엔진②).

레벨(5장세)과 방향(전환)을 결정론으로 판단. 8/18 반전 케이스 포함.
"""
from __future__ import annotations

from backend.services.engine.market_sensing import (
    classify_regime_5tier,
    detect_transition,
    regime_to_set,
)

_CFG = {
    "regime.crash_pct": -2.0, "regime.down_pct": -1.5, "regime.up_pct": 0.5,
    "regime.surge_pct": 2.5, "regime.vix_volatile": 28.0,
    "regime.down_transition_pp": -1.0, "regime.up_transition_pp": 1.0,
    "regime.li_lean_weight": 0.25,
}


def _g(key, default=None):
    return _CFG.get(key, default)


def test_5tier_levels():
    assert classify_regime_5tier(-2.5, getter=_g) == "crash"
    assert classify_regime_5tier(-1.6, getter=_g) == "down"
    assert classify_regime_5tier(0.0, getter=_g) == "flat"
    assert classify_regime_5tier(1.2, getter=_g) == "up"
    assert classify_regime_5tier(3.0, getter=_g) == "surge"


def test_surge_distinct_from_up():
    # 폭등(+2.5↑)이 상승과 구분됨 — 기존 시스템엔 없던 티어
    assert classify_regime_5tier(2.6, getter=_g) == "surge"
    assert classify_regime_5tier(2.4, getter=_g) == "up"


def test_vix_volatile_overrides():
    assert classify_regime_5tier(1.0, vix=30.0, getter=_g) == "volatile"


def test_li_lean_bias():
    # 경계(+0.4, up 임계 0.5 미만=flat)인데 강세 선행지표(+0.5 lean)면 up으로
    assert classify_regime_5tier(0.4, li_lean=0.0, getter=_g) == "flat"
    assert classify_regime_5tier(0.4, li_lean=0.5, getter=_g) == "up"  # 0.4+0.125=... 0.525>0.5


def test_transition_down_detects_8_18_reversal():
    # 8/18: 10:30 +2.77 → 11:00 +1.25 = -1.52%p → 하락전환
    assert detect_transition([2.77, 1.25], getter=_g) == "down_transition"


def test_transition_up():
    # 바닥 반등: -1.0 → +0.5 = +1.5%p → 상승전환
    assert detect_transition([-1.0, 0.5], getter=_g) == "up_transition"


def test_transition_none_when_flat():
    # 레벨은 높아도(둘 다 +2%대) 방향 변화 작으면 전환 아님
    assert detect_transition([2.5, 2.6], getter=_g) is None


def test_transition_level_agnostic():
    # 레벨이 아직 +여도(꺾임) 하락전환 — 8/18의 핵심(레벨 무관)
    assert detect_transition([4.0, 2.5], getter=_g) == "down_transition"


def test_transition_insufficient_data():
    assert detect_transition([1.0], getter=_g) is None
    assert detect_transition([], getter=_g) is None


def test_regime_to_set_mapping():
    assert regime_to_set("surge") == "risk_on"
    assert regime_to_set("crash") == "risk_off"
    assert regime_to_set("flat") == "neutral"
