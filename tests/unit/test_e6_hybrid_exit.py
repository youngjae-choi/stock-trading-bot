"""E6 하이브리드 트레일 청산 오버라이드 — 상승/폭등장 전용(2026-09-18 상승장 필승패턴).

권위 지점: rule_resolver.resolve_symbol_rule — trailing_activate_profit/trailing_stop_rate의
최종 결정처(add_position이 이 캐시된 final_rule을 읽음). 당일 application의 kospi_change_pct/vix로
classify_regime_5tier를 재분류해 surge↔up을 구분한다(레짐SET regime_label은 SET 4종이라 못 구분).

- surge → (+3% 발동, 2% 트레일) / up·risk_on → (+2% 발동, 1.5% 트레일)
- flat/down/risk_off/volatile → 오버라이드 없음(레짐SET 값 유지 = 불변)
- exit_hybrid_mode=off → 어디에도 오버라이드 없음
"""
from __future__ import annotations

import backend.services.regime_set_service as rss
import backend.services.settings_store as ss
from backend.services.engine.rule_resolver import resolve_symbol_rule

_TRADE_DATE = "2026-09-18"

# E6 하이브리드 기본값(코드기본과 동일)
_E6_SETTINGS = {
    "engine.stop_source": "profile",          # regime stop_source 경로는 이 테스트 범위 밖(트레일만 검증)
    "engine.exit_hybrid_mode": "enforce",
    "engine.exit_riskon_trail_activate": 0.02,
    "engine.exit_riskon_trail_stop": 0.015,
    "engine.exit_surge_trail_activate": 0.03,
    "engine.exit_surge_trail_stop": 0.02,
}


def _install(monkeypatch, kospi_change, vix=None, overrides=None):
    """settings getter + 당일 application(kospi/vix)만 세팅하고 나머지 SSOT 경로는 스텁."""
    cfg = dict(_E6_SETTINGS, **(overrides or {}))
    monkeypatch.setattr(ss, "get_setting", lambda k, d=None: cfg.get(k, d))
    # 당일 application — 트레일 오버라이드가 5장세 재분류에 쓰는 kospi/vix만 필요.
    fake_app = {
        "regime_label": "risk_on",   # SET 라벨(surge/up 구분 못함 — 재분류가 핵심)
        "kospi_change_pct": kospi_change,
        "vix_value": vix,
        "applied_settings": {},
    }
    monkeypatch.setattr(rss, "get_today_application", lambda td: fake_app)


def _resolve(monkeypatch, **kwargs):
    """최소 레이어로 resolve_symbol_rule 호출 — 트레일 오버라이드 결과만 관찰."""
    _install(monkeypatch, **kwargs)
    base = {"id": "b", "version": "1"}
    profile_pack = {"profiles": {"MID_VOL": {}}}
    # regime SET 값(오버라이드 안 걸리는 레짐에서 이 값이 유지돼야 함 = 불변 증거)
    daily_plan = None
    global_risk = {"max_position_rate_per_stock": 0.15, "max_positions": 19,
                   "force_exit_time": "15:20:00", "new_entry_cutoff_time": "15:10:00"}
    return resolve_symbol_rule(
        symbol_code="005930", base_rulepack=base, profile_pack=profile_pack,
        daily_plan=daily_plan, symbol_overrides={}, global_risk=global_risk,
        trade_date=_TRADE_DATE,
    )


def test_surge_regime_overrides_wider_trail(monkeypatch):
    """폭등장(kospi +3% ≥ surge 2.5%) → +3% 발동·2% 트레일."""
    final = _resolve(monkeypatch, kospi_change=3.0)
    assert final["trailing_activate_profit"] == 0.03
    assert final["trailing_stop_rate"] == 0.02
    assert final.get("exit_hybrid") == "surge"


def test_up_regime_overrides_tight_trail(monkeypatch):
    """상승장(kospi +1.0%, up 임계 0.5~surge 2.5% 사이) → +2% 발동·1.5% 트레일."""
    final = _resolve(monkeypatch, kospi_change=1.0)
    assert final["trailing_activate_profit"] == 0.02
    assert final["trailing_stop_rate"] == 0.015
    assert final.get("exit_hybrid") == "up"


def test_flat_regime_no_override(monkeypatch):
    """보합(kospi +0.2%, up 임계 0.5 미만) → 오버라이드 없음(레짐SET/프로필 값 유지)."""
    final = _resolve(monkeypatch, kospi_change=0.2)
    assert "exit_hybrid" not in final
    # 오버라이드 미적용이면 트레일 키는 프로필/기본 경로 그대로(강제 세팅 안 됨)


def test_down_regime_no_override(monkeypatch):
    """하락(kospi -2.0% ≤ down -1.5%) → 오버라이드 없음."""
    final = _resolve(monkeypatch, kospi_change=-2.0)
    assert "exit_hybrid" not in final


def test_volatile_regime_no_override(monkeypatch):
    """변동성장(VIX>28) → 오버라이드 없음(상승/폭등 아님)."""
    final = _resolve(monkeypatch, kospi_change=3.0, vix=35.0)
    assert "exit_hybrid" not in final


def test_hybrid_mode_off_no_override_anywhere(monkeypatch):
    """exit_hybrid_mode=off → 폭등장이라도 오버라이드 없음(구동작)."""
    final = _resolve(monkeypatch, kospi_change=3.0, overrides={"engine.exit_hybrid_mode": "off"})
    assert "exit_hybrid" not in final


def test_override_values_are_settings_driven(monkeypatch):
    """오버라이드 값은 하드코딩이 아니라 설정에서 읽는다."""
    final = _resolve(monkeypatch, kospi_change=3.0, overrides={
        "engine.exit_surge_trail_activate": 0.05,
        "engine.exit_surge_trail_stop": 0.04,
    })
    assert final["trailing_activate_profit"] == 0.05
    assert final["trailing_stop_rate"] == 0.04
