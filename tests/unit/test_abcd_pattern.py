"""ABCD 눌림목 패턴 검출기(순수) 테스트 — A→B→C 구조 판정.

detect_abcd_entry: A(임펄스 스윙고점)→B(눌림저점)→C(higher-low 지지 후 반등) 성립 시 (stop,target).
scripts/abcd_backtest.py와 동일 로직. DB·매매 무관(순수).
"""
from __future__ import annotations

from backend.services.engine.abcd_pattern import detect_abcd_entry

_CFG = {"lookback": 30, "impulse": 2.0, "pull_min": 1.0, "pull_max": 5.0}


def _bar(m, o, h, l, c, v=100):
    return {"m": m, "o": o, "h": h, "l": l, "c": c, "v": v}


def _abcd_bars():
    """정상 ABCD: base(100)→A(105, +5% 임펄스)→B(102.5, 눌림 2.4%)→C(103.5 반등)."""
    bars = []
    for k in range(5):                       # 0~4 base ~100
        bars.append(_bar(f"10{k:02d}", 100, 100.3, 99.8, 100))
    for k, c in enumerate([101.5, 103, 104, 105], start=5):   # 5~8 상승 → A=105
        bars.append(_bar(f"10{k:02d}", c - 0.5, c + 0.2, c - 0.6, c))
    for k, c in enumerate([104, 103.2, 102.8, 102.6], start=9):  # 9~12 눌림 → B~102.5
        bars.append(_bar(f"10{k:02d}", c + 0.3, c + 0.4, c - 0.1, c))
    # 13: C 반등(양봉, 저가≥B, 종가 B<c<A)
    bars.append(_bar("1013", 102.8, 103.6, 102.6, 103.5))
    return bars


def test_detects_valid_abcd():
    bars = _abcd_bars()
    sig = detect_abcd_entry(bars, len(bars) - 1, _CFG)
    assert sig is not None
    stop, target = sig
    assert 105.0 < target < 105.5            # A(전고점 고가 ≈105.2) = 목표
    assert 102.0 < stop < 102.6              # B 지지선 바로 아래 = 손절
    # 진입(103.5)은 손절 위·목표 아래 = 여력 존재
    assert stop < bars[-1]["c"] < target


def test_no_signal_without_impulse():
    """1차 상승(임펄스)이 없으면(밋밋) ABCD 아님."""
    bars = [_bar(f"10{k:02d}", 100, 100.2, 99.9, 100) for k in range(15)]
    assert detect_abcd_entry(bars, len(bars) - 1, _CFG) is None


def test_no_signal_when_support_broken():
    """현재 저가가 B 저점을 깨면(지지 실패) 진입 아님."""
    bars = _abcd_bars()
    bars[-1] = _bar("1013", 102.8, 103.0, 101.0, 102.9)  # 저가 101 < B(102.5) → 지지 붕괴
    assert detect_abcd_entry(bars, len(bars) - 1, _CFG) is None


def test_no_signal_when_no_rebound():
    """반등(양봉/직전종가 상향) 없으면(음봉·하락) 진입 아님."""
    bars = _abcd_bars()
    prev_c = bars[-2]["c"]
    bars[-1] = _bar("1013", 103.4, 103.5, 102.6, prev_c - 0.3)  # 음봉·직전보다 하락
    assert detect_abcd_entry(bars, len(bars) - 1, _CFG) is None


def test_no_signal_outside_time_window():
    """진입 시간창(09:35~13:30) 밖이면 신호 없음."""
    bars = _abcd_bars()
    bars[-1] = {**bars[-1], "m": "1400"}     # 14:00 = 창 밖
    assert detect_abcd_entry(bars, len(bars) - 1, _CFG) is None


def test_pullback_too_deep_rejected():
    """눌림이 pull_max(5%)보다 깊으면 ABCD 아님(급락=다른 상황)."""
    bars = _abcd_bars()
    # B를 아주 깊게(97 → 눌림 ~7.6%)
    bars[11] = _bar("1011", 97.5, 97.8, 97.0, 97.4)
    bars[-1] = _bar("1013", 97.6, 99.0, 97.2, 98.5)  # 반등하지만 눌림 과다
    assert detect_abcd_entry(bars, len(bars) - 1, _CFG) is None
