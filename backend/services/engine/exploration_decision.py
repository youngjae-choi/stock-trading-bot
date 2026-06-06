"""탐색모드 OR 매수 결정 헬퍼 — _on_tick 이 호출하는 순수 평가 함수.

BarEngine.compute_signal_state(symbol) 로 라이브 state 를 만들고, 일봉 TSI(외부 주입)를
state["tsi"] 에 채운 뒤 buy_condition_framework.evaluate_groups_or 로 그룹들 OR 을 평가한다.

가드(보유/중복/쿨다운)는 호출부(_on_tick) 책임 — 이 함수는 순수 평가만 한다.
"""

from __future__ import annotations

import logging
from typing import Any

from .buy_condition_framework import evaluate_groups_or

logger = logging.getLogger("ExplorationDecision")


def evaluate_exploration_buy(
    *,
    symbol: str,
    bar_engine: Any,
    groups: list[dict[str, Any]],
    conditions: dict[str, dict[str, Any]],
    tsi: float | None,
) -> dict[str, Any]:
    """탐색 OR 매수 평가 결과를 반환한다.

    Args:
        symbol: 평가 대상 종목 코드.
        bar_engine: compute_signal_state(symbol) 를 제공하는 BarEngine(또는 호환 객체).
        groups: load_groups() 결과(활성 그룹).
        conditions: load_conditions() 결과({id: condition}).
        tsi: 일봉 TSI(외부 주입). None 이면 state 의 None 유지(결손은 차단 금지).

    Returns:
        {"any": bool, "fired": [group_names], "condition_states": state_snapshot}.
    """
    state = bar_engine.compute_signal_state(symbol)
    if tsi is not None:
        state["tsi"] = tsi
    result = evaluate_groups_or(groups, conditions, state)
    return {
        "any": bool(result.get("any")),
        "fired": list(result.get("fired") or []),
        "condition_states": state,
    }
