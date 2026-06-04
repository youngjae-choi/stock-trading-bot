import asyncio
import backend.services.scheduler as sched


def test_should_skip_s2_when_tone_exists(monkeypatch):
    monkeypatch.setattr(sched, "get_today_market_tone", lambda _d: {"tone": "mixed"}, raising=False)
    assert sched._s2_already_done("2099-02-01") is True


def test_should_not_skip_s2_when_no_tone(monkeypatch):
    monkeypatch.setattr(sched, "get_today_market_tone", lambda _d: None, raising=False)
    assert sched._s2_already_done("2099-02-02") is False


def test_premarket_tone_job_runs_analysis(monkeypatch):
    calls = {}

    async def fake_token():
        calls["token"] = True
        return {"token_status": "success"}

    async def fake_tone(trigger_source="auto_scheduler"):
        calls["tone_source"] = trigger_source
        return {"ok": True, "tone": "positive"}

    monkeypatch.setattr(sched, "job_refresh_kis_token", fake_token, raising=False)
    monkeypatch.setattr(sched, "run_market_tone_analysis", fake_tone, raising=False)
    monkeypatch.setattr(sched, "_today_kst", lambda: "2099-02-03", raising=False)
    asyncio.run(sched.job_premarket_market_tone())
    assert calls.get("token") is True
    assert calls.get("tone_source") == "auto_scheduler"
