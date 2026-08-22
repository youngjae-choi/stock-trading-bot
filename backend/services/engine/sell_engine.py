"""매도 엔진 (엔진⑤) — 청산 전략(손절·익절·트레일·수확)의 도메인 권위.

레짐별 플레이북에서 **매도 파라미터**를 읽어 제공한다. position_manager가 흩어진
레짐SET/설정을 직접 읽던 것을 이 엔진에서 꺼내 쓰게 통일. 값 동일 — 무손실.

하락전환 트레일 조임(엔진② 대응)은 position_manager._update_trailing이 담당(별도).
"""
from __future__ import annotations

from typing import Callable

from ..settings_store import get_setting
from .strategy_playbook import get_playbook


def resolve_sell_params(regime5: str = "flat", regime_set: dict | None = None,
                        getter: Callable = get_setting) -> dict:
    """이 레짐의 매도 파라미터 한 벌.

    반환: {stop_loss_rate, take_profit_rate, trailing_activate_profit,
           trailing_stop_rate, harvest_mode, scaleout_ratio, scaleout_target_rate}
    stop/tp/trail은 레짐SET(regime_set)에서, 수확은 설정에서.
    """
    return get_playbook(regime5, regime_set=regime_set, getter=getter).sell


# 매도 엔진이 관리하는 설정 키(Settings 화면 ⑤ 그룹) — stop/tp/trail은 레짐SET에서 관리
SELL_SETTING_KEYS = [
    "engine.harvest_mode", "engine.scaleout_ratio", "engine.scaleout_target_rate",
    "engine.scaleout_ratio_after_target", "engine.daily_target_rate",
    "engine.stop_source",  # 손절/트레일 출처(profile|regime) — Phase3 통합 스위치
]
