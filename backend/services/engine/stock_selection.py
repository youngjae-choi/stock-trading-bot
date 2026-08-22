"""종목선정 엔진 — 단타 모멘텀 선정 점수 (엔진③, inc1).

현재 `universe_filter._score_and_rank`에 박힌 선정 점수(등락률 + 거래량급증)를
**설정 기반 단일 함수**로 정리한다. 가중치를 설정화해 나중에 레짐별 선정
(예: 하락장=상대강도 중시)으로 확장할 토대. 결정론(AI 0).

inc1: 순수함수 + TDD, 기존 로직과 동일(가중치만 설정). 배선(universe_filter가
이걸 호출)은 다음 inc — shadow 비교 후. 현재는 동작 불변.
"""
from __future__ import annotations

from typing import Callable

from ..settings_store import get_setting

# 거래량급증(전일대비 거래량증가율%) 포화 분모 — 300%(전일 3배)에서 점수 1.0.
_VOLUME_SURGE_SATURATION_PCT = 300.0


def _f(getter: Callable, key: str, default: float) -> float:
    try:
        return float(getter(key, default))
    except (TypeError, ValueError):
        return float(default)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def selection_score(
    change_rate: float = 0.0,
    change_rank: int | None = None,
    volume_surge: float = 0.0,
    volume_rank: int | None = None,
    total: int = 1,
    getter: Callable = get_setting,
) -> float:
    """단타 모멘텀 선정 점수 = 등락률점수×change_w + 거래량급증점수×surge_w.

    - change_score: 등락률 순위 있으면 순위점수((total-rank+1)/total), 없으면 등락률 정규화.
    - surge_score: 거래량급증% 정규화(min(1, surge/300)), 0/부재면 거래량 순위점수 폴백.
    - 가중치(change_w·surge_w)는 설정 — 레짐별 선정 확장 토대(결정3 플레이북).
    """
    total = total or 1
    change_w = _f(getter, "selection.change_weight", 0.5)
    surge_w = _f(getter, "selection.surge_weight", 0.5)

    if change_rank is not None and change_rank <= total:
        change_score = (total - change_rank + 1) / total
    else:
        change_score = (change_rate + 30.0) / 60.0
    change_score = _clamp01(change_score)

    surge = float(volume_surge or 0.0)
    if surge > 0.0:
        surge_score = min(1.0, surge / _VOLUME_SURGE_SATURATION_PCT)
    elif volume_rank is not None and volume_rank <= total:
        surge_score = (total - volume_rank + 1) / total
    else:
        surge_score = 0.0
    surge_score = _clamp01(surge_score)

    return round(change_w * change_score + surge_w * surge_score, 4)
