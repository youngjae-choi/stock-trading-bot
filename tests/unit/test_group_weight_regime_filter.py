"""과제 A2 — 매수 조건그룹 평가의 weight 가중치·레짐(assigned_to) 필터 테스트.

DB 미접촉: evaluate_groups_or 는 순수 함수, evaluate_exploration_buy 는
get_setting 을 monkeypatch 해 격리한다.
"""

import backend.services.engine.buy_condition_framework as bcf
import backend.services.engine.exploration_decision as ed


# 돌파(day_high_breakout=True)는 발화하는 state
_S = {
    "change_rate": 2.3, "체결강도": 0.62, "tick_vol_mult": 2.3, "tsi": 11.0,
    "vwap_position": "above", "day_high_breakout": True, "pullback_rebound": False,
    "rising_bars": 3, "time_hhmm": "10:30",
}

_CONDS = {
    "c1": {"id": "c1", "ctype": "day_high_breakout", "params": {}},
}


def _group(name, *, weight=1.0, assigned_to=""):
    return {
        "id": name, "name": name, "condition_ids": ["c1"],
        "weight": weight, "assigned_to": assigned_to,
    }


# ── weight_floor 필터 ──────────────────────────────────────────


def test_weight_below_floor_is_skipped():
    # EV 가지치기로 weight 0.1 까지 깎인 그룹은 발화하지 않는다
    out = bcf.evaluate_groups_or([_group("저가중치", weight=0.1)], _CONDS, _S)
    assert out["any"] is False
    assert out["fired"] == []
    assert out["skipped"] == [{"name": "저가중치", "reason": "weight_floor"}]


def test_weight_at_or_above_floor_fires():
    out = bcf.evaluate_groups_or([_group("정상", weight=1.0)], _CONDS, _S)
    assert out["any"] is True
    assert out["fired"] == ["정상"]
    assert out["skipped"] == []


def test_weight_floor_param_override():
    # weight_floor 를 올리면 0.5 그룹도 제외된다
    out = bcf.evaluate_groups_or(
        [_group("중간", weight=0.5)], _CONDS, _S, weight_floor=0.6
    )
    assert out["any"] is False
    assert out["skipped"] == [{"name": "중간", "reason": "weight_floor"}]


def test_missing_weight_defaults_to_one():
    # weight 키 없는 그룹(기존 호출부 호환)은 1.0 으로 간주 → 발화
    g = {"id": "g1", "name": "무가중치", "condition_ids": ["c1"]}
    out = bcf.evaluate_groups_or([g], _CONDS, _S)
    assert out["any"] is True
    assert out["fired"] == ["무가중치"]


# ── 레짐(assigned_to) 필터 ─────────────────────────────────────


def test_regime_mismatch_is_skipped():
    # assigned_to="risk_on" 그룹은 regime="risk_off" 에서 제외된다
    out = bcf.evaluate_groups_or(
        [_group("리스크온전용", assigned_to="risk_on")], _CONDS, _S, regime="risk_off"
    )
    assert out["any"] is False
    assert out["fired"] == []
    assert out["skipped"] == [{"name": "리스크온전용", "reason": "regime_filter"}]


def test_regime_match_fires():
    out = bcf.evaluate_groups_or(
        [_group("리스크온전용", assigned_to="risk_on")], _CONDS, _S, regime="risk_on"
    )
    assert out["any"] is True
    assert out["fired"] == ["리스크온전용"]


def test_empty_assigned_to_fires_in_any_regime():
    # assigned_to 빈 값 = 모든 레짐 허용
    out = bcf.evaluate_groups_or(
        [_group("전체허용", assigned_to="")], _CONDS, _S, regime="risk_off"
    )
    assert out["any"] is True
    assert out["fired"] == ["전체허용"]


def test_regime_none_disables_filter():
    # regime=None 이면 assigned_to 무관하게 평가(필터 미적용, fail-open)
    out = bcf.evaluate_groups_or(
        [_group("리스크온전용", assigned_to="risk_on")], _CONDS, _S, regime=None
    )
    assert out["any"] is True
    assert out["fired"] == ["리스크온전용"]


def test_assigned_to_comma_separated_string():
    # 콤마구분 문자열(현재 DB 저장 형식) — 포함된 레짐이면 발화
    g = _group("복수레짐", assigned_to="risk_on, neutral")
    assert bcf.evaluate_groups_or([g], _CONDS, _S, regime="neutral")["any"] is True
    assert bcf.evaluate_groups_or([g], _CONDS, _S, regime="risk_off")["any"] is False


def test_assigned_to_list_form():
    # list 형식도 허용
    g = _group("리스트레짐", assigned_to=["risk_on", "neutral"])
    assert bcf.evaluate_groups_or([g], _CONDS, _S, regime="neutral")["any"] is True
    assert bcf.evaluate_groups_or([g], _CONDS, _S, regime="risk_off")["any"] is False


def test_skipped_reasons_recorded_per_group():
    groups = [
        _group("저가중치", weight=0.1),
        _group("타레짐", assigned_to="risk_on"),
        _group("발화", weight=1.0),
    ]
    out = bcf.evaluate_groups_or(groups, _CONDS, _S, regime="risk_off")
    assert out["any"] is True
    assert out["fired"] == ["발화"]
    assert {(s["name"], s["reason"]) for s in out["skipped"]} == {
        ("저가중치", "weight_floor"), ("타레짐", "regime_filter"),
    }


# ── evaluate_exploration_buy 연동 ──────────────────────────────


class _FakeBarEngine:
    def __init__(self, state):
        self._state = state

    def compute_signal_state(self, symbol):
        return dict(self._state)


def test_exploration_buy_passes_regime_and_weight_floor(monkeypatch):
    # get_setting("exploration.weight_floor") 값이 평가에 반영된다
    monkeypatch.setattr(ed, "get_setting", lambda key, default=None: 0.5)
    groups = [
        _group("저가중치", weight=0.3),                  # floor 0.5 미만 → 제외
        _group("타레짐", assigned_to="risk_on"),          # regime 불일치 → 제외
    ]
    out = ed.evaluate_exploration_buy(
        symbol="005930", bar_engine=_FakeBarEngine(_S),
        groups=groups, conditions=_CONDS, tsi=None, regime="risk_off",
    )
    assert out["any"] is False
    assert out["fired"] == []
    assert {(s["name"], s["reason"]) for s in out["skipped"]} == {
        ("저가중치", "weight_floor"), ("타레짐", "regime_filter"),
    }


def test_exploration_buy_regime_default_none_keeps_behavior(monkeypatch):
    # regime 미전달(기존 호출부 호환) → 레짐 필터 미적용
    monkeypatch.setattr(ed, "get_setting", lambda key, default=None: default)
    groups = [_group("리스크온전용", assigned_to="risk_on")]
    out = ed.evaluate_exploration_buy(
        symbol="005930", bar_engine=_FakeBarEngine(_S),
        groups=groups, conditions=_CONDS, tsi=None,
    )
    assert out["any"] is True
    assert out["fired"] == ["리스크온전용"]


def test_exploration_buy_weight_floor_setting_failure_falls_back(monkeypatch):
    # 설정 조회 실패 시 기본 floor 0.2 로 폴백(차단 금지)
    def _boom(key, default=None):
        raise RuntimeError("settings db down")

    monkeypatch.setattr(ed, "get_setting", _boom)
    groups = [_group("정상", weight=1.0)]
    out = ed.evaluate_exploration_buy(
        symbol="005930", bar_engine=_FakeBarEngine(_S),
        groups=groups, conditions=_CONDS, tsi=None, regime=None,
    )
    assert out["any"] is True
