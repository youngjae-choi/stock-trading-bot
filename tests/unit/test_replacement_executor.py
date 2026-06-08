import asyncio
import backend.services.engine.replacement_executor as rx


def test_cooldown_blocks_recent_symbol(monkeypatch):
    monkeypatch.setattr(rx, "_last_swap_at", {"457370": 1000.0})
    monkeypatch.setattr(rx, "_now_ts", lambda: 1000.0 + 10*60)  # 10분 경과
    assert rx._in_cooldown("457370", cooldown_min=30) is True
    monkeypatch.setattr(rx, "_now_ts", lambda: 1000.0 + 31*60)  # 31분 경과
    assert rx._in_cooldown("457370", cooldown_min=30) is False


def test_execute_swaps_calls_sell_then_buy(monkeypatch):
    calls = []
    async def fake_sell(symbol, reason): calls.append(("sell", symbol)); return {"ok": True}
    async def fake_buy(symbol, candidate, price): calls.append(("buy", symbol)); return {"ok": True}
    monkeypatch.setattr(rx, "_sell_position", fake_sell)
    monkeypatch.setattr(rx, "_buy_candidate", fake_buy)
    monkeypatch.setattr(rx, "_in_cooldown", lambda s, cooldown_min: False)
    monkeypatch.setattr(rx, "_setting_bool", lambda k, d: True)
    monkeypatch.setattr(rx, "_setting_int", lambda k, d: 20)
    signals = [{"current_symbol": "457370", "new_symbol": "388790", "score_gap": 0.2}]
    cands = {"388790": {"symbol": "388790", "price": 7000}}
    out = asyncio.run(rx.execute_replacements(signals, cands))
    assert calls == [("sell", "457370"), ("buy", "388790")]
    assert out["executed"] == 1
