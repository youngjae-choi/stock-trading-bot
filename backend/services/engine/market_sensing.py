"""시장감지 엔진 — 결정론 5장세 판정 + 전환(방향) 감지 (엔진②, inc1).

레짐을 **레벨(5장세)** 과 **방향(전환)** 두 축으로 결정론 판단한다(AI 개입 0).
- `classify_regime_5tier`: KOSPI(+VIX·선행지표lean)로 폭락/하락/보합/상승/폭등 판정.
- `detect_transition`: 최근 KOSPI 시계열의 **기울기**로 하락전환/상승전환 감지.
  8/18(+2.77%꼭지→+1.25%)처럼 레벨은 아직 +여도 방향이 꺾이면 잡는다.

**모든 임계가 설정** (결정5·A-7#5 하드코딩 해소) — 관리자가 코드 없이 조절.
inc1: 순수함수+TDD. 배선(shadow→활성)은 다음 inc. 기존 `_judge_regime`은 유지(병행).
"""
from __future__ import annotations

from typing import Callable, Sequence

from ..settings_store import get_setting

# 5장세 레벨 임계(설정키, 기본값) — KOSPI 등락률(%) 기준
# crash는 기존 폭락 방어선(risk.flash_crash_threshold_pct)을 재사용(중복 방지)
_LEVEL = {
    "crash": ("risk.flash_crash_threshold_pct", -2.0),  # 폭락(폭락방어선과 단일출처)
    "down": ("regime.down_pct", -1.5),        # 하락
    "up": ("regime.up_pct", 0.5),             # 상승
    "surge": ("regime.surge_pct", 2.5),       # 폭등
    "vix_volatile": ("regime.vix_volatile", 28.0),
}
# 전환(방향) 임계 — 최근 window(분) 동안의 KOSPI 변화(%p)
_TRANSITION = {
    "down_pp": ("regime.down_transition_pp", -1.0),   # 하락전환: -1.0%p↓
    "up_pp": ("regime.up_transition_pp", 1.0),        # 상승전환: +1.0%p↑
}
# 5장세 → 기존 레짐 SET 매핑(하위호환: 플레이북/SET은 아직 4종)
_SET_MAP = {
    "crash": "risk_off", "down": "risk_off", "flat": "neutral",
    "up": "risk_on", "surge": "risk_on", "volatile": "volatile",
}


def _f(getter: Callable, key: str, default: float) -> float:
    try:
        return float(getter(key, default))
    except (TypeError, ValueError):
        return float(default)


def classify_regime_5tier(
    kospi_change: float | None, vix: float | None = None,
    li_lean: float = 0.0, getter: Callable = get_setting,
) -> str:
    """KOSPI 등락률(+VIX·선행지표lean)로 5장세 판정: crash/down/flat/up/surge(+volatile).

    li_lean: 간밤 선행지표 방향(음수=약세). 당일 상수 바이어스로 반영(결정5).
    """
    crash = _f(getter, *_LEVEL["crash"])
    down = _f(getter, *_LEVEL["down"])
    up = _f(getter, *_LEVEL["up"])
    surge = _f(getter, *_LEVEL["surge"])
    vixv = _f(getter, *_LEVEL["vix_volatile"])
    if vix is not None and vix > vixv:
        return "volatile"
    k = (kospi_change if kospi_change is not None else 0.0)
    # 선행지표 lean을 소폭 바이어스(설정 weight, 기본 0.25%p/lean단위)
    k += li_lean * _f(getter, "regime.li_lean_weight", 0.25)
    if k <= crash:
        return "crash"
    if k <= down:
        return "down"
    if k >= surge:
        return "surge"
    if k >= up:
        return "up"
    return "flat"


def detect_transition(
    series: Sequence[float], getter: Callable = get_setting,
) -> str | None:
    """최근 KOSPI 등락률 시계열(window 내, 시간순)의 기울기로 전환 감지.

    series[0]=window 시작, series[-1]=현재. 변화량으로 방향 판정.
    반환: 'down_transition' / 'up_transition' / None. (레벨 무관 — 방향만)
    """
    vals = [v for v in series if v is not None]
    if len(vals) < 2:
        return None
    delta = vals[-1] - vals[0]
    down_pp = _f(getter, *_TRANSITION["down_pp"])
    up_pp = _f(getter, *_TRANSITION["up_pp"])
    if delta <= down_pp:
        return "down_transition"
    if delta >= up_pp:
        return "up_transition"
    return None


def regime_to_set(regime5: str) -> str:
    """5장세 라벨 → 기존 레짐 SET 라벨(하위호환)."""
    return _SET_MAP.get(regime5, "neutral")
