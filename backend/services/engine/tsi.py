"""True Strength Index (TSI) 계산 — 이중 평활 모멘텀 추세 지표.

TSI = 100 * EMA(EMA(Δclose, r), s) / EMA(EMA(|Δclose|, r), s)
v1: 일봉 종가, 표준 r=25, s=13. 상승추세>0 / 하락추세<0.
"""
from __future__ import annotations


def _ema(values: list[float], period: int) -> list[float]:
    """단순 EMA 시계열. 첫 값은 시드(첫 원소)로 시작."""
    if not values:
        return []
    k = 2.0 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(out[-1] + k * (v - out[-1]))
    return out


def compute_tsi(closes: list[float], r: int = 25, s: int = 13) -> float | None:
    """종가 리스트(오래된→최신)로 최신 TSI 값을 반환. 데이터 부족 시 None."""
    if not closes or len(closes) < r + s + 1:
        return None
    mtm = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    abs_mtm = [abs(x) for x in mtm]
    double_mtm = _ema(_ema(mtm, r), s)
    double_abs = _ema(_ema(abs_mtm, r), s)
    denom = double_abs[-1]
    if denom == 0:
        return 0.0
    return max(-100.0, min(100.0, 100.0 * double_mtm[-1] / denom))


def tsi_for_closes(closes: list[float]) -> float | None:
    """closes 시계열로 TSI 계산(round 2). 예외/부족 시 None."""
    try:
        v = compute_tsi([float(c) for c in closes if c is not None])
        return round(v, 2) if v is not None else None
    except Exception:
        return None
