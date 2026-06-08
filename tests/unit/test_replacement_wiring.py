import asyncio
import backend.services.engine.decision_engine as de


def test_refresh_triggers_execute_when_signals(monkeypatch):
    captured = {}
    async def fake_eval(**kw): return {"ok": True, "created": 1, "signals": [{"current_symbol":"A","new_symbol":"B","score_gap":0.2}]}
    async def fake_exec(signals): captured["signals"] = signals; return {"ok": True, "executed": 1}
    monkeypatch.setattr("backend.services.engine.replacement_signal.evaluate_replacement_signals", fake_eval)
    monkeypatch.setattr("backend.services.engine.replacement_executor.execute_replacements", fake_exec)
    # _maybe_execute_replacements 는 signals 있으면 execute_replacements 호출
    out = asyncio.run(de._maybe_execute_replacements({"ok": True, "signals": [{"current_symbol":"A","new_symbol":"B","score_gap":0.2}]}))
    assert captured["signals"][0]["new_symbol"] == "B"
    assert out["executed"] == 1
