"""§A-7#5 배선 — SET 선택 regime을 설정기반 5장세로 (regime.set_source=5tier).

check_intraday_regime이 set_source=5tier일 때 쓰는 매핑:
  regime_to_set(classify_regime_5tier(kospi, vix)) → SET 라벨(risk_on/neutral/risk_off/volatile).
기본 set_source=judge(현행 하드코딩)라 활성 전 라이브 무변화. 이 테스트는 5tier 경로의 산출을 고정.
"""
from backend.services.engine.market_sensing import classify_regime_5tier, regime_to_set


def _set_label(kospi, vix):
    # 코드 기본 임계 사용(getter가 default 반환) — down_pct-1.5/up_pct0.5/surge_pct2.5/vix_volatile28
    r5 = classify_regime_5tier(kospi, vix, getter=lambda k, d=None: d)
    return regime_to_set(r5)


def test_5tier_set_mapping_down_up_flat():
    assert _set_label(-2.0, 20.0) == "risk_off"   # 하락(<-1.5)
    assert _set_label(1.0, 18.0) == "risk_on"      # 상승(>0.5)
    assert _set_label(0.0, 20.0) == "neutral"      # 보합


def test_5tier_set_mapping_surge_and_volatile():
    assert _set_label(3.0, 18.0) == "risk_on"      # 폭등(>2.5)=상승 사이징 티어→risk_on
    assert _set_label(0.5, 30.0) == "volatile"     # 고VIX(>28)→volatile(직교)


# ---------------------------------------------------------------------------
# _resolve_set_regime dispatch — set_source 스위치 (활성 2026-08-23)
# ---------------------------------------------------------------------------
import backend.services.settings_store as _ss
from backend.services.engine.intraday_regime_monitor import _resolve_set_regime


def _patch(monkeypatch, overrides):
    monkeypatch.setattr(_ss, "get_setting", lambda k, d=None: overrides.get(k, d))


def test_resolve_set_regime_uses_5tier(monkeypatch):
    """set_source=5tier → classify_regime_5tier→regime_to_set 경로, source=5tier:*."""
    _patch(monkeypatch, {"regime.set_source": "5tier"})
    regime, source = _resolve_set_regime(-2.0, 20.0, "risk_on")  # ib_regime 무시됨
    assert regime == "risk_off"
    assert source.startswith("5tier:")


def test_resolve_set_regime_5tier_volatile(monkeypatch):
    """고VIX(>28)면 5tier도 volatile SET."""
    _patch(monkeypatch, {"regime.set_source": "5tier"})
    regime, source = _resolve_set_regime(0.5, 30.0, None)
    assert regime == "volatile"


def test_resolve_set_regime_judge_prefers_index_board(monkeypatch):
    """롤백 judge + live_driver off → index-board regime 우선."""
    _patch(monkeypatch, {"regime.set_source": "judge",
                         "regime.intraday_live_driver_enabled": False})
    regime, source = _resolve_set_regime(0.0, 20.0, "risk_on")
    assert regime == "risk_on"
    assert source == "index-board"


def test_resolve_set_regime_judge_live_driver(monkeypatch):
    """judge + live_driver on → 실시간 _judge_regime(judge_live)."""
    _patch(monkeypatch, {"regime.set_source": "judge",
                         "regime.intraday_live_driver_enabled": True})
    regime, source = _resolve_set_regime(-2.0, 20.0, "risk_on")
    assert regime == "risk_off"  # _judge_regime(-2.0) = risk_off, ib 무시
    assert source == "judge_live"
