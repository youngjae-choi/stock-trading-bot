"""전략설정 엔진 — 예수금비중 사이징 모델(결정4) 검증.

종목당 5~15% 비중, 종목수 6~19 파생. 확신↑ → 집중(비중↑·종목수↓).
"""
from __future__ import annotations

from backend.services.engine.strategy_playbook import (
    build_playbook,
    get_playbook,
    resolve_conviction,
    resolve_max_positions,
    resolve_position_sizing,
)

# 테스트용 설정 getter — DB 없이 PM 확정값 주입
_CFG = {
    "sizing.per_position_rate_min": 0.05,
    "risk.max_position_rate_per_stock": 0.15,
    "sizing.positions_min": 6,
    "sizing.positions_max": 19,
    "exploration.deploy_target_rate": 0.95,
    # 2026-08-29 PM: 종목당 절대금액 통제(500만~2000만)
    "sizing.per_position_min_krw": 5_000_000,
    "sizing.per_position_max_krw": 20_000_000,
}


def _getter(key, default=None):
    return _CFG.get(key, default)


def test_high_conviction_max_amount_concentrates():
    """확신 1.0 → 종목당 최대금액(2000만) = 집중. 종목수는 파생(클램프 없음)."""
    r = resolve_position_sizing(100_000_000, conviction=1.0, getter=_getter)
    assert r.per_position_krw == 20_000_000        # min + (max-min)×1.0 = 2000만
    assert r.target_positions == 4                 # int(9500만/2000만) = 4 (구 [6,19] 하한 6 아님)


def test_low_conviction_min_amount_diversifies():
    """확신 0.0 → 종목당 최소금액(500만) = 분산."""
    r = resolve_position_sizing(100_000_000, conviction=0.0, getter=_getter)
    assert r.per_position_krw == 5_000_000
    assert r.target_positions == 19                # int(9500만/500만) = 19


def test_amount_independent_of_deposit():
    """종목당 금액은 예수금과 무관하게 확신도로 결정(투입율은 종목수만 좌우)."""
    r_small = resolve_position_sizing(50_000_000, conviction=1.0, getter=_getter)
    r_big = resolve_position_sizing(300_000_000, conviction=1.0, getter=_getter)
    assert r_small.per_position_krw == r_big.per_position_krw == 20_000_000
    # 종목수만 예수금에 따라 파생 — [6,19] 클램프 없음(300M/2000만 배포 → 14개)
    assert r_big.target_positions == 14            # int(2.85억/2000만) = 14


def test_surge_expands_max_amount():
    """폭등 티어(per_rate_max↑)면 최대 금액이 비례 확대된다."""
    # 기본 max_rate 0.15, 폭등 0.30 → max_krw 2000만 × 2 = 4000만
    r = resolve_position_sizing(200_000_000, conviction=1.0, getter=_getter, per_rate_max=0.30)
    assert r.per_position_krw == 40_000_000


def test_mid_conviction_amount_interpolates():
    """확신 0.5 → 종목당 금액 중간(1250만), 종목수 파생."""
    r = resolve_position_sizing(100_000_000, conviction=0.5, getter=_getter)
    assert r.per_position_krw == 12_500_000       # 500만 + 1500만×0.5
    assert r.target_positions == 7                # int(9500만/1250만) = 7


def test_amount_stays_within_min_max_bounds():
    """모든 확신도에서 종목당 금액이 [min,max] 내 — [6,19] 종목수 클램프 없음."""
    for c in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
        r = resolve_position_sizing(100_000_000, conviction=c, getter=_getter)
        assert 5_000_000 <= r.per_position_krw <= 20_000_000


def test_conviction_clamped():
    """확신도 [0,1] 밖은 클램프 — 금액 상/하한으로."""
    hi = resolve_position_sizing(100_000_000, conviction=5.0, getter=_getter)
    lo = resolve_position_sizing(100_000_000, conviction=-3.0, getter=_getter)
    assert hi.per_position_krw == 20_000_000
    assert lo.per_position_krw == 5_000_000


def test_zero_deposit_safe():
    """예수금 0 → 종목수 0(배포 여력 없음)."""
    r = resolve_position_sizing(0, conviction=1.0, getter=_getter)
    assert r.target_positions == 0


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


def test_surge_tier_raises_ceiling():
    # 폭등 티어: per_rate_max override로 종목당 상한↑ (확신 1.0에서 15%→20%)
    normal = resolve_position_sizing(100_000_000, 1.0, getter=_getter)
    surge = resolve_position_sizing(100_000_000, 1.0, getter=_getter, per_rate_max=0.20)
    assert normal.per_position_krw == 20_000_000
    assert surge.per_position_krw == 26_666_666.67          # 2000만 × (0.20/0.15)


def test_surge_default_no_change():
    # override 없으면(=기본) 동작 불변
    a = resolve_position_sizing(100_000_000, 0.5, getter=_getter)
    b = resolve_position_sizing(100_000_000, 0.5, getter=_getter, per_rate_max=None)
    assert a.per_position_rate == b.per_position_rate


def test_conviction_feeds_sizing_end_to_end():
    # 결합: 최고 확신 → 최대금액(2000만) 집중, 최저 확신 → 최소금액(500만) 분산
    hi = resolve_conviction("risk_on", -3.0, getter=_cgetter)
    lo = resolve_conviction("risk_off", 2.0, getter=_cgetter)
    assert resolve_position_sizing(100_000_000, hi, getter=_getter).per_position_krw == 20_000_000
    assert resolve_position_sizing(100_000_000, lo, getter=_getter).per_position_krw <= 7_000_000


def test_resolve_max_positions_returns_model_ceiling():
    # [6,19] 모델의 상한 = positions_max
    assert resolve_max_positions(getter=_getter) == 19


# ── 전략설정 엔진① — get_playbook 권위 ──
_PB = {
    "selection.change_weight": 0.5, "selection.surge_weight": 0.5,
    "engine.entry_vwap_pullback_mode": "enforce", "engine.max_price_change_pct": 4.0,
    "engine.min_price_change_pct": 1.5, "engine.min_volume_ratio": 1.5,
    "sizing.per_position_rate_min": 0.05, "risk.max_position_rate_per_stock": 0.15,
    "sizing.positions_min": 6, "sizing.positions_max": 19,
    "exploration.deploy_target_rate": 0.95, "sizing.surge_per_position_rate_max": 0.20,
}


def _pb(k, d=None):
    return _PB.get(k, d)


def test_get_playbook_full_strategy_all_axes():
    # 레짐→전략 한 벌: 선정+매수게이트+매도+사이징 전부 채워짐
    rset = {"stop_loss_rate": -0.035, "take_profit_rate": 0.08}
    pb = get_playbook("up", regime_set=rset, getter=_pb)
    assert pb.regime == "up" and pb.set_label == "risk_on"
    assert pb.selection["change_weight"] == 0.5
    assert pb.gates["vwap_pullback_mode"] == "enforce"
    assert pb.sell["stop_loss_rate"] == -0.035
    assert pb.sizing["per_position_rate_max"] == 0.15  # 비폭등


def test_get_playbook_surge_expands_sizing():
    # 폭등 5장세 → 사이징 상한이 surge 값으로
    pb = get_playbook("surge", regime_set={}, getter=_pb)
    assert pb.set_label == "risk_on"          # 상승 SET 재사용
    assert pb.sizing["per_position_rate_max"] == 0.20  # 확대
    assert pb.sizing["surge_tier"] is True


def test_get_playbook_regime5_to_set_mapping():
    assert get_playbook("crash", getter=_pb).set_label == "risk_off"
    assert get_playbook("down", getter=_pb).set_label == "risk_off"
    assert get_playbook("flat", getter=_pb).set_label == "neutral"


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


def test_compute_new_model_sizing_caps_by_deployable():
    # 신모델 수량은 가용현금(95% 배포)으로 캡 — 과배포 안 함
    from backend.services.engine.order_executor import OrderExecutor
    oe = OrderExecutor.__new__(OrderExecutor)
    # 총자산 1억(버퍼 5백만) · 가용현금 1천만 → deployable 5백만으로 신모델(중립 1천만) 캡
    balance = {"output2": [{"ord_psbl_cash": "10000000", "tot_evlu_amt": "100000000"}]}
    info = oe._compute_new_model_sizing("005930", 70000.0, balance)
    assert info is not None
    assert info["new_qty"] <= 5_000_000 // 70000 + 1   # deployable(5백만) 캡 이내
    assert info["new_qty"] >= 0


def test_compute_new_model_sizing_bad_price_returns_none():
    from backend.services.engine.order_executor import OrderExecutor
    oe = OrderExecutor.__new__(OrderExecutor)
    assert oe._compute_new_model_sizing("005930", 0.0, {"output2": [{}]}) is None


def test_build_playbook_assembles_sell_and_sizing():
    regime_set = {"stop_loss_rate": -0.035, "take_profit_rate": 0.08,
                  "trailing_activate_profit": 0.04, "trailing_stop_rate": 0.02}
    pb = build_playbook("risk_on", regime_settings=regime_set, getter=_getter)
    assert pb.regime == "risk_on"
    assert pb.sell["stop_loss_rate"] == -0.035
    assert pb.sizing["per_position_rate_max"] == 0.15
    assert pb.sizing["positions_max"] == 19


# ── 레짐별 VWAP 진입밴드 (2026-09-05 BackDB 335건: 상승장 천장완화 + falling knife floor) ──

def _band_getter(overrides=None):
    o = overrides or {}
    return lambda k, d=None: o.get(k, d)  # 미지정 키는 코드 기본값(=밴드 검증 대상)


def test_vwap_ceiling_relaxed_in_up_regimes():
    """상승장(up/surge/risk_on)은 천장 0.0 — VWAP까지 허용(돌파>0는 여전히 차단)."""
    for rg in ("up", "surge", "risk_on"):
        assert build_playbook(rg, getter=_band_getter()).gates["entry_max_vwap_dist_pct"] == 0.0, rg


def test_vwap_ceiling_tight_in_defensive_regimes():
    """보합/하락(flat/neutral/down/risk_off/volatile/crash)은 천장 -1.0(눌림만 고수)."""
    for rg in ("flat", "neutral", "down", "risk_off", "volatile", "crash"):
        assert build_playbook(rg, getter=_band_getter()).gates["entry_max_vwap_dist_pct"] == -1.0, rg


def test_vwap_floor_is_regime_common():
    """바닥(falling knife) -5.0은 전 레짐 공통 — 딥눌림(<-5%) 진입 차단."""
    for rg in ("up", "flat", "risk_off", "surge"):
        assert build_playbook(rg, getter=_band_getter()).gates["entry_min_vwap_dist_pct"] == -5.0, rg


def test_vwap_ceiling_riskon_override_rolls_back():
    """롤백 스위치: engine.entry_max_vwap_dist_pct_riskon=-1 → 상승장도 눌림 원복."""
    g = _band_getter({"engine.entry_max_vwap_dist_pct_riskon": -1.0})
    assert build_playbook("risk_on", getter=g).gates["entry_max_vwap_dist_pct"] == -1.0


def test_vwap_floor_override():
    """floor 튜닝: engine.entry_min_vwap_dist_pct 존중."""
    g = _band_getter({"engine.entry_min_vwap_dist_pct": -8.0})
    assert build_playbook("flat", getter=g).gates["entry_min_vwap_dist_pct"] == -8.0


def test_resolve_buy_gates_applies_regime_band():
    """회귀: resolve_buy_gates가 레짐을 받아 밴드를 차등 적용(기존 'flat' 기본→상승장 눌림고정 갭 수정)."""
    from backend.services.engine.buy_engine import resolve_buy_gates
    g = _band_getter()
    assert resolve_buy_gates("up", getter=g)["entry_max_vwap_dist_pct"] == 0.0
    assert resolve_buy_gates("flat", getter=g)["entry_max_vwap_dist_pct"] == -1.0
    assert resolve_buy_gates("up", getter=g)["entry_min_vwap_dist_pct"] == -5.0
