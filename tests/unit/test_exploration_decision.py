import backend.services.engine.exploration_decision as ed


class _FakeBarEngine:
    def __init__(self, state):
        self._state = state

    def compute_signal_state(self, symbol):
        return dict(self._state)


_STATE_FIRES = {
    "change_rate": 2.3, "체결강도": 0.62, "tick_vol_mult": 2.3, "tsi": None,
    "vwap_position": "above", "day_high_breakout": True, "pullback_rebound": False,
    "rising_bars": 3, "time_hhmm": "10:30",
}


def test_evaluate_returns_fired_groups_and_states():
    conds = {
        "c1": {"id": "c1", "ctype": "day_high_breakout", "params": {}},
        "c2": {"id": "c2", "ctype": "chegyeol_gangdo_min", "params": {"min": 0.55}},
    }
    groups = [{"id": "g1", "name": "돌파전략", "condition_ids": ["c1", "c2"]}]
    eng = _FakeBarEngine(_STATE_FIRES)
    out = ed.evaluate_exploration_buy(
        symbol="005930", bar_engine=eng, groups=groups, conditions=conds, tsi=11.0,
    )
    assert out["any"] is True
    assert out["fired"] == ["돌파전략"]
    # condition_states 는 진입 스냅샷 — 주입된 tsi 가 반영됨
    assert out["condition_states"]["tsi"] == 11.0
    assert out["condition_states"]["체결강도"] == 0.62


def test_evaluate_no_fire_returns_any_false():
    conds = {"c1": {"id": "c1", "ctype": "day_high_breakout", "params": {}}}
    groups = [{"id": "g1", "name": "돌파전략", "condition_ids": ["c1"]}]
    state = {**_STATE_FIRES, "day_high_breakout": False}
    eng = _FakeBarEngine(state)
    out = ed.evaluate_exploration_buy(
        symbol="005930", bar_engine=eng, groups=groups, conditions=conds, tsi=None,
    )
    assert out["any"] is False
    assert out["fired"] == []


def test_evaluate_injects_tsi_into_state_for_evaluation():
    # state.tsi=None 이지만 tsi=-5 주입 시 tsi_positive 그룹은 발화하지 않아야 한다
    conds = {"c1": {"id": "c1", "ctype": "tsi_positive", "params": {}}}
    groups = [{"id": "g1", "name": "추세", "condition_ids": ["c1"]}]
    eng = _FakeBarEngine(_STATE_FIRES)
    out = ed.evaluate_exploration_buy(
        symbol="005930", bar_engine=eng, groups=groups, conditions=conds, tsi=-5.0,
    )
    assert out["any"] is False
    assert out["condition_states"]["tsi"] == -5.0


def test_evaluate_keeps_tsi_none_when_not_injected():
    conds = {"c1": {"id": "c1", "ctype": "tsi_positive", "params": {}}}
    groups = [{"id": "g1", "name": "추세", "condition_ids": ["c1"]}]
    eng = _FakeBarEngine(_STATE_FIRES)
    out = ed.evaluate_exploration_buy(
        symbol="005930", bar_engine=eng, groups=groups, conditions=conds, tsi=None,
    )
    # tsi None → tsi_positive 통과(결손 차단 금지) → 발화
    assert out["any"] is True
    assert out["condition_states"]["tsi"] is None


def test_build_exploration_tag_payload_shapes_record_entry_tag_kwargs():
    candidate = {"symbol": "005930", "name": "삼성전자", "score": 0.36,
                 "suitability_score": 0.72, "change_rate_rank": 3, "trade_rank": 5,
                 "tsi": 42.0, "llm_note": "반도체 강세"}
    decision = {"any": True, "fired": ["돌파전략"],
                "condition_states": {"체결강도": 0.62, "tsi": 11.0}}
    market_context = {"regime": "neutral", "market_tone": "negative",
                      "time_bucket": "10:30", "vix": 18.2}
    payload = ed.build_exploration_tag_payload(
        order_id="ord-1", symbol="005930", trade_date="2099-03-01",
        candidate=candidate, decision=decision, market_context=market_context,
    )
    # record_entry_tag 키워드 시그니처와 1:1 매칭
    assert payload["order_id"] == "ord-1"
    assert payload["symbol"] == "005930"
    assert payload["trade_date"] == "2099-03-01"
    assert payload["fired_groups"] == ["돌파전략"]
    assert payload["condition_states"]["체결강도"] == 0.62
    assert payload["market_context"]["regime"] == "neutral"
    # selection_reason 은 build_selection_reason 산출 — 등락률순위 포함
    assert "등락률순위#3" in payload["selection_reason"]["sources"]
    assert payload["selection_reason"]["scores"]["llm_suitability"] == 0.72
