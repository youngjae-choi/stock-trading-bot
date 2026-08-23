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
