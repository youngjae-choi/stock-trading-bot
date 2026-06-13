"""classify_regime_heuristic 단위 테스트 — index-board 텍스트→regime 분류."""
from backend.services.engine.market_tone import classify_regime_heuristic


def test_risk_on():
    r = classify_regime_heuristic("간밤 위험선호 회복, 강세 출발 예상, 반등 기대")
    assert r["regime"] == "risk_on" and r["tone"] == "positive"


def test_risk_off():
    r = classify_regime_heuristic("위험회피 심리 확산, 급락·약세 지속, 경계 필요")
    assert r["regime"] == "risk_off" and r["tone"] == "negative"


def test_ambiguous_defaults_neutral():
    # on=1(반등) off=1(부진) → net=0 → |net|<THRESHOLD → neutral (보수적)
    r = classify_regime_heuristic("기술적 반등 시도가 있었으나 전반적으로 부진한 흐름")
    assert r["regime"] == "neutral"


def test_empty_neutral():
    assert classify_regime_heuristic("")["regime"] == "neutral"


def test_volatile():
    r = classify_regime_heuristic("변동성 확대, 혼조세 지속, 불확실성 잔존")
    assert r["regime"] == "volatile" and r["tone"] == "neutral"


def test_risk_level_from_vix():
    r = classify_regime_heuristic("강세 강세 위험선호 회복", {"vix": {"price": 35.0}})
    assert r["risk_level"] == "high"


def test_risk_level_low_vix():
    r = classify_regime_heuristic("강세 강세 위험선호 회복", {"vix": {"price": 15.0}})
    assert r["risk_level"] == "low"


def test_risk_level_normal_default():
    r = classify_regime_heuristic("강세 강세 위험선호 회복")
    assert r["risk_level"] == "normal"
