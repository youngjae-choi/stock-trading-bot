"""매수 엔진 (엔진④) — 진입 게이트 전략의 도메인 권위.

레짐별 플레이북(전략설정 엔진①)에서 **매수 게이트 파라미터**를 읽어 제공한다.
진입 판단 로직(decision_engine._entry_gate_block_reason)이 흩어져 get_setting을
직접 읽던 것을, 이 엔진 하나에서 꺼내 쓰게 통일한다(설정 4중구조 단일화).

결정론(AI 0). 값은 get_playbook과 동일 — 무손실.
"""
from __future__ import annotations

from typing import Callable

from ..settings_store import get_setting
from .strategy_playbook import get_playbook


def resolve_buy_gates(regime5: str = "flat", getter: Callable = get_setting) -> dict:
    """이 레짐의 매수 게이트 파라미터 한 벌. decision_engine이 여기서 읽는다.

    반환: {vwap_pullback_mode, entry_max_vwap_dist_pct, max_price_change_pct,
           min_price_change_pct, min_volume_ratio, confidence_gate_mode,
           min_ai_confidence, intraday_max_stoploss, leverage_restriction}
    """
    return get_playbook(regime5, getter=getter).gates


# 매수 엔진이 관리하는 설정 키(Settings 화면 ④ 그룹 · SSOT 일치)
GATE_SETTING_KEYS = [
    "engine.entry_vwap_pullback_mode", "engine.entry_max_vwap_dist_pct",
    "engine.max_price_change_pct", "engine.min_price_change_pct",
    "engine.min_volume_ratio", "engine.confidence_gate_mode",
    "engine.min_ai_confidence", "engine.intraday_max_stoploss_per_symbol",
    "engine.leverage_restriction_mode",
]
