"""진입 게이트 레짐 출처 = 장중 현재 SET (2026-09-30 전수점검) + 인버스 예산상한 순서 회귀.

사고1: 09-30 11:00 SET이 neutral로 전환됐는데 `_current_regime`이 아침 daily_context_snapshot(risk_on)만
읽어 VWAP 천장·ABCD·conviction 게이트가 종일 상승장 기준으로 돌았다(SET 손절·배포와 레짐 불일치).
사고2: 인버스1x 예산상한(_apply_crash_playbook_cap)이 신모델 사이징 **전**에 적용돼 무력화됐다.
"""
from __future__ import annotations

import inspect

import backend.services.engine.decision_engine as de_mod
import backend.services.engine.order_executor as oe_mod
from backend.services.db import get_connection


def _iso_db(monkeypatch, tmp_path):
    from backend.config import settings as cfg
    from backend.services.db import initialize_database
    monkeypatch.setattr(cfg, "APP_DB_PATH", str(tmp_path / "t.sqlite3"))
    initialize_database()


def _seed(today, snapshot_regime=None, app_regime=None):
    with get_connection() as conn:
        if snapshot_regime:
            conn.execute("INSERT INTO daily_context_snapshot (trade_date, regime, created_at) VALUES (?, ?, ?)",
                         (today, snapshot_regime, f"{today}T00:20:00Z"))
        if app_regime:
            conn.execute(
                "INSERT INTO regime_set_applications (id, trade_date, applied_at, set_id, regime_label, "
                "trigger, current_flag, created_at) VALUES ('a1', ?, ?, 'SET-NEUTRAL', ?, 'intraday', 1, ?)",
                (today, f"{today}T11:00:00+09:00", app_regime, f"{today}T02:00:00Z"))
        conn.commit()


def _engine(monkeypatch, source="intraday"):
    monkeypatch.setattr(de_mod, "_get_setting_str",
                        lambda k, d: source if k == "engine.gate_regime_source" else d)
    return de_mod.DecisionEngine.__new__(de_mod.DecisionEngine)


def test_intraday_set_overrides_morning_snapshot(monkeypatch, tmp_path):
    _iso_db(monkeypatch, tmp_path)
    today = de_mod._today_kst()
    _seed(today, snapshot_regime="risk_on", app_regime="neutral")
    assert _engine(monkeypatch)._current_regime() == "neutral"


def test_snapshot_rollback_switch(monkeypatch, tmp_path):
    _iso_db(monkeypatch, tmp_path)
    today = de_mod._today_kst()
    _seed(today, snapshot_regime="risk_on", app_regime="neutral")
    assert _engine(monkeypatch, "snapshot")._current_regime() == "risk_on"


def test_falls_back_to_snapshot_without_application(monkeypatch, tmp_path):
    _iso_db(monkeypatch, tmp_path)
    today = de_mod._today_kst()
    _seed(today, snapshot_regime="risk_off")
    assert _engine(monkeypatch)._current_regime() == "risk_off"


def test_none_when_nothing_recorded(monkeypatch, tmp_path):
    _iso_db(monkeypatch, tmp_path)
    assert _engine(monkeypatch)._current_regime() is None


def test_crash_cap_applied_after_final_sizing():
    """인버스 예산상한은 신모델 qty·프로필캡 확정 **후**에 적용돼야 한다(덮어쓰기 무력화 방지)."""
    src = inspect.getsource(oe_mod)
    cap = src.index("qty = self._apply_crash_playbook_cap(")
    assert src.index('qty = _nm["new_qty"]') < cap
    assert src.index("qty = _cap") < cap
