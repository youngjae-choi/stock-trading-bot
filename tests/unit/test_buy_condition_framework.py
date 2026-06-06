import backend.services.engine.buy_condition_framework as bcf


_S = {
    "change_rate": 2.3, "체결강도": 0.62, "tick_vol_mult": 2.3, "tsi": 11.0,
    "vwap_position": "above", "day_high_breakout": True, "pullback_rebound": False,
    "rising_bars": 3, "time_hhmm": "10:30",
}


def test_change_rate_band():
    c = {"ctype": "change_rate_band", "params": {"min": 1.5, "max": 5.0}}
    assert bcf.evaluate_condition(c, _S) is True
    assert bcf.evaluate_condition(c, {**_S, "change_rate": 6.0}) is False
    assert bcf.evaluate_condition(c, {**_S, "change_rate": 1.0}) is False


def test_chegyeol_gangdo_min():
    c = {"ctype": "chegyeol_gangdo_min", "params": {"min": 0.55}}
    assert bcf.evaluate_condition(c, _S) is True
    assert bcf.evaluate_condition(c, {**_S, "체결강도": 0.50}) is False


def test_tick_volume_mult_min():
    c = {"ctype": "tick_volume_mult_min", "params": {"min": 2.0}}
    assert bcf.evaluate_condition(c, _S) is True
    assert bcf.evaluate_condition(c, {**_S, "tick_vol_mult": 1.5}) is False


def test_tsi_positive_passes_on_missing():
    c = {"ctype": "tsi_positive", "params": {}}
    assert bcf.evaluate_condition(c, _S) is True
    assert bcf.evaluate_condition(c, {**_S, "tsi": None}) is True   # 결손은 통과(차단 금지)
    assert bcf.evaluate_condition(c, {**_S, "tsi": -5.0}) is False


def test_vwap_above():
    c = {"ctype": "vwap_above", "params": {}}
    assert bcf.evaluate_condition(c, _S) is True
    assert bcf.evaluate_condition(c, {**_S, "vwap_position": "below"}) is False


def test_bool_conditions():
    assert bcf.evaluate_condition({"ctype": "day_high_breakout", "params": {}}, _S) is True
    assert bcf.evaluate_condition({"ctype": "pullback_rebound", "params": {}}, _S) is False


def test_momentum_rising_bars():
    c = {"ctype": "momentum_rising_bars", "params": {"min_bars": 3}}
    assert bcf.evaluate_condition(c, _S) is True
    assert bcf.evaluate_condition(c, {**_S, "rising_bars": 2}) is False


def test_time_window():
    c = {"ctype": "time_window", "params": {"start": "09:30", "end": "15:00"}}
    assert bcf.evaluate_condition(c, _S) is True
    assert bcf.evaluate_condition(c, {**_S, "time_hhmm": "15:10"}) is False


def test_unknown_ctype_is_false():
    assert bcf.evaluate_condition({"ctype": "nonsense", "params": {}}, _S) is False


def test_group_and_all_pass():
    conds = {
        "c1": {"id": "c1", "ctype": "day_high_breakout", "params": {}},
        "c2": {"id": "c2", "ctype": "chegyeol_gangdo_min", "params": {"min": 0.55}},
    }
    group = {"id": "g1", "name": "돌파", "condition_ids": ["c1", "c2"]}
    assert bcf.evaluate_group(group, conds, _S) is True
    assert bcf.evaluate_group(group, conds, {**_S, "체결강도": 0.4}) is False  # AND 하나 실패


def test_group_empty_conditions_is_false():
    assert bcf.evaluate_group({"id": "g", "name": "x", "condition_ids": []}, {}, _S) is False


def test_evaluate_groups_or():
    conds = {
        "c1": {"id": "c1", "ctype": "day_high_breakout", "params": {}},
        "c2": {"id": "c2", "ctype": "pullback_rebound", "params": {}},
    }
    groups = [
        {"id": "g1", "name": "돌파", "condition_ids": ["c1"]},
        {"id": "g2", "name": "눌림", "condition_ids": ["c2"]},
    ]
    out = bcf.evaluate_groups_or(groups, conds, _S)  # 돌파만 충족
    assert out["any"] is True
    assert out["fired"] == ["돌파"]
    out2 = bcf.evaluate_groups_or(groups, conds, {**_S, "day_high_breakout": False})
    assert out2["any"] is False
    assert out2["fired"] == []
