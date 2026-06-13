"""장후 브리핑 저장/조회 + 감성 분류 단위 테스트 (격리 DB)."""
import asyncio

import pytest

from backend.config import settings
import backend.services.db as db_mod
import backend.services.engine.evening_briefing as eb
import backend.services.engine.llm_router as llm_router


def _iso_db(tmp_path, monkeypatch):
    p = tmp_path / "evening_briefing.sqlite3"
    monkeypatch.setattr(settings, "APP_DB_PATH", str(p))
    db_mod.initialize_database()


def test_save_and_get_evening_briefing(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)
    eb.save_evening_briefing(
        "2026-06-12", "위험선호 회복", "risk_on", {"vix": 19.25}, "2026-06-12T21:47:00"
    )
    row = eb.get_evening_briefing("2026-06-12")
    assert row is not None
    assert row["sentiment"] == "risk_on"
    assert row["market_data"]["vix"] == 19.25
    assert row["briefing_text"] == "위험선호 회복"
    assert row["source_ts"] == "2026-06-12T21:47:00"


def test_get_missing_returns_none(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)
    assert eb.get_evening_briefing("1999-01-01") is None


def test_save_replaces_same_date(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)
    eb.save_evening_briefing("2026-06-12", "a", "neutral")
    eb.save_evening_briefing("2026-06-12", "b", "risk_off")
    row = eb.get_evening_briefing("2026-06-12")
    assert row["briefing_text"] == "b"
    assert row["sentiment"] == "risk_off"


def test_get_range_returns_recent_first(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)
    eb.save_evening_briefing("2026-06-10", "d10", "neutral")
    eb.save_evening_briefing("2026-06-11", "d11", "risk_on")
    eb.save_evening_briefing("2026-06-12", "d12", "risk_off")
    rows = eb.get_evening_briefings_range("2026-06-10", "2026-06-12")
    assert [r["trade_date"] for r in rows] == ["2026-06-12", "2026-06-11", "2026-06-10"]


def test_classify_sentiment_parses_llm_keyword(tmp_path, monkeypatch):
    async def fake_call_llm(prompt, task_name=""):
        return {"ok": True, "provider": "test", "raw": "risk_on", "tried": ["test"]}

    monkeypatch.setattr(llm_router, "call_llm", fake_call_llm)
    result = asyncio.run(eb.classify_sentiment("위험선호 강하게 회복"))
    assert result == "risk_on"


def test_classify_sentiment_extracts_from_sentence(tmp_path, monkeypatch):
    async def fake_call_llm(prompt, task_name=""):
        return {"ok": True, "provider": "test", "raw": "판단: risk_off 입니다.", "tried": ["test"]}

    monkeypatch.setattr(llm_router, "call_llm", fake_call_llm)
    result = asyncio.run(eb.classify_sentiment("위험회피 심리 확산"))
    assert result == "risk_off"


def test_classify_sentiment_fallback_neutral_on_failure(tmp_path, monkeypatch):
    async def fake_call_llm(prompt, task_name=""):
        return {"ok": False, "provider": "none", "raw": "", "tried": []}

    monkeypatch.setattr(llm_router, "call_llm", fake_call_llm)
    result = asyncio.run(eb.classify_sentiment("어떤 텍스트"))
    assert result == "neutral"


def test_classify_sentiment_fallback_neutral_on_unknown(tmp_path, monkeypatch):
    async def fake_call_llm(prompt, task_name=""):
        return {"ok": True, "provider": "test", "raw": "모르겠음", "tried": ["test"]}

    monkeypatch.setattr(llm_router, "call_llm", fake_call_llm)
    result = asyncio.run(eb.classify_sentiment("애매한 텍스트"))
    assert result == "neutral"
