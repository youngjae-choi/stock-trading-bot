"""폭락 반등 가드 + 변동성 입력(VIX 범위검사·KOSPI 실현변동성) — 2026-10-16 폭락 2주 관찰 반영."""
from backend.services.engine.intraday_regime_monitor import (
    _sanitize_vix,
    crash_rebound_guard,
    kospi_realized_vol,
    regime_vol_input,
)

# 실제 KOSPI 종가(daily_review_reports) 10-01 ~ 10-15
CRASH = [6961.32, 6995.86, 6939.26, 6816.34, 6666.92, 6394.26, 6038.17, 6028.44, 5556.31]
CALM = [3000 * (1 + 0.001 * i) for i in range(11)]


def _g(over=None):
    over = over or {}
    return lambda k, d=None: over.get(k, d)


def test_sanitize_vix_rejects_misparse():
    assert _sanitize_vix(3.7) is None  # 10-12 index-board 오입력
    assert _sanitize_vix(None) is None
    assert _sanitize_vix(15.2) == 15.2


def test_realized_vol_detects_korean_crash():
    rv = kospi_realized_vol(CRASH)
    assert rv is not None and rv > 28  # → 5장세 volatile(regime.vix_volatile 28)
    assert kospi_realized_vol(CALM) < 5
    assert kospi_realized_vol(CRASH[:4]) is None  # 표본 부족


def test_regime_vol_input_takes_max_and_rollback():
    assert regime_vol_input(15.0, 45.0, _g()) == 45.0
    assert regime_vol_input(3.7, None, _g()) is None
    assert regime_vol_input(15.0, 45.0, _g({"regime.vol_source": "vix"})) == 15.0


def test_crash_guard_blocks_rebound_risk_on():
    # 10-16 판정 시점: 직전 종가 5556 vs 5거래일 전 6666 → −16.7%
    reg, note = crash_rebound_guard("risk_on", CRASH, _g())
    assert reg == "neutral" and "crash_rebound_guard" in note


def test_crash_guard_inactive_when_calm_or_off_or_not_risk_on():
    assert crash_rebound_guard("risk_on", CALM, _g()) == ("risk_on", None)
    assert crash_rebound_guard("risk_on", CRASH, _g({"regime.crash_rebound_guard": False})) == ("risk_on", None)
    assert crash_rebound_guard("risk_off", CRASH, _g()) == ("risk_off", None)
    assert crash_rebound_guard("risk_on", CRASH[:3], _g()) == ("risk_on", None)
