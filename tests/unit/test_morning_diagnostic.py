import backend.services.engine.morning_diagnostic as md


def _patch(monkeypatch, *, statuses, plan, assigns, engine_active):
    monkeypatch.setattr(md, "_latest_step_statuses", lambda _d: statuses)
    monkeypatch.setattr(md, "_active_plan", lambda _d: plan)
    monkeypatch.setattr(md, "_plan_assignment_count", lambda _p: assigns)
    monkeypatch.setattr(md, "_engine_is_active", lambda: engine_active)


_ALL_OK = {"S1": "success", "S2": "success", "S3": "success", "S4": "success", "S5": "success"}


def test_all_normal_no_issues(monkeypatch):
    _patch(monkeypatch, statuses=_ALL_OK, plan={"status": "active"}, assigns=3, engine_active=True)
    r = md.run_morning_diagnostic("2026-06-05")
    assert r["ok"] is True
    assert r["issues"] == []


def test_s4_failure_flagged_critical(monkeypatch):
    bad = dict(_ALL_OK); bad["S4"] = "failed"
    _patch(monkeypatch, statuses=bad, plan={"status": "active"}, assigns=3, engine_active=True)
    r = md.run_morning_diagnostic("2026-06-05")
    assert r["ok"] is False
    assert any(i["severity"] == "CRITICAL" and "S4" in i["title"] for i in r["issues"])


def test_no_plan_flagged(monkeypatch):
    _patch(monkeypatch, statuses=_ALL_OK, plan=None, assigns=0, engine_active=False)
    r = md.run_morning_diagnostic("2026-06-05")
    assert r["ok"] is False
    assert any("Daily Plan" in i["title"] or "플랜" in i["title"] for i in r["issues"])


def test_engine_inactive_with_plan_flagged(monkeypatch):
    _patch(monkeypatch, statuses=_ALL_OK, plan={"status": "active"}, assigns=3, engine_active=False)
    r = md.run_morning_diagnostic("2026-06-05")
    assert r["ok"] is False
    assert any("엔진" in i["title"] or "Engine" in i["title"] for i in r["issues"])


def test_missing_step_treated_as_not_success(monkeypatch):
    partial = {"S1": "success", "S2": "success"}  # S3/S4/S5 missing
    _patch(monkeypatch, statuses=partial, plan={"status": "active"}, assigns=3, engine_active=True)
    r = md.run_morning_diagnostic("2026-06-05")
    assert r["ok"] is False
    assert any("S4" in i["title"] for i in r["issues"])
