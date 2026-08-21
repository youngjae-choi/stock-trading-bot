"""전략설정 엔진 — 예수금비중 사이징 모델(결정4) 검증.

종목당 5~15% 비중, 종목수 6~19 파생. 확신↑ → 집중(비중↑·종목수↓).
"""
from __future__ import annotations

from backend.services.engine.strategy_playbook import (
    build_playbook,
    resolve_conviction,
    resolve_position_sizing,
)

# 테스트용 설정 getter — DB 없이 PM 확정값 주입
_CFG = {
    "sizing.per_position_rate_min": 0.05,
    "risk.max_position_rate_per_stock": 0.15,
    "sizing.positions_min": 6,
    "sizing.positions_max": 19,
    "exploration.deploy_target_rate": 0.95,
}


def _getter(key, default=None):
    return _CFG.get(key, default)


def test_high_conviction_concentrates_to_min_positions():
    # 확신 1.0 → 종목당 15% → 6종목 집중
    r = resolve_position_sizing(100_000_000, conviction=1.0, getter=_getter)
    assert r.per_position_rate == 0.15
    assert r.target_positions == 6          # int(0.95/0.15)=6
    assert r.per_position_krw == 15_000_000  # 1억 × 15%


def test_low_conviction_diversifies_to_max_positions():
    # 확신 0.0 → 종목당 5% → 19종목 분산
    r = resolve_position_sizing(100_000_000, conviction=0.0, getter=_getter)
    assert r.per_position_rate == 0.05
    assert r.target_positions == 19         # int(0.95/0.05)=19
    assert r.per_position_krw == 5_000_000


def test_mid_conviction_interpolates():
    r = resolve_position_sizing(100_000_000, conviction=0.5, getter=_getter)
    assert r.per_position_rate == 0.10       # 5% + (15-5)*0.5
    assert 6 <= r.target_positions <= 19
    assert r.target_positions == 9           # int(0.95/0.10)=9


def test_count_stays_within_bounds():
    for c in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
        r = resolve_position_sizing(100_000_000, conviction=c, getter=_getter)
        assert 6 <= r.target_positions <= 19
        assert 0.05 <= r.per_position_rate <= 0.15
        # 총배포가 상한 이내
        assert r.per_position_rate * r.target_positions <= r.deploy_target_rate + 1e-9


def test_conviction_clamped():
    hi = resolve_position_sizing(1_000_000, conviction=5.0, getter=_getter)
    lo = resolve_position_sizing(1_000_000, conviction=-3.0, getter=_getter)
    assert hi.per_position_rate == 0.15
    assert lo.per_position_rate == 0.05


def test_zero_deposit_safe():
    r = resolve_position_sizing(0, conviction=1.0, getter=_getter)
    assert r.per_position_krw == 0.0
    assert r.target_positions == 6


_CONV = {
    "conviction.regime_weight": 0.5,
    "conviction.pullback_full_dist_pct": -3.0,
    "conviction.regime_scores": {"risk_on": 1.0, "neutral": 0.5, "risk_off": 0.2},
}


def _cgetter(key, default=None):
    return _CONV.get(key, default)


def test_conviction_best_case_uptrend_deep_pullback():
    # risk_on(1.0) + 깊은 눌림(-3%→1.0) → 0.5*1 + 0.5*1 = 1.0 (최고 집중)
    assert resolve_conviction("risk_on", -3.0, getter=_cgetter) == 1.0


def test_conviction_worst_case_defensive_chase():
    # risk_off(0.2) + VWAP위 추격(0.0) → 0.5*0.2 + 0.5*0 = 0.1 (분산)
    assert abs(resolve_conviction("risk_off", 1.5, getter=_cgetter) - 0.1) < 1e-9


def test_conviction_regime_weight_shifts_emphasis():
    # regime_weight=1.0 → 눌림 무시, 레짐만. risk_on이면 눌림 없어도 1.0
    cfg = dict(_CONV, **{"conviction.regime_weight": 1.0})
    assert resolve_conviction("risk_on", 5.0, getter=lambda k, d=None: cfg.get(k, d)) == 1.0
    # regime_weight=0.0 → 레짐 무시, 눌림만. 깊은 눌림이면 risk_off여도 1.0
    cfg0 = dict(_CONV, **{"conviction.regime_weight": 0.0})
    assert resolve_conviction("risk_off", -3.0, getter=lambda k, d=None: cfg0.get(k, d)) == 1.0


def test_conviction_unknown_vwap_neutral():
    # 눌림 미상 → 0.5. risk_on(1.0): 0.5*1 + 0.5*0.5 = 0.75
    assert resolve_conviction("risk_on", None, getter=_cgetter) == 0.75


def test_conviction_feeds_sizing_end_to_end():
    # 결합: 최고 확신 → 15%×6, 최저 확신 → 5%×19 근처
    hi = resolve_conviction("risk_on", -3.0, getter=_cgetter)
    lo = resolve_conviction("risk_off", 2.0, getter=_cgetter)
    assert resolve_position_sizing(100_000_000, hi, getter=_getter).target_positions == 6
    assert resolve_position_sizing(100_000_000, lo, getter=_getter).per_position_rate <= 0.06


def test_shadow_sizing_never_raises_and_logs(caplog):
    # shadow는 매수 경로를 절대 막으면 안 됨 — 최소 balance로도 예외 없이 로그만
    import logging
    from backend.services.engine.order_executor import OrderExecutor
    oe = OrderExecutor.__new__(OrderExecutor)
    balance = {"output2": [{"ord_psbl_cash": "100000000", "tot_evlu_amt": "100000000"}]}
    with caplog.at_level(logging.INFO):
        oe._shadow_new_sizing("005930", 70000.0, balance, actual_qty=10)  # 예외 없어야
    assert any("SHADOW-SIZING" in r.message for r in caplog.records)


def test_shadow_sizing_swallows_bad_balance():
    # 잘못된 balance여도 매수 경로 안 막음(예외 삼킴)
    from backend.services.engine.order_executor import OrderExecutor
    oe = OrderExecutor.__new__(OrderExecutor)
    oe._shadow_new_sizing("005930", 70000.0, {}, actual_qty=0)  # raise 안 하면 통과


def test_build_playbook_assembles_sell_and_sizing():
    regime_set = {"stop_loss_rate": -0.035, "take_profit_rate": 0.08,
                  "trailing_activate_profit": 0.04, "trailing_stop_rate": 0.02}
    pb = build_playbook("risk_on", regime_settings=regime_set, getter=_getter)
    assert pb.regime == "risk_on"
    assert pb.sell["stop_loss_rate"] == -0.035
    assert pb.sizing["per_position_rate_max"] == 0.15
    assert pb.sizing["positions_max"] == 19
