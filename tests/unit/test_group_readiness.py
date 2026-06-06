"""group-based 매수 준비도 순수 함수 테스트 — OR(AND-그룹들)."""

from __future__ import annotations

from backend.api.routes.trading_monitor import (
    _build_readiness_state,
    _compute_group_readiness,
)


def _conditions() -> dict[str, dict]:
    return {
        "c_break": {"id": "c_break", "name": "당일고가 돌파", "ctype": "day_high_breakout", "params": {"buffer_pct": 0}},
        "c_gangdo": {"id": "c_gangdo", "name": "체결강도 55%+", "ctype": "chegyeol_gangdo_min", "params": {"min": 0.55}},
        "c_cr": {"id": "c_cr", "name": "등락률 1.5~5%", "ctype": "change_rate_band", "params": {"min": 1.5, "max": 5.0}},
        "c_tsi": {"id": "c_tsi", "name": "일봉 TSI>0", "ctype": "tsi_positive", "params": {"min": 0}},
    }


def _groups() -> list[dict]:
    return [
        {"id": "g_break", "name": "돌파전략", "condition_ids": ["c_break", "c_gangdo"]},
        {"id": "g_base", "name": "베이스라인", "condition_ids": ["c_cr", "c_tsi"]},
    ]


def test_one_group_fully_met_or_true():
    conds = _conditions()
    groups = _groups()
    # 돌파전략 완전충족(돌파 True + 체결강도 0.6>=0.55), 베이스라인 부분충족(등락률만 OK, TSI<=0)
    state = {
        "day_high_breakout": True,
        "체결강도": 0.6,
        "change_rate": 3.0,   # 1.5~5 → met
        "tsi": -1.0,          # tsi>0 False → 베이스라인 미충족
    }
    out = _compute_group_readiness(state, groups, conds)
    assert out["mode"] == "or_groups"
    assert out["any_met"] is True
    by_name = {g["name"]: g for g in out["groups"]}
    assert by_name["돌파전략"]["met"] is True
    assert by_name["돌파전략"]["met_count"] == 2
    assert by_name["돌파전략"]["total"] == 2
    assert by_name["베이스라인"]["met"] is False
    assert by_name["베이스라인"]["met_count"] == 1
    # overall_pct = 가장 근접한(=충족) 그룹 비율 = 100
    assert out["overall_pct"] == 100.0


def test_no_group_met_or_false():
    conds = _conditions()
    groups = _groups()
    state = {
        "day_high_breakout": False,
        "체결강도": 0.1,
        "change_rate": 0.2,   # 범위 밖
        "tsi": -1.0,
    }
    out = _compute_group_readiness(state, groups, conds)
    assert out["any_met"] is False
    assert all(g["met"] is False for g in out["groups"])
    # 가장 근접한 그룹의 met/total = 0/2 → 0%
    assert out["overall_pct"] == 0.0


def test_overall_pct_reflects_closest_group():
    conds = _conditions()
    groups = _groups()
    # 어느 그룹도 완전충족 안 됨. 돌파전략 1/2, 베이스라인 2/2는 아니고 1/2.
    # 돌파전략: 돌파 True, 체결강도 0.1 미달 → 1/2
    # 베이스라인: 등락률 met, tsi -1 미달 → 1/2  → overall 50%
    state = {
        "day_high_breakout": True,
        "체결강도": 0.1,
        "change_rate": 3.0,
        "tsi": -1.0,
    }
    out = _compute_group_readiness(state, groups, conds)
    assert out["any_met"] is False
    assert out["overall_pct"] == 50.0


def test_condition_shape_has_required_keys():
    conds = _conditions()
    groups = _groups()
    state = {"day_high_breakout": True, "체결강도": 0.6, "change_rate": 3.0, "tsi": 1.0}
    out = _compute_group_readiness(state, groups, conds)
    cond0 = out["groups"][0]["conditions"][0]
    for key in ("name", "label", "ctype", "met", "current_value", "threshold_label"):
        assert key in cond0


def test_build_readiness_state_merges_live_and_candidate():
    candidate = {"change_rate": 2.5, "tsi": 12.0}
    tick = {"change_rate": 3.1}
    live = {"체결강도": 0.7, "tick_vol_mult": 2.2, "day_high_breakout": True, "tsi": None}
    state = _build_readiness_state(candidate, tick, live)
    # tick.change_rate 우선
    assert state["change_rate"] == 3.1
    # candidate.tsi가 live None을 덮음
    assert state["tsi"] == 12.0
    # live 신호 보존
    assert state["체결강도"] == 0.7
    assert state["day_high_breakout"] is True
    # time_hhmm 채워짐 (HH:MM 형식)
    assert ":" in state["time_hhmm"]


def test_build_readiness_state_change_rate_falls_back_to_candidate():
    candidate = {"change_rate": 2.5}
    tick = {}
    state = _build_readiness_state(candidate, tick, {})
    assert state["change_rate"] == 2.5
    # live 신호 없으면 체결강도/tick_vol_mult는 0 폴백
    assert state["체결강도"] == 0.0
    assert state["tick_vol_mult"] == 0.0
