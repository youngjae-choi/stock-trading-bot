"""GET /api/v1/evening-briefing/today — 장후 브리핑 조회 API 테스트.

운영 DB 미접촉: settings.APP_DB_PATH를 임시 파일로 monkeypatch.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

import backend.main as main_mod
from backend.config import settings
from backend.services import db as db_mod
from backend.services.engine.evening_briefing import save_evening_briefing

client = TestClient(main_mod.app)


def _isolated_db(tmp_path, monkeypatch):
    p = tmp_path / "evening_briefing_api.sqlite3"
    monkeypatch.setattr(settings, "APP_DB_PATH", str(p))
    db_mod.initialize_database()


def _today_kst() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


def test_evening_today_empty_returns_ok(tmp_path, monkeypatch):
    _isolated_db(tmp_path, monkeypatch)
    r = client.get("/api/v1/evening-briefing/today")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["payload"] is None
    assert body["is_today"] is False


def test_evening_today_returns_saved(tmp_path, monkeypatch):
    _isolated_db(tmp_path, monkeypatch)
    today = _today_kst()
    save_evening_briefing(
        today, "간밤 미국 증시 위험선호 회복", "risk_on", {"vix": 18.5}, "2026-06-12T21:47:00"
    )
    r = client.get("/api/v1/evening-briefing/today")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["payload"] is not None
    assert body["payload"]["sentiment"] == "risk_on"
    assert body["payload"]["trade_date"] == today
    assert body["is_today"] is True


def test_evening_today_fallback_to_recent(tmp_path, monkeypatch):
    """오늘 데이터가 없으면 직전 7일 최신 1건으로 폴백, is_today=False."""
    _isolated_db(tmp_path, monkeypatch)
    from datetime import timedelta

    yesterday = (
        datetime.now(ZoneInfo("Asia/Seoul")) - timedelta(days=1)
    ).strftime("%Y-%m-%d")
    save_evening_briefing(yesterday, "전날 장후 위험회피", "risk_off")
    r = client.get("/api/v1/evening-briefing/today")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["payload"] is not None
    assert body["payload"]["sentiment"] == "risk_off"
    assert body["is_today"] is False


def test_evening_range_returns_list(tmp_path, monkeypatch):
    _isolated_db(tmp_path, monkeypatch)
    save_evening_briefing("2026-06-10", "d10", "neutral")
    save_evening_briefing("2026-06-11", "d11", "risk_on")
    r = client.get("/api/v1/evening-briefing/today?start=2026-06-10&end=2026-06-11")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert isinstance(body["payload"], list)
    assert [row["trade_date"] for row in body["payload"]] == ["2026-06-11", "2026-06-10"]
