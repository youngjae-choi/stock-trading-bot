"""시장 톤 슬롯 추이(get_today_tone_slots) — Plan&Funnel ① 환경 장중 변화 표시용 (2026-06-21).

순수 읽기: market_tone_results의 당일 슬롯을 시각 오름차순으로 반환.
"""

import tempfile

import pytest


@pytest.fixture()
def fresh_db(monkeypatch):
    from backend.config import settings as cfg
    from backend.services.db import initialize_database

    tmp = tempfile.mktemp(suffix=".sqlite3")
    monkeypatch.setattr(cfg, "APP_DB_PATH", tmp)
    initialize_database()
    return tmp


def test_tone_slots_empty_day(fresh_db):
    from backend.services.engine.market_tone import get_today_tone_slots
    assert get_today_tone_slots("2026-06-21") == []


def test_tone_slots_ordered_ascending(fresh_db):
    from backend.services.engine.market_tone import _ensure_table, get_today_tone_slots
    from backend.services.db import get_connection

    _ensure_table()
    with get_connection() as c:
        # 일부러 역순 삽입 — 반환은 시각 오름차순이어야 함
        c.execute("INSERT INTO market_tone_results (trade_date, tone, confidence, created_at) VALUES (?,?,?,?)",
                  ("2026-06-19", "mixed", 0.70, "2026-06-19T02:30:00Z"))
        c.execute("INSERT INTO market_tone_results (trade_date, tone, confidence, created_at) VALUES (?,?,?,?)",
                  ("2026-06-19", "positive", 1.0, "2026-06-19T00:01:00Z"))
        c.execute("INSERT INTO market_tone_results (trade_date, tone, confidence, created_at) VALUES (?,?,?,?)",
                  ("2026-06-19", "positive", 0.72, "2026-06-19T01:30:00Z"))

    slots = get_today_tone_slots("2026-06-19")
    assert [s["tone"] for s in slots] == ["positive", "positive", "mixed"]
    assert slots[0]["created_at"] < slots[-1]["created_at"]
    assert slots[-1]["confidence"] == 0.70
