import asyncio
import backend.services.scheduler as sched


def test_job_skips_non_trading_day(monkeypatch):
    monkeypatch.setattr(sched, "_non_trading_day_today", lambda: "weekend")
    called = {"n": 0}

    async def fake_run():
        called["n"] += 1
        return {"ok": True}

    import backend.services.engine.momentum_scanner as ms
    monkeypatch.setattr(ms, "run_momentum_scan", fake_run)
    asyncio.run(sched.job_momentum_scan())
    assert called["n"] == 0  # 비거래일 스킵


def test_job_runs_on_trading_day(monkeypatch):
    monkeypatch.setattr(sched, "_non_trading_day_today", lambda: None)
    called = {"n": 0}

    async def fake_run():
        called["n"] += 1
        return {"ok": True, "added": 0}

    import backend.services.engine.momentum_scanner as ms
    monkeypatch.setattr(ms, "run_momentum_scan", fake_run)
    asyncio.run(sched.job_momentum_scan())
    assert called["n"] == 1
