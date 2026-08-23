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


# get_playbook.gates 키 → final_rule(RulePack) 키 매핑 (이름 상이 주의: min_volume_ratio↔volume_ratio_min)
_GATE_TO_RULE = {
    "min_price_change_pct": "min_price_change_pct",
    "max_price_change_pct": "max_price_change_pct",
    "min_ai_confidence": "min_ai_confidence",
    "min_volume_ratio": "volume_ratio_min",
}


def reconcile_buy_gates(final_rule: dict, regime5: str = "flat",
                        getter: Callable = get_setting) -> tuple[dict, list[tuple]]:
    """④ 매수 게이트 단일화(get_playbook 통합) — settings 권위 vs RulePack 대조.

    decision_rules가 final_rule(RulePack)에서 밴드·확신도를 읽는데, RulePack이 settings와
    다를 수 있다(4중구조 발산). 이 함수가 **권위(get_playbook.gates=settings)와 대조**해
    발산을 드러내고(shadow), 스위치로 단일화한다.

    반환 (effective_rule, divergences):
      - divergences: [(rule_key, rulepack_val, playbook_val), ...] — SHADOW 로그용.
      - `engine.buy_gates_source`=playbook 이면 effective_rule의 게이트키를 playbook(settings)값으로
        덮어 단일출처화. legacy(기본)면 final_rule 그대로(현행=RulePack 우선). 롤백스위치.
    """
    gates = get_playbook(regime5, getter=getter).gates
    divergences: list[tuple] = []
    for gk, rk in _GATE_TO_RULE.items():
        pv = gates.get(gk)
        rv = final_rule.get(rk)
        if rv is None or pv is None:
            continue
        try:
            diff = abs(float(rv) - float(pv)) > 1e-9
        except (TypeError, ValueError):
            diff = rv != pv
        if diff:
            divergences.append((rk, rv, pv))
    source = str(getter("engine.buy_gates_source", "legacy") or "legacy").lower()
    if source == "playbook":
        eff = dict(final_rule)
        for gk, rk in _GATE_TO_RULE.items():
            if gates.get(gk) is not None:
                eff[rk] = gates[gk]
        return eff, divergences
    return final_rule, divergences


# 매수 엔진이 관리하는 설정 키(Settings 화면 ④ 그룹 · SSOT 일치)
GATE_SETTING_KEYS = [
    "engine.entry_vwap_pullback_mode", "engine.entry_max_vwap_dist_pct",
    "engine.max_price_change_pct", "engine.min_price_change_pct",
    "engine.min_volume_ratio", "engine.confidence_gate_mode",
    "engine.min_ai_confidence", "engine.intraday_max_stoploss_per_symbol",
    "engine.leverage_restriction_mode",
]
