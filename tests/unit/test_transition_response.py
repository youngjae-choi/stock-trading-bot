"""엔진② 전환 대응 — get_current_transition 신선도/상태 판정 검증.

하락전환 매수중단 게이트가 읽는 상태. 오래된 상태(틱 끊김)는 무시(오작동 방지).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import backend.services.engine.intraday_regime_monitor as irm


def _mock_settings(monkeypatch, trans, at_iso, win=60):
    cfg = {
        "regime.current_transition": trans,
        "regime.current_transition_at": at_iso,
        "regime.transition_window_min": win,
    }
    monkeypatch.setattr("backend.services.settings_store.get_setting",
                        lambda k, d=None: cfg.get(k, d))


def _now_iso(minutes_ago=0):
    return (datetime.now(ZoneInfo("Asia/Seoul")) - timedelta(minutes=minutes_ago)).isoformat()


def test_fresh_down_transition_returned(monkeypatch):
    _mock_settings(monkeypatch, "down_transition", _now_iso(5))
    assert irm.get_current_transition() == "down_transition"


def test_none_when_no_transition(monkeypatch):
    _mock_settings(monkeypatch, "none", _now_iso(5))
    assert irm.get_current_transition() is None


def test_stale_transition_ignored(monkeypatch):
    # 마지막 갱신이 window+15분보다 오래됨(틱 끊김) → 신선하지 않음 → None
    _mock_settings(monkeypatch, "down_transition", _now_iso(200), win=60)
    assert irm.get_current_transition() is None


def test_up_transition_returned(monkeypatch):
    _mock_settings(monkeypatch, "up_transition", _now_iso(1))
    assert irm.get_current_transition() == "up_transition"


def test_missing_state_returns_none(monkeypatch):
    monkeypatch.setattr("backend.services.settings_store.get_setting",
                        lambda k, d=None: d)
    assert irm.get_current_transition() is None


# ---------------------------------------------------------------------------
# 상승전환 재개 래치 (엔진② inc4, 2026-08-23)
# ---------------------------------------------------------------------------

def _mock_suspend(monkeypatch, suspended, at_iso, win=60):
    cfg = {
        "regime.entry_suspended": suspended,
        "regime.entry_suspended_at": at_iso,
        "regime.transition_window_min": win,
    }
    monkeypatch.setattr("backend.services.settings_store.get_setting",
                        lambda k, d=None: cfg.get(k, d))


def test_latch_semantics_pure():
    """래치 코어: down→중단(True), up→재개(False), None→유지(None)."""
    assert irm._latch_from_transition("down_transition") is True
    assert irm._latch_from_transition("up_transition") is False
    assert irm._latch_from_transition(None) is None
    assert irm._latch_from_transition("none") is None


def test_entry_suspended_true_when_fresh(monkeypatch):
    _mock_suspend(monkeypatch, "true", _now_iso(5))
    assert irm.get_entry_suspended() is True


def test_entry_suspended_bool_true(monkeypatch):
    _mock_suspend(monkeypatch, True, _now_iso(5))
    assert irm.get_entry_suspended() is True


def test_entry_suspended_false_when_released(monkeypatch):
    """up_transition으로 해제된 상태 → 매수 재개."""
    _mock_suspend(monkeypatch, "false", _now_iso(5))
    assert irm.get_entry_suspended() is False


def test_entry_suspended_stale_auto_release(monkeypatch):
    """래치 갱신이 window+15분 초과(틱 끊김·익일) → stale 자동해제(장초 차단 방지)."""
    _mock_suspend(monkeypatch, "true", _now_iso(200), win=60)
    assert irm.get_entry_suspended() is False


def test_entry_suspended_missing_false(monkeypatch):
    monkeypatch.setattr("backend.services.settings_store.get_setting",
                        lambda k, d=None: d)
    assert irm.get_entry_suspended() is False
