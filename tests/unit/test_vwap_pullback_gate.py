"""눌림목 게이트(_vwap_pullback_gate) — VWAP 위 이격 진입(추격) 차단.

데이터 확증 엣지(2026-08-14 백테스트): VWAP 아래 진입 승률 51→61%·흑자,
꼭지추격(VWAP 위) 39%. 진입가가 VWAP보다 임계% 넘게 위면 차단대상.
"""

from __future__ import annotations

from backend.services.engine.decision_engine import _vwap_pullback_gate


def test_blocks_above_vwap():
    # 가격 10100, VWAP 10000 → +1.0% 위, 임계 0 → 차단(vwap_dist 반환)
    assert _vwap_pullback_gate(10000.0, 10100.0, 0.0) == 1.0


def test_passes_below_vwap():
    # 가격 9900, VWAP 10000 → -1.0% (눌림) → 통과(None)
    assert _vwap_pullback_gate(10000.0, 9900.0, 0.0) is None


def test_passes_at_vwap():
    assert _vwap_pullback_gate(10000.0, 10000.0, 0.0) is None  # 정확히 VWAP = 통과


def test_threshold_tolerance():
    # 임계 +0.5% 허용: +0.3%는 통과, +0.8%는 차단
    assert _vwap_pullback_gate(10000.0, 10030.0, 0.5) is None
    assert _vwap_pullback_gate(10000.0, 10080.0, 0.5) == 0.8


def test_fail_open_when_no_vwap():
    assert _vwap_pullback_gate(None, 10000.0, 0.0) is None   # VWAP 없음 → 통과
    assert _vwap_pullback_gate(0.0, 10000.0, 0.0) is None
    assert _vwap_pullback_gate(10000.0, None, 0.0) is None   # 가격 없음 → 통과
    assert _vwap_pullback_gate(10000.0, 0.0, 0.0) is None
