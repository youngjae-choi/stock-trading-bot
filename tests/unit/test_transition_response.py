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
