"""탐색모드 OR 매수 결정 헬퍼 — _on_tick 이 호출하는 순수 평가 함수.

BarEngine.compute_signal_state(symbol) 로 라이브 state 를 만들고, 일봉 TSI(외부 주입)를
state["tsi"] 에 채운 뒤 buy_condition_framework.evaluate_groups_or 로 그룹들 OR 을 평가한다.

가드(보유/중복/쿨다운)는 호출부(_on_tick) 책임 — 이 함수는 순수 평가만 한다.
"""

from __future__ import annotations

import logging
from typing import Any

from ..settings_store import get_setting
from .buy_condition_framework import evaluate_groups_or

logger = logging.getLogger("ExplorationDecision")

_DEFAULT_WEIGHT_FLOOR = 0.2


def _weight_floor_setting() -> float:
    """exploration.weight_floor 설정 조회 — 실패/비정상 값은 기본 0.2 폴백(차단 금지)."""
    try:
        return float(get_setting("exploration.weight_floor", _DEFAULT_WEIGHT_FLOOR) or _DEFAULT_WEIGHT_FLOOR)
    except Exception as exc:
        logger.warning("WARN: [탐색] weight_floor 설정 조회 실패 → 기본 %.2f 사용 reason=%s", _DEFAULT_WEIGHT_FLOOR, exc)
        return _DEFAULT_WEIGHT_FLOOR


def evaluate_exploration_buy(
    *,
    symbol: str,
    bar_engine: Any,
    groups: list[dict[str, Any]],
    conditions: dict[str, dict[str, Any]],
    tsi: float | None,
    regime: str | None = None,
) -> dict[str, Any]:
    """탐색 OR 매수 평가 결과를 반환한다.

    Args:
        symbol: 평가 대상 종목 코드.
        bar_engine: compute_signal_state(symbol) 를 제공하는 BarEngine(또는 호환 객체).
        groups: load_groups() 결과(활성 그룹).
        conditions: load_conditions() 결과({id: condition}).
        tsi: 일봉 TSI(외부 주입). None 이면 state 의 None 유지(결손은 차단 금지).
        regime: 현재 레짐(예: risk_on/neutral/risk_off). None 이면 레짐 필터 미적용.

    Returns:
        {"any": bool, "fired": [group_names], "skipped": [{"name","reason"}],
         "condition_states": state_snapshot}.
    """
    state = bar_engine.compute_signal_state(symbol)
    if tsi is not None:
        state["tsi"] = tsi
    result = evaluate_groups_or(
        groups, conditions, state, regime=regime, weight_floor=_weight_floor_setting()
    )
    return {
        "any": bool(result.get("any")),
        "fired": list(result.get("fired") or []),
        "skipped": list(result.get("skipped") or []),
        "condition_states": state,
    }


def build_exploration_tag_payload(
    *,
    order_id: str,
    symbol: str,
    trade_date: str,
    candidate: dict[str, Any],
    decision: dict[str, Any],
    market_context: dict[str, Any],
) -> dict[str, Any]:
    """record_entry_tag 키워드 인자 dict 를 조립한다(태깅 페이로드).

    Args:
        order_id: 매수 주문 로컬 id(없으면 빈 문자열).
        symbol: 종목 코드.
        trade_date: YYYY-MM-DD 거래일.
        candidate: S4 후보 dict(선정사유 추출 원천).
        decision: evaluate_exploration_buy 결과({any, fired, condition_states}).
        market_context: {"regime","market_tone","time_bucket","vix"} dict.
    """
    from .trade_tagging import build_selection_reason

    return {
        "order_id": str(order_id or ""),
        "symbol": str(symbol or ""),
        "trade_date": str(trade_date or ""),
        "selection_reason": build_selection_reason(candidate or {}),
        "fired_groups": list(decision.get("fired") or []),
        "condition_states": dict(decision.get("condition_states") or {}),
        "market_context": dict(market_context or {}),
    }
