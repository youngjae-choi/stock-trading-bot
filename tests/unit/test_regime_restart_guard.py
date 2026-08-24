"""S6 activate 재기동 되돌림 방지 (2026-08-24) — 장중 레짐을 아침 regime으로 덮지 않는다.

재기동 시 _save_daily_context_snapshot이 아침 regime(neutral·kospi=None)으로 match_set을 호출해
폭락장 risk_off를 morning-neutral로 되돌리던 버그. 이미 intraday 적용이 있으면 스킵.
"""
import backend.services.engine.decision_context as dc
import backend.services.regime_set_service as rss


def _iso_db(monkeypatch, tmp_path):
    from backend.config import settings as cfg
    from backend.services.db import initialize_database
    monkeypatch.setattr(cfg, "APP_DB_PATH", str(tmp_path / "t.sqlite3"))
    initialize_database()


def test_skip_morning_reapply_when_intraday_exists(monkeypatch, tmp_path):
    """이미 장중(intraday) 레짐이 있으면 아침 regime 재적용을 스킵한다(restart 되돌림 방지)."""
    _iso_db(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(rss, "match_set", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(rss, "get_today_application",
                        lambda d: {"trigger": "intraday", "regime_label": "risk_off"})
    dc._save_daily_context_snapshot("2026-08-24")
    assert calls == []  # match_set 미호출 = 장중 레짐 유지


def test_apply_morning_when_no_intraday(monkeypatch, tmp_path):
    """장중 적용이 없으면(아침 최초 활성) 아침 regime을 적용한다."""
    _iso_db(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(rss, "match_set", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(rss, "get_today_application", lambda d: {"trigger": "morning"})
    dc._save_daily_context_snapshot("2026-08-24")
    assert len(calls) == 1  # 아침 regime 적용됨
