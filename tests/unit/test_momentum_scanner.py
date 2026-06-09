import backend.services.engine.momentum_scanner as ms


def test_pick_new_symbols_excludes_existing_held_cooldown(monkeypatch):
    movers = [{"symbol": "111", "change_rate": 20, "volume": 1000},
              {"symbol": "222", "change_rate": 15, "volume": 2000},
              {"symbol": "333", "change_rate": 12, "volume": 3000}]
    existing = {"111"}          # 이미 감시중
    held = {"222"}              # 보유중
    monkeypatch.setattr(ms, "_in_cooldown", lambda s: s == "333")  # 333 쿨다운
    new = ms._pick_new_symbols(movers, existing=existing, held=held)
    assert [m["symbol"] for m in new] == []  # 셋 다 제외


def test_pick_new_symbols_returns_fresh(monkeypatch):
    movers = [{"symbol": "444", "change_rate": 18, "volume": 5000}]
    monkeypatch.setattr(ms, "_in_cooldown", lambda s: False)
    new = ms._pick_new_symbols(movers, existing=set(), held=set())
    assert [m["symbol"] for m in new] == ["444"]
