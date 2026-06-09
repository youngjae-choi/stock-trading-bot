import asyncio

import backend.services.engine.decision_engine as de


def test_add_merges_and_caps(monkeypatch):
    eng = de.decision_engine
    eng._candidates = {"A": {"symbol": "A"}}
    monkeypatch.setattr(de, "load_daily_rules", lambda today, syms: len(syms))
    captured = {}

    async def fake_start(symbols):
        captured["symbols"] = symbols

    monkeypatch.setattr(de.realtime_ws_manager, "start", fake_start)
    monkeypatch.setattr(de.position_manager, "get_positions", lambda: [])
    monkeypatch.setattr(de, "get_setting", lambda k, d=None: 40 if "max_sub" in k else d, raising=False)
    new = [{"symbol": "B"}, {"symbol": "C"}, {"symbol": "A"}]  # A 중복
    out = asyncio.run(eng.add_momentum_candidates(new))
    assert set(eng._candidates.keys()) == {"A", "B", "C"}
    assert out["added"] == 2  # B, C
    assert "A" in captured["symbols"] and "B" in captured["symbols"]
