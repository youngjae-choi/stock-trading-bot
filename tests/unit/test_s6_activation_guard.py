"""S6 활성화 — prep 완료 前 'no active Daily Plan' 오탐 알림 억제 (2026-09-18).

워치독(2분)·재기동이 prep(≈09:05) 완료 前(09:00~09:04)·야간(재부팅 직후 02:05)에 S6 활성화를
시도하며 "S6 차단 ❌" 텔레그램을 도배하던 오탐. prep 예정시각+5분 유예 前엔 blocked 감사(→알림)를
기록하지 않고, 이후에만 진짜 문제로 보고한다.
"""
from __future__ import annotations

import asyncio
from datetime import datetime as _dt
from zoneinfo import ZoneInfo

import backend.services.scheduler as sch
import backend.services.settings_store as ss


def _run_job6_no_plan(monkeypatch, hh: int, mm: int):
    """활성 plan 없음 상태에서 job_decision_engine_start를 hh:mm(KST)에 실행 → blocked 감사 호출 목록."""
    audits: list = []
    monkeypatch.setattr(sch, "_should_skip_auto_job", lambda step: False)
    monkeypatch.setattr(sch, "_get_active_daily_plan_for_s6", lambda: None)
    monkeypatch.setattr(sch, "_get_latest_daily_plan_context_for_s6",
                        lambda: {"id": "x", "status": "none", "validation_summary": {}})
    monkeypatch.setattr(sch, "_get_recent_pre_s6_audit_context", lambda: {})
    monkeypatch.setattr(sch, "_audit_skipped_step", lambda *a, **k: audits.append(a))
    monkeypatch.setattr(ss, "get_setting",
                        lambda k, d=None: "09:05" if k == "schedule_trade_prep_time" else d)

    class _FakeDatetime:
        @staticmethod
        def now(tz=None):
            return _dt(2026, 9, 18, hh, mm, tzinfo=ZoneInfo("Asia/Seoul"))
    monkeypatch.setattr(sch, "datetime", _FakeDatetime)
    asyncio.run(sch.job_decision_engine_start())
    return audits


def test_s6_no_plan_before_prep_suppressed(monkeypatch):
    """09:02 (prep 09:05 前) — blocked 감사/알림 없음(오탐 억제)."""
    assert _run_job6_no_plan(monkeypatch, 9, 2) == []


def test_s6_no_plan_night_after_reboot_suppressed(monkeypatch):
    """02:05 (재부팅 직후 야간) — blocked 감사/알림 없음."""
    assert _run_job6_no_plan(monkeypatch, 2, 5) == []


def test_s6_no_plan_after_prep_grace_alerts(monkeypatch):
    """09:20 (prep+5=09:10 後) — plan 없으면 진짜 문제 → blocked 감사 기록(알림)."""
    audits = _run_job6_no_plan(monkeypatch, 9, 20)
    assert len(audits) == 1 and audits[0][0] == "S6"


def test_s6_no_plan_exactly_at_grace_boundary(monkeypatch):
    """09:10 (=prep 09:05+5) 경계 — 유예 끝 → 알림."""
    audits = _run_job6_no_plan(monkeypatch, 9, 10)
    assert len(audits) == 1
