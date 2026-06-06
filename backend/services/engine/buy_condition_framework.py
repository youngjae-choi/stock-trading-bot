"""설정 가능한 매수 조건 프레임워크 — 원자 조건 → AND 그룹 → 그룹들 OR.

평가기는 정규화된 state dict(체결강도·VWAP·10초봉 등)에 대해 동작한다.
state 값 채움은 Phase 1b, 매수경로 통합은 후속. 본 모듈은 순수 로직 + DB 정의.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from ..db import get_connection

logger = logging.getLogger("BuyConditionFramework")


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def evaluate_condition(condition: dict[str, Any], state: dict[str, Any]) -> bool:
    """원자 조건 1개를 state에 대해 평가. 알 수 없는 ctype은 False."""
    ctype = str(condition.get("ctype") or "")
    p = condition.get("params") or {}
    if ctype == "change_rate_band":
        cr = _f(state.get("change_rate"))
        return _f(p.get("min")) <= cr <= _f(p.get("max"), 999.0)
    if ctype == "chegyeol_gangdo_min":
        return _f(state.get("체결강도")) >= _f(p.get("min"))
    if ctype == "tick_volume_mult_min":
        return _f(state.get("tick_vol_mult")) >= _f(p.get("min"))
    if ctype == "tsi_positive":
        tsi = state.get("tsi")
        return True if tsi is None else _f(tsi) > 0  # 결손은 통과(차단 금지)
    if ctype == "vwap_above":
        return str(state.get("vwap_position")) == "above"
    if ctype == "day_high_breakout":
        return bool(state.get("day_high_breakout"))
    if ctype == "pullback_rebound":
        return bool(state.get("pullback_rebound"))
    if ctype == "momentum_rising_bars":
        return int(_f(state.get("rising_bars"))) >= int(_f(p.get("min_bars"), 1))
    if ctype == "time_window":
        t = str(state.get("time_hhmm") or "")
        return str(p.get("start") or "00:00") <= t <= str(p.get("end") or "23:59")
    return False
