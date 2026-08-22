"""탐색모드(OR 폭증·풀예수금) 안전 게이트 + 사이징 파라미터 선택.

🔒 탐색모드는 KIS 모의(openapivts)일 때만 허용한다. 실계좌면 설정이 켜져 있어도 하드 차단해
실수로 80패가 실손실이 되는 것을 막는다(설계서 "안전장치" 모의 전용 게이트).

순수 헬퍼 — KIS/WS/DB 부작용 없음. get_setting/_is_virtual 을 패치해 단위테스트한다.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("ExplorationGate")


def is_exploration_allowed() -> bool:
    """탐색모드 제거(2026-08-22, PM 결정) — 항상 False.

    과거: engine.exploration_mode + 모의계좌면 OR폭증·풀예수금 매매(데이터 축적용). 탐색 졸업으로
    완전 제거한다. 이제 매수는 baseline S4/S5 경로만, 사이징은 예수금비중 신모델(sizing.model_active)
    이 담당한다. 호출부(order_executor·decision_engine·momentum_scanner)는 모두 else/early-return
    분기를 타 baseline 동작만 남는다.
    """
    return False


def select_sizing_params(final_rule: dict[str, Any]) -> tuple[None, int]:
    """사이징 파라미터 (budget_rate, max_positions) 를 반환한다.

    항상 (None, 기존 final_rule.max_positions) 를 반환한다. budget_rate=None 은
    "탐색 아님 → 호출부가 기존 daily_capital.get_active_budget_rate 를 쓰라"는 신호다.

    NOTE: 유일한 호출부(order_executor)가 `if is_exploration_allowed(): ... else:`의
    else 분기에서만 이 함수를 호출하므로, 탐색 허용 분기는 도달 불가(dead)다.
    따라서 풀예수금 파라미터 분기를 제거하고 비탐색 경로만 유지한다.

    Args:
        final_rule: rule_cache.get_rule(symbol) 결과(기존 max_positions 소스).
    """
    try:
        existing_max = int(float(final_rule.get("max_positions") or 7))
    except (TypeError, ValueError):
        existing_max = 7
    return None, existing_max
