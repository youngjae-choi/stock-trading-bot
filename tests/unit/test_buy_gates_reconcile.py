"""④ 매수 게이트 단일화(get_playbook 통합) — reconcile_buy_gates 발산 감지 + 스위치.

라이브 RulePack(예: 7/23 min_ai_confidence 0.65·밴드 1.0~5.0)이 settings(0.60·1.5~4.0)와
다른 4중구조 발산을 드러내고, buy_gates_source=playbook 이면 settings로 단일화.
"""
from backend.services.engine.buy_engine import reconcile_buy_gates

# settings 권위값(get_playbook.gates가 읽음). getter 주입으로 고정.
_SETTINGS = {
    "engine.min_price_change_pct": 1.5,
    "engine.max_price_change_pct": 4.0,
    "engine.min_ai_confidence": 0.60,
    "engine.min_volume_ratio": 1.5,
    "engine.entry_vwap_pullback_mode": "enforce",
    "engine.confidence_gate_mode": "regime_defensive",
}


def _getter(source="legacy"):
    cfg = dict(_SETTINGS)
    cfg["engine.buy_gates_source"] = source
    return lambda k, d=None: cfg.get(k, d)


# 라이브 RulePack 발산 케이스(7/23 실측 모사)
_RULEPACK = {
    "min_price_change_pct": 1.0, "max_price_change_pct": 5.0,
    "min_ai_confidence": 0.65, "volume_ratio_min": 1.5,
    "profile_assigned": "MID_VOL",
}


def test_divergence_detected():
    """RulePack(1.0/5.0/0.65) vs settings(1.5/4.0/0.60) 발산 3건 감지."""
    eff, divs = reconcile_buy_gates(dict(_RULEPACK), "flat", getter=_getter("legacy"))
    keys = {d[0] for d in divs}
    assert keys == {"min_price_change_pct", "max_price_change_pct", "min_ai_confidence"}
    # volume은 동일(1.5) → 발산 아님


def test_legacy_keeps_rulepack():
    """legacy(기본): final_rule 그대로 — RulePack 우선(현행 동작 보존)."""
    eff, _ = reconcile_buy_gates(dict(_RULEPACK), "flat", getter=_getter("legacy"))
    assert eff["min_price_change_pct"] == 1.0
    assert eff["max_price_change_pct"] == 5.0
    assert eff["min_ai_confidence"] == 0.65


def test_playbook_overrides_to_settings():
    """playbook: 게이트키를 settings(권위)로 덮어 단일출처화."""
    eff, _ = reconcile_buy_gates(dict(_RULEPACK), "flat", getter=_getter("playbook"))
    assert eff["min_price_change_pct"] == 1.5
    assert eff["max_price_change_pct"] == 4.0
    assert eff["min_ai_confidence"] == 0.60
    assert eff["profile_assigned"] == "MID_VOL"  # 비게이트 필드는 보존


def test_no_divergence_when_aligned():
    """RulePack이 settings와 일치하면 발산 0."""
    aligned = {"min_price_change_pct": 1.5, "max_price_change_pct": 4.0,
               "min_ai_confidence": 0.60, "volume_ratio_min": 1.5}
    eff, divs = reconcile_buy_gates(aligned, "flat", getter=_getter("legacy"))
    assert divs == []


def test_missing_rulepack_keys_no_false_divergence():
    """final_rule에 키 없으면(빈 dict) 발산으로 잡지 않음(None skip)."""
    eff, divs = reconcile_buy_gates({}, "flat", getter=_getter("legacy"))
    assert divs == []
