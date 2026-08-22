"""Phase 3(2026-08-22) — Risk Profile → Regime 손절 통합 롤백스위치 검증.

engine.stop_source="profile"(기본) 면 종목별 프로필 손절 유지(라이브 무변화),
"regime" 이면 당일 레짐SET(applied_settings.stop_loss_rate)로 손절/트레일 단일출처.
필드명 매핑: 레짐 stop_loss_rate → 프로필 필드명 initial_stop_loss.
"""
import backend.services.engine.rule_resolver as rr


def _args(profile_stop=-0.018):
    return dict(
        symbol_code="005930",
        base_rulepack={"id": "base"},
        profile_pack={"profiles": {"MID_VOL": {
            "initial_stop_loss": profile_stop,
            "trailing_activate_profit": 0.015,
            "trailing_stop_rate": 0.010,
        }}},
        daily_plan={"symbol_assignments": [{"code": "005930", "profile": "MID_VOL"}]},
        symbol_overrides={},
        global_risk={"max_positions": 5},
        trade_date="2026-08-22",
    )


def test_stop_source_profile_default(monkeypatch):
    """기본 profile — 프로필 손절 유지(현행)."""
    monkeypatch.setattr(rr, "_get_active_rulepack_entry_rules", lambda d: {})
    monkeypatch.setattr("backend.services.settings_store.get_setting",
                        lambda k, d=None: "profile" if k == "engine.stop_source" else d)
    r = rr.resolve_symbol_rule(**_args(profile_stop=-0.018))
    assert r["initial_stop_loss"] == -0.018
    assert r.get("stop_source") != "regime"


def test_stop_source_regime_overrides_with_set(monkeypatch):
    """regime — 당일 레짐SET stop_loss_rate로 대체(필드명 매핑)."""
    monkeypatch.setattr(rr, "_get_active_rulepack_entry_rules", lambda d: {})
    monkeypatch.setattr("backend.services.settings_store.get_setting",
                        lambda k, d=None: "regime" if k == "engine.stop_source" else d)
    monkeypatch.setattr("backend.services.regime_set_service.get_today_application",
                        lambda d: {"applied_settings": {
                            "stop_loss_rate": -0.012,
                            "trailing_activate_profit": 0.020,
                            "trailing_stop_rate": 0.008,
                        }})
    r = rr.resolve_symbol_rule(**_args(profile_stop=-0.018))
    assert r["initial_stop_loss"] == -0.012      # 프로필 -0.018 대신 레짐 -0.012
    assert r["trailing_activate_profit"] == 0.020
    assert r["trailing_stop_rate"] == 0.008
    assert r["stop_source"] == "regime"


def test_stop_source_regime_falls_back_when_no_application(monkeypatch):
    """regime인데 당일 적용SET 없으면 프로필 유지(fail-safe)."""
    monkeypatch.setattr(rr, "_get_active_rulepack_entry_rules", lambda d: {})
    monkeypatch.setattr("backend.services.settings_store.get_setting",
                        lambda k, d=None: "regime" if k == "engine.stop_source" else d)
    monkeypatch.setattr("backend.services.regime_set_service.get_today_application",
                        lambda d: None)
    r = rr.resolve_symbol_rule(**_args(profile_stop=-0.018))
    assert r["initial_stop_loss"] == -0.018      # 적용SET 없음 → 프로필 유지
