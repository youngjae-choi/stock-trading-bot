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


def test_tsi_positive_min_param():
    # min=0 (기본/no-op) → 현재 동작과 동일: tsi>0
    c0 = {"ctype": "tsi_positive", "params": {"min": 0}}
    assert bcf.evaluate_condition(c0, {**_S, "tsi": 11.0}) is True
    assert bcf.evaluate_condition(c0, {**_S, "tsi": None}) is True   # 결손은 통과
    assert bcf.evaluate_condition(c0, {**_S, "tsi": -5.0}) is False
    # min=5 → 더 엄격: tsi>5
    c5 = {"ctype": "tsi_positive", "params": {"min": 5}}
    assert bcf.evaluate_condition(c5, {**_S, "tsi": 3.0}) is False
    assert bcf.evaluate_condition(c5, {**_S, "tsi": 11.0}) is True


def test_vwap_above():
    c = {"ctype": "vwap_above", "params": {}}
    assert bcf.evaluate_condition(c, _S) is True
    assert bcf.evaluate_condition(c, {**_S, "vwap_position": "below"}) is False


def test_vwap_above_margin_pct_param():
    base = {**_S, "price": 1000.0, "vwap": 1000.0}
    # margin_pct=0 (기본/no-op) → price>=vwap
    c0 = {"ctype": "vwap_above", "params": {"margin_pct": 0}}
    assert bcf.evaluate_condition(c0, base) is True
    # margin_pct=1 → price>=vwap*1.01 = 1010 필요 → 1000은 실패
    c1 = {"ctype": "vwap_above", "params": {"margin_pct": 1}}
    assert bcf.evaluate_condition(c1, base) is False
    # raw vwap 결손 → 기존 vwap_position 폴백
    c_fb = {"ctype": "vwap_above", "params": {"margin_pct": 0}}
    assert bcf.evaluate_condition(c_fb, {**_S, "vwap_position": "above"}) is True


def test_bool_conditions():
    assert bcf.evaluate_condition({"ctype": "day_high_breakout", "params": {}}, _S) is True
    assert bcf.evaluate_condition({"ctype": "pullback_rebound", "params": {}}, _S) is False


def test_day_high_breakout_buffer_pct_param():
    base = {**_S, "price": 1000.0, "prior_day_high": 1000.0}
    # buffer_pct=0 (기본/no-op) → price>=prior_day_high
    c0 = {"ctype": "day_high_breakout", "params": {"buffer_pct": 0}}
    assert bcf.evaluate_condition(c0, base) is True
    # buffer_pct=1 → price>=prior_day_high*1.01 = 1010 필요 → 1000은 실패
    c1 = {"ctype": "day_high_breakout", "params": {"buffer_pct": 1}}
    assert bcf.evaluate_condition(c1, base) is False
    # raw prior_day_high 결손 → 기존 day_high_breakout bool 폴백
    c_fb = {"ctype": "day_high_breakout", "params": {"buffer_pct": 0}}
    assert bcf.evaluate_condition(c_fb, {**_S, "day_high_breakout": True}) is True


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


def test_seed_and_load_roundtrip():
    bcf._ensure_tables()
    bcf._clear_all_for_test()
    bcf.seed_defaults()
    conds = bcf.load_conditions()
    groups = bcf.load_groups()
    # 기본 조건에 핵심 ctype 존재
    ctypes = {c["ctype"] for c in conds.values()}
    assert "day_high_breakout" in ctypes
    assert "chegyeol_gangdo_min" in ctypes
    # 기본 그룹 3패턴 + 베이스라인
    names = {g["name"] for g in groups}
    assert {"돌파전략", "눌림전략", "모멘텀전략"}.issubset(names)
    # 그룹의 condition_ids가 실제 conditions를 가리킴 (참조 무결성)
    for g in groups:
        for cid in g["condition_ids"]:
            assert cid in conds
    bcf._clear_all_for_test()


def test_seed_is_idempotent():
    bcf._ensure_tables()
    bcf._clear_all_for_test()
    bcf.seed_defaults()
    n1 = len(bcf.load_conditions())
    bcf.seed_defaults()  # 재호출
    n2 = len(bcf.load_conditions())
    assert n1 == n2  # 중복 시드 안 함
    bcf._clear_all_for_test()


def test_seed_defaults_include_tuning_params():
    bcf._ensure_tables()
    bcf._clear_all_for_test()
    bcf.seed_defaults()
    conds = bcf.load_conditions()
    assert conds["cond_tsi"]["params"] == {"min": 0}
    assert conds["cond_breakout"]["params"] == {"buffer_pct": 0}
    assert conds["cond_vwap"]["params"] == {"margin_pct": 0}
    bcf._clear_all_for_test()


def test_migrate_fills_empty_params_only():
    bcf._ensure_tables()
    bcf._clear_all_for_test()
    bcf.seed_defaults()
    # 빈 {}로 강제(기존 DB 시뮬레이션)
    with bcf.get_connection() as conn:
        conn.execute("UPDATE buy_conditions SET params_json='{}' WHERE id='cond_tsi'")
        # 운영자 커스텀 값(비어있지 않음) → 보존되어야 함
        conn.execute("UPDATE buy_conditions SET params_json='{\"margin_pct\": 2}' WHERE id='cond_vwap'")
    bcf.migrate_condition_params()
    conds = bcf.load_conditions()
    assert conds["cond_tsi"]["params"] == {"min": 0}          # 빈 → 채워짐
    assert conds["cond_vwap"]["params"] == {"margin_pct": 2}  # 커스텀 → 보존
    bcf._clear_all_for_test()


def test_migrate_is_idempotent():
    bcf._ensure_tables()
    bcf._clear_all_for_test()
    bcf.seed_defaults()
    bcf.migrate_condition_params()
    bcf.migrate_condition_params()  # 재호출
    conds = bcf.load_conditions()
    assert conds["cond_breakout"]["params"] == {"buffer_pct": 0}
    bcf._clear_all_for_test()
