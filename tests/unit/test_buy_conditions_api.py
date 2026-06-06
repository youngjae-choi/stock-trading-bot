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
