from fastapi.testclient import TestClient

import backend.main as main_mod
import backend.services.engine.buy_condition_framework as bcf

client = TestClient(main_mod.app)


def _seeded():
    bcf._ensure_tables()
    bcf._clear_all_for_test()
    bcf.seed_defaults()


def test_get_conditions_includes_disabled():
    _seeded()
    r = client.get("/api/v1/buy-conditions/conditions")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    conds = body["payload"]["conditions"]
    ctypes = {c["ctype"] for c in conds}
    assert "day_high_breakout" in ctypes
    assert "chegyeol_gangdo_min" in ctypes
    # 모든 조건에 필수 키 존재
    for c in conds:
        assert set(["id", "name", "ctype", "params", "enabled"]).issubset(c.keys())


def test_put_condition_updates_params_and_enabled():
    _seeded()
    r = client.put(
        "/api/v1/buy-conditions/conditions/cond_gangdo",
        json={"params": {"min": 0.70}, "enabled": False},
    )
    assert r.status_code == 200
    cond = r.json()["payload"]["condition"]
    assert cond["params"]["min"] == 0.70
    assert cond["enabled"] is False
    # 영속 확인 (enabled_only=False 로드)
    after = bcf.load_conditions(enabled_only=False)["cond_gangdo"]
    assert after["params"]["min"] == 0.70
    assert after["enabled"] is False


def test_put_condition_missing_returns_404():
    _seeded()
    r = client.put("/api/v1/buy-conditions/conditions/no_such", json={"enabled": True})
    assert r.status_code == 404


def test_get_groups_includes_defaults():
    _seeded()
    r = client.get("/api/v1/buy-conditions/groups")
    assert r.status_code == 200
    groups = r.json()["payload"]["groups"]
    names = {g["name"] for g in groups}
    assert {"돌파전략", "눌림전략", "모멘텀전략"}.issubset(names)
    for g in groups:
        assert set(["id", "name", "condition_ids", "enabled", "weight", "assigned_to"]).issubset(g.keys())


def test_post_group_creates_and_persists():
    _seeded()
    r = client.post(
        "/api/v1/buy-conditions/groups",
        json={"name": "테스트전략", "condition_ids": ["cond_breakout", "cond_gangdo"],
              "weight": 1.5, "assigned_to": "regime:risk_on"},
    )
    assert r.status_code == 200
    g = r.json()["payload"]["group"]
    assert g["name"] == "테스트전략"
    assert g["condition_ids"] == ["cond_breakout", "cond_gangdo"]
    assert g["weight"] == 1.5
    assert g["assigned_to"] == "regime:risk_on"
    # 영속 확인
    found = [x for x in bcf.load_groups(enabled_only=False) if x["id"] == g["id"]]
    assert found and found[0]["name"] == "테스트전략"


def test_put_group_updates_assignment_and_enabled():
    _seeded()
    r = client.put(
        "/api/v1/buy-conditions/groups/grp_pullback",
        json={"enabled": False, "weight": 0.5, "assigned_to": "profile:HIGH_VOL",
              "condition_ids": ["cond_pullback"]},
    )
    assert r.status_code == 200
    g = r.json()["payload"]["group"]
    assert g["enabled"] is False
    assert g["weight"] == 0.5
    assert g["assigned_to"] == "profile:HIGH_VOL"
    assert g["condition_ids"] == ["cond_pullback"]


def test_put_group_missing_returns_404():
    _seeded()
    r = client.put("/api/v1/buy-conditions/groups/no_such", json={"enabled": True})
    assert r.status_code == 404


def test_assign_targets_lists_regimes_and_profiles():
    r = client.get("/api/v1/buy-conditions/assign-targets")
    assert r.status_code == 200
    p = r.json()["payload"]
    assert "regimes" in p and "profiles" in p
    assert "HIGH_VOL" in p["profiles"]
    assert len(p["regimes"]) >= 1
