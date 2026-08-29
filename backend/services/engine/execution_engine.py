"""매매 엔진 (엔진⑥) — 사이징·주문 실행 전략의 도메인 권위.

레짐별 플레이북 + 확신도로 **예수금비중 사이징**을 산출. order_executor가 이 엔진에서
사이징을 꺼내 쓴다(사이징은 이미 strategy_playbook 모델; 이 엔진이 진입점 통일).
결정론(AI 0). 값 동일 — 무손실.
"""
from __future__ import annotations

from typing import Callable

from ..settings_store import get_setting
from .strategy_playbook import (
    SizingResult,
    get_playbook,
    resolve_conviction,
    resolve_position_sizing,
)


def resolve_execution_sizing(
    deposit: float, regime5: str = "flat", vwap_dist_pct: float | None = None,
    getter: Callable = get_setting,
) -> SizingResult:
    """매매 실행용 사이징 — 레짐×눌림 확신도 → 예수금비중, 폭등 티어 상한 반영.

    deposit: 사이징 기준액(총자산 등). regime5: 5장세. vwap_dist_pct: 진입 눌림.
    """
    pb = get_playbook(regime5, getter=getter)
    conviction = resolve_conviction(pb.set_label, vwap_dist_pct, getter=getter)
    per_rate_max = pb.sizing.get("per_position_rate_max")
    return resolve_position_sizing(deposit, conviction, getter=getter, per_rate_max=per_rate_max)


# 매매 엔진이 관리하는 설정 키(Settings 화면 ⑥ 그룹)
EXEC_SETTING_KEYS = [
    # 2026-08-29 PM: 종목수 결정 폐지 → 종목당 금액 통제. positions_min/max·per_position_rate_min은
    # 死(무결성 백스톱)라 설정화면에서 제외.
    "sizing.model_active",
    "sizing.per_position_min_krw", "sizing.per_position_max_krw",
    "exploration.deploy_target_rate",
    "sizing.surge_per_position_rate_max", "risk.max_position_rate_per_stock",
]
