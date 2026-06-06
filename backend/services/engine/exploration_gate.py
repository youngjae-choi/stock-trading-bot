"""탐색모드(OR 폭증·풀예수금) 안전 게이트 + 사이징 파라미터 선택.

🔒 탐색모드는 KIS 모의(openapivts)일 때만 허용한다. 실계좌면 설정이 켜져 있어도 하드 차단해
실수로 80패가 실손실이 되는 것을 막는다(설계서 "안전장치" 모의 전용 게이트).

순수 헬퍼 — KIS/WS/DB 부작용 없음. get_setting/_is_virtual 을 패치해 단위테스트한다.
"""

from __future__ import annotations

import logging
from typing import Any

from ..settings_store import get_setting

logger = logging.getLogger("ExplorationGate")

# 탐색모드 사이징 기본값(설계서 §자본·포지션: max_positions↑·예산률↑)
_DEFAULT_MAX_POSITIONS = 40
_DEFAULT_BUDGET_RATE = 0.95


def _is_virtual() -> bool:
    """KIS 클라이언트가 모의투자(openapivts) 환경인지 반환한다.

    별도 함수로 분리해 단위테스트에서 패치 가능하게 한다.
    """
    from ..kis.common.client import kis_client

    return kis_client._is_virtual_trading()


def _coerce_bool(value: Any) -> bool:
    """system_settings 값(bool/str/int)을 불리언으로 강제한다."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def is_exploration_allowed() -> bool:
    """탐색모드 허용 여부 = engine.exploration_mode 켜짐 AND KIS 모의계좌.

    실계좌면 무조건 False(하드 차단).
    """
    if not _is_virtual():
        return False
    return _coerce_bool(get_setting("engine.exploration_mode", False))


def select_sizing_params(final_rule: dict[str, Any]) -> tuple[float | None, int]:
    """사이징 파라미터 (budget_rate, max_positions) 를 반환한다.

    탐색 허용 시 풀예수금 파라미터(exploration.budget_rate / exploration.max_positions),
    아니면 (None, 기존 final_rule.max_positions) 를 반환한다. budget_rate=None 은
    "탐색 아님 → 호출부가 기존 daily_capital.get_active_budget_rate 를 쓰라"는 신호다.

    Args:
        final_rule: rule_cache.get_rule(symbol) 결과(기존 max_positions 소스).
    """
    if is_exploration_allowed():
        budget_rate = float(get_setting("exploration.budget_rate", _DEFAULT_BUDGET_RATE) or _DEFAULT_BUDGET_RATE)
        max_positions = int(get_setting("exploration.max_positions", _DEFAULT_MAX_POSITIONS) or _DEFAULT_MAX_POSITIONS)
        logger.info(
            "INFO: [탐색] 풀예수금 사이징 적용 budget_rate=%.2f max_positions=%d", budget_rate, max_positions
        )
        return budget_rate, max_positions
    try:
        existing_max = int(float(final_rule.get("max_positions") or 7))
    except (TypeError, ValueError):
        existing_max = 7
    return None, existing_max
