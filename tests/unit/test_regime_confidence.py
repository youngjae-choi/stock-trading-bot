"""Phase 2 — 전날 장후 sentiment vs 당일 아침 regime 정렬 신뢰도 보정 단위 테스트."""
from backend.services.regime_set_service import compute_confidence_adjustment


def test_aligned_boosts():
    assert compute_confidence_adjustment("risk_on", "risk_on") == ("aligned", 0.10)
    assert compute_confidence_adjustment("risk_off", "risk_off") == ("aligned", 0.10)


def test_opposite_penalizes():
    assert compute_confidence_adjustment("risk_on", "risk_off") == ("conflict", -0.15)
    assert compute_confidence_adjustment("risk_off", "risk_on") == ("conflict", -0.15)


def test_volatile_penalizes():
    label, adj = compute_confidence_adjustment("neutral", "volatile")
    assert label == "volatile" and adj == -0.05
    label2, adj2 = compute_confidence_adjustment("volatile", "risk_on")
    assert label2 == "volatile" and adj2 == -0.05


def test_none_evening_no_change():
    assert compute_confidence_adjustment("risk_on", None) == ("none", 0.0)


def test_neutral_mix_no_change():
    assert compute_confidence_adjustment("risk_on", "neutral") == ("neutral", 0.0)
    assert compute_confidence_adjustment("neutral", "risk_off") == ("neutral", 0.0)
