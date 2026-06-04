import asyncio
import backend.services.scheduler as sched


def _setup(monkeypatch, *, halt, active, should_be, plan, s6_today, in_window):
    monkeypatch.setattr(sched, "_is_emergency_halt_active", lambda: halt)
    monkeypatch.setattr(sched, "_get_engine_should_be_active", lambda: should_be)
    monkeypatch.setattr(sched, "_get_active_daily_plan_for_s6", lambda: ({"id": "p"} if plan else None))
    monkeypatch.setattr(sched, "_s6_activated_today", lambda: s6_today)
    monkeypatch.setattr(sched, "_within_late_plan_window", lambda: in_window)
    calls = {"start": 0}
    async def fake_start():
        calls["start"] += 1
    monkeypatch.setattr(sched, "job_decision_engine_start", fake_start)
    class FakeEngine:
        def is_active(self):
            return active
    import backend.services.engine.decision_engine as de
    monkeypatch.setattr(de, "decision_engine", FakeEngine())
    return calls


def test_late_plan_activates_when_blocked_then_plan_appears(monkeypatch):
    # 오전 차단(should_be=False) + 장중 활성 플랜 + 금일 S6 미활성 + 윈도우 내 → 활성화
    calls = _setup(monkeypatch, halt=False, active=False, should_be=False, plan=True, s6_today=False, in_window=True)
    asyncio.run(sched.job_decision_engine_watchdog())
    assert calls["start"] == 1


def test_no_late_activation_outside_window(monkeypatch):
    calls = _setup(monkeypatch, halt=False, active=False, should_be=False, plan=True, s6_today=False, in_window=False)
    asyncio.run(sched.job_decision_engine_watchdog())
    assert calls["start"] == 0


def test_no_late_activation_when_s6_already_succeeded_today(monkeypatch):
    # 금일 S6 성공 이력 있음(=수동 정지 등) → 자가활성화 안 함(운영자 의도 존중)
    calls = _setup(monkeypatch, halt=False, active=False, should_be=False, plan=True, s6_today=True, in_window=True)
    asyncio.run(sched.job_decision_engine_watchdog())
    assert calls["start"] == 0


def test_no_late_activation_without_plan(monkeypatch):
    calls = _setup(monkeypatch, halt=False, active=False, should_be=False, plan=False, s6_today=False, in_window=True)
    asyncio.run(sched.job_decision_engine_watchdog())
    assert calls["start"] == 0


def test_emergency_halt_respected(monkeypatch):
    calls = _setup(monkeypatch, halt=True, active=False, should_be=False, plan=True, s6_today=False, in_window=True)
    asyncio.run(sched.job_decision_engine_watchdog())
    assert calls["start"] == 0


def test_existing_reactivation_still_works(monkeypatch):
    # 기존 동작: should_be=True인데 꺼짐 → 재활성화
    calls = _setup(monkeypatch, halt=False, active=False, should_be=True, plan=True, s6_today=True, in_window=False)
    asyncio.run(sched.job_decision_engine_watchdog())
    assert calls["start"] == 1


def test_no_action_when_already_active(monkeypatch):
    calls = _setup(monkeypatch, halt=False, active=True, should_be=True, plan=True, s6_today=False, in_window=True)
    asyncio.run(sched.job_decision_engine_watchdog())
    assert calls["start"] == 0
