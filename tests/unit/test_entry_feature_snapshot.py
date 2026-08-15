"""진입 미시구조 피처 계측(_entry_feature_snapshot) — 엣지 발굴 데이터 수집.

체결강도·VWAP거리·일중고가거리·틱볼륨을 진입 시점에 bar_engine에서 스냅샷해
trade_entry_tags에 저장 → EOD outcome과 조인해 '무엇이 승패를 가르나' 발굴.
"""

from __future__ import annotations

import backend.services.engine.decision_engine as de


class _FakeBar:
    def __init__(self, vwap=None, high=0.0, gangdo=0.0, tickvol=0.0):
        self._vwap, self._high, self._gangdo, self._tickvol = vwap, high, gangdo, tickvol

    def get_vwap(self, _s):
        return self._vwap

    def get_day_high(self, _s):
        return self._high

    def get_chegyeol_gangdo(self, _s):
        return self._gangdo

    def get_tick_vol_mult(self, _s):
        return self._tickvol


class _Stub:
    """_entry_feature_snapshot만 격리 실행하기 위한 경량 스텁."""
    _entry_feature_snapshot = de.DecisionEngine._entry_feature_snapshot

    def __init__(self, bar):
        self._bar_engine = bar


def test_snapshot_computes_distances_and_pressure():
    stub = _Stub(_FakeBar(vwap=10000.0, high=11000.0, gangdo=0.62, tickvol=3.5))
    feat = stub._entry_feature_snapshot(
        "005930",
        {"price": 10500.0, "change_rate": 3.2, "volume_ratio": 5.0, "confidence": 0.41},
    )
    assert feat["chegyeol_gangdo"] == 0.62
    assert feat["vwap_dist_pct"] == 5.0        # (10500/10000-1)*100, VWAP 위
    assert feat["high_dist_pct"] == -4.55      # (10500/11000-1)*100, 일중고가 아래(되돌림)
    assert feat["tick_vol_mult"] == 3.5
    assert feat["change_rate"] == 3.2
    assert feat["confidence"] == 0.41
    assert ":" in feat["entry_hm"]


def test_snapshot_null_safe_when_no_bar_data():
    stub = _Stub(_FakeBar(vwap=None, high=0.0, gangdo=0.0, tickvol=0.0))
    feat = stub._entry_feature_snapshot("005930", {"price": 10500.0})
    assert feat["vwap_dist_pct"] is None       # VWAP 없음
    assert feat["high_dist_pct"] is None        # day_high 0 → None
    assert feat["chegyeol_gangdo"] == 0.0
    # 예외 없이 dict 반환(계측 실패가 매매를 막지 않음)
    assert isinstance(feat, dict)


def test_snapshot_never_raises():
    stub = _Stub(_FakeBar())
    assert stub._entry_feature_snapshot("", {}) is not None  # 빈 입력도 안전
