"""리더 진입 pullback 모드 — E6 강세근접VWAP (2026-09-24).

09-18 규명: 상승장 손실 뿌리 = ①추격(breakout=꼭지매수) ②laggard 매수. 스크리너가 강세 리더를
유니버스에 넣어도 daily plan이 laggard를 후보로 골라 손실. pullback 모드는 강세(cfo>0) 리더가
VWAP 눌림 구간[floor,ceiling]에 있을 때만 매수 → 추격·laggard 둘 다 회피. 상승장(risk_on) 전용.
검증: ①강세+밴드내 발동 ②laggard(cfo≤0) 차단 ③추격(>ceiling)·딥(<floor) 차단 ④비상승장 no-op.
"""
from __future__ import annotations

import asyncio

import backend.services.engine.decision_engine as de
from backend.services.engine.momentum_entry import _detect_leader_pullback, run_momentum_entries


def _bars(rows):
    return [{"bar_ts": t, "open": o, "high": h, "low": lo, "close": c, "volume": v}
            for (t, o, h, lo, c, v) in rows]


# ── 검출 로직: 강세 리더 VWAP 눌림 ──────────────────────────────────────────────

def test_pullback_fires_strong_near_vwap():
    # day_open=100, VWAP=102.5, last=102 → cfo +2%, vwap_dist -0.49% (밴드 [-3,+1] 내·강세)
    bars = _bars([("093000", 100, 104, 100, 103, 10), ("094000", 103, 104, 101, 102, 10)])
    sig = _detect_leader_pullback(bars, -3.0, 1.0, 0.0)
    assert sig is not None
    assert sig[3] == 2.0            # cfo +2%
    assert -3.0 <= (102 / sig[2] - 1) * 100 <= 1.0  # vwap_dist 밴드 내


def test_pullback_blocks_laggard():
    # last=98 < open=100 → cfo -2% (약체 laggard) → 차단
    bars = _bars([("093000", 100, 100, 98, 99, 10), ("094000", 99, 99, 97, 98, 10)])
    assert _detect_leader_pullback(bars, -3.0, 1.0, 0.0) is None


def test_pullback_blocks_chase_above_ceiling():
    # VWAP=105, last=110 → vwap_dist +4.76% > ceiling(+1) → 추격이라 차단(강세여도)
    bars = _bars([("093000", 100, 100, 100, 100, 10), ("094000", 100, 110, 100, 110, 10)])
    assert _detect_leader_pullback(bars, -3.0, 1.0, 0.0) is None


def test_pullback_blocks_below_floor():
    # 강세지만 VWAP보다 floor 아래로 깊이 눌림 → 차단
    bars = _bars([("093000", 100, 120, 100, 118, 10), ("094000", 118, 118, 101, 101, 10)])
    sig = _detect_leader_pullback(bars, -3.0, 1.0, 0.0)
    assert sig is None  # vwap≈109.5, last=101 → vwap_dist≈-7.8% < -3 floor


# ── 레짐 게이트: pullback은 상승장 전용 ────────────────────────────────────────

def _getter(overrides):
    base = {"momentum.enabled": True, "momentum.entry_mode": "pullback"}
    base.update(overrides)
    return lambda k, d=None: base.get(k, d)


def test_pullback_noop_when_not_up_regime(monkeypatch):
    monkeypatch.setattr(de, "_current_regime_label", lambda *a, **k: "risk_off")
    out = asyncio.run(run_momentum_entries("2026-09-24", getter=_getter({})))
    assert out["entered"] == 0 and "not_up_regime" in out.get("reason", "")


def test_pullback_runs_in_risk_on(monkeypatch):
    # risk_on이면 레짐 게이트 통과 → 이후 단계(exec_start/스캔)로 진행(무바이면 entered 0이나 not_up_regime 아님)
    monkeypatch.setattr(de, "_current_regime_label", lambda *a, **k: "risk_on")
    out = asyncio.run(run_momentum_entries("2026-09-24",
                                           getter=_getter({"momentum.exec_start": "153000"})))
    assert "not_up_regime" not in out.get("reason", "")


def test_disabled_noop():
    out = asyncio.run(run_momentum_entries("2026-09-24", getter=lambda k, d=None: (
        False if k == "momentum.enabled" else d)))
    assert out == {"enabled": False, "scanned": 0, "entered": 0}
