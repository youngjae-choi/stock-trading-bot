"""비거래일(주말·공휴일) 자동 잡 스킵 — morning_diagnostic 오경보 방지.

버그: _should_skip_auto_job이 schedule_skip_today 플래그만 봐서, 비거래일에
플래그가 false로 남으면 morning_diagnostic이 "S1~S5 미실행" CRITICAL 오경보를 냈다.
수정: 거래일을 직접(_non_trading_day_today) 확인해 비거래일이면 무조건 스킵.
"""

import backend.services.scheduler as sched


def test_skip_auto_job_on_non_trading_day(monkeypatch):
    monkeypatch.setattr(sched, "get_schedule_skip_today_status", lambda: {"skip": False})
    monkeypatch.setattr(sched, "_non_trading_day_today", lambda: "weekend")
    import backend.services.engine.pipeline_audit as pa
    monkeypatch.setattr(pa, "start_pipeline_run", lambda **k: "rid")
    monkeypatch.setattr(pa, "finish_pipeline_run", lambda **k: None)
    # 플래그는 false여도 비거래일이면 스킵
    assert sched._should_skip_auto_job("S6") is True


def test_no_skip_on_trading_day(monkeypatch):
    monkeypatch.setattr(sched, "get_schedule_skip_today_status", lambda: {"skip": False})
    monkeypatch.setattr(sched, "_non_trading_day_today", lambda: None)
    assert sched._should_skip_auto_job("S6") is False


def test_skip_when_flag_set_regardless(monkeypatch):
    monkeypatch.setattr(sched, "get_schedule_skip_today_status", lambda: {"skip": True})
    monkeypatch.setattr(sched, "_non_trading_day_today", lambda: None)
    import backend.services.engine.pipeline_audit as pa
    monkeypatch.setattr(pa, "start_pipeline_run", lambda **k: "rid")
    monkeypatch.setattr(pa, "finish_pipeline_run", lambda **k: None)
    assert sched._should_skip_auto_job("S6") is True
