"""전략 사양 드리프트 대조 로직 — 의도 vs 실측 불일치 감지.

STRATEGY_SPEC.md의 SSOT를 지탱하는 compute_drift가 (a)일치 시 무경보,
(b)설정 변조·누락·레짐 SET 변조를 모두 잡는지 회귀 보호한다.
"""
from __future__ import annotations

from backend.services.engine import strategy_spec
from backend.services.engine.strategy_spec import (
    CONFORMANCE,
    check_conformance,
    compute_drift,
)


def test_no_drift_when_live_matches_intent():
    intent = {"engine.mode": "enforce", "engine.cap": 4.0, "engine.flag": False}
    live = {"engine.mode": "enforce", "engine.cap": 4.0, "engine.flag": False}
    sets_i = {"risk_on": {"stop_loss_rate": -0.035, "max_positions": 12}}
    sets_l = {"risk_on": {"stop_loss_rate": -0.035, "max_positions": 12}}
    assert compute_drift(intent, live, sets_i, sets_l) == []


def test_detects_value_mismatch():
    intent = {"engine.cap": 4.0}
    live = {"engine.cap": 15.0}  # 고점추격 상한이 의도(4)와 다르게 15로 벌어짐
    drift = compute_drift(intent, live, {}, {})
    assert len(drift) == 1
    assert "engine.cap" in drift[0]


def test_detects_missing_setting():
    intent = {"engine.mode": "enforce"}
    drift = compute_drift(intent, {}, {}, {})  # DB에 키 없음
    assert len(drift) == 1
    assert "미설정" in drift[0]


def test_detects_bool_mismatch_not_numeric_coerced():
    # False 의도인데 실측 True — bool은 숫자 허용오차로 뭉개지면 안 됨
    drift = compute_drift({"engine.flag": False}, {"engine.flag": True}, {}, {})
    assert len(drift) == 1


def test_detects_regime_set_field_drift():
    sets_i = {"risk_on": {"stop_loss_rate": -0.035}}
    sets_l = {"risk_on": {"stop_loss_rate": -0.09}}  # 손절폭이 의도 벗어남
    drift = compute_drift({}, {}, sets_i, sets_l)
    assert any("risk_on.stop_loss_rate" in d for d in drift)


def test_float_tolerance_no_false_positive():
    # 부동소수 미세오차는 드리프트 아님
    drift = compute_drift({"x": -0.035}, {"x": -0.03500000001}, {}, {})
    assert drift == []


def test_code_default_absent_is_ok():
    # 코드기본 레버가 DB에 없음 = 정상(코드기본대로 동작), 드리프트 아님
    drift = compute_drift({}, {}, {}, {}, intent_code_defaults={"engine.churn": 2})
    assert drift == []


def test_code_default_override_flagged():
    # 코드기본 레버가 DB에 '다른 값'으로 오버라이드되면 의도이탈 = 드리프트
    drift = compute_drift({}, {"engine.churn": 5}, {}, {}, intent_code_defaults={"engine.churn": 2})
    assert len(drift) == 1
    assert "오버라이드" in drift[0] and "engine.churn" in drift[0]


def test_code_default_matching_db_is_ok():
    # 코드기본과 같은 값이 DB에 명시돼 있으면 정상
    drift = compute_drift({}, {"engine.churn": 2}, {}, {}, intent_code_defaults={"engine.churn": 2})
    assert drift == []


def test_conformance_current_implementation_matches_ssot():
    # 지금 구현이 SSOT 주장(코드심볼·설정)과 맞물려 있어야 한다
    assert check_conformance() == []


def test_conformance_catches_missing_symbol(monkeypatch):
    # SSOT가 없는 구현을 주장하면 conformance가 잡아야 한다("SSOT부터 고쳐" 신호)
    fake = list(CONFORMANCE) + [("가짜 주장", "함수가_존재하지_않음_xyz", None)]
    monkeypatch.setattr(strategy_spec, "CONFORMANCE", fake)
    issues = check_conformance()
    assert any("함수가_존재하지_않음_xyz" in i for i in issues)


def test_conformance_catches_untracked_setting(monkeypatch):
    # SSOT가 감시 안 되는 설정을 주장하면 잡아야 한다
    fake = list(CONFORMANCE) + [("가짜", "resolve_conviction", "engine.존재안함_xyz")]
    monkeypatch.setattr(strategy_spec, "CONFORMANCE", fake)
    issues = check_conformance()
    assert any("존재안함_xyz" in i for i in issues)
