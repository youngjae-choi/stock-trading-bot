"""엔진④매수·⑤매도·⑥매매 — get_playbook에서 도메인 전략을 읽는 권위 검증.

값이 get_playbook과 동일(무손실). 소비자가 흩어진 소스 대신 이 엔진을 읽는다.
"""
from __future__ import annotations

from backend.services.engine.buy_engine import resolve_buy_gates
from backend.services.engine.execution_engine import resolve_execution_sizing
from backend.services.engine.sell_engine import resolve_sell_params
from backend.services.engine.strategy_playbook import get_playbook

_CFG = {
    "selection.change_weight": 0.5, "selection.surge_weight": 0.5,
    "engine.entry_vwap_pullback_mode": "enforce", "engine.max_price_change_pct": 4.0,
    "engine.min_price_change_pct": 1.5, "engine.min_volume_ratio": 1.5,
    "engine.harvest_mode": True, "engine.scaleout_ratio": 0.6,
    "engine.scaleout_target_rate": 0.01,
    "sizing.per_position_rate_min": 0.05, "risk.max_position_rate_per_stock": 0.15,
    "sizing.positions_min": 6, "sizing.positions_max": 19,
    "exploration.deploy_target_rate": 0.95, "sizing.surge_per_position_rate_max": 0.20,
    "conviction.regime_weight": 0.5, "conviction.pullback_full_dist_pct": -3.0,
}


def _g(k, d=None):
    return _CFG.get(k, d)


def test_buy_engine_matches_playbook_gates():
    # ④ 매수: 게이트 = get_playbook.gates (무손실)
    gates = resolve_buy_gates("up", getter=_g)
    assert gates == get_playbook("up", getter=_g).gates
    assert gates["vwap_pullback_mode"] == "enforce"
    assert gates["max_price_change_pct"] == 4.0


def test_sell_engine_matches_playbook_sell():
    # ⑤ 매도: 손절/익절은 레짐SET, 수확은 설정
    rset = {"stop_loss_rate": -0.035, "take_profit_rate": 0.08,
            "trailing_stop_rate": 0.02, "trailing_activate_profit": 0.04}
    sell = resolve_sell_params("up", regime_set=rset, getter=_g)
    assert sell == get_playbook("up", regime_set=rset, getter=_g).sell
    assert sell["stop_loss_rate"] == -0.035
    assert sell["harvest_mode"] is True


def test_exec_engine_sizing_high_conviction():
    # ⑥ 매매: risk_on(up)+깊은눌림 → 집중(15%×6)
    sz = resolve_execution_sizing(100_000_000, "up", vwap_dist_pct=-3.0, getter=_g)
    assert sz.per_position_rate == 0.15
    assert sz.target_positions == 6


def test_exec_engine_surge_expands():
    # 폭등 → per_rate_max가 surge 상한(0.20)
    sz = resolve_execution_sizing(100_000_000, "surge", vwap_dist_pct=-3.0, getter=_g)
    assert sz.per_position_rate == 0.20


def test_exec_engine_defensive_diversifies():
    # 하락(risk_off)+추격 → 분산(낮은 비중)
    sz = resolve_execution_sizing(100_000_000, "down", vwap_dist_pct=2.0, getter=_g)
    assert sz.per_position_rate <= 0.07
