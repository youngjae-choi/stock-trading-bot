"""collect_and_store_evening_briefing 오케스트레이션 단위 테스트 (네트워크/LLM 전부 mock)."""
import asyncio

from backend.config import settings
import backend.services.db as db_mod
import backend.services.engine.evening_briefing as eb
import backend.services.engine.index_board_scraper as scraper


def _iso_db(tmp_path, monkeypatch):
    p = tmp_path / "evening_collect.sqlite3"
    monkeypatch.setattr(settings, "APP_DB_PATH", str(p))
    db_mod.initialize_database()


def test_collect_scrape_failed_skips_store(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)

    async def fake_scrape_evening():
        return None

    monkeypatch.setattr(scraper, "scrape_evening", fake_scrape_evening)

    result = asyncio.run(eb.collect_and_store_evening_briefing("2026-06-12"))
    assert result["ok"] is False
    assert result["stored"] is False
    assert result["reason"] == "scrape_failed"
    assert eb.get_evening_briefing("2026-06-12") is None


def test_collect_success_stores(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)

    async def fake_scrape_evening():
        return {
            "text": "나스닥100 선물 +0.70%, VIX 급락. 위험선호 회복.",
            "type": "post",
            "market": "nasdaq",
            "generated_at": "2026-06-12T21:47:52Z",
        }

    async def fake_classify(text):
        return "risk_on"

    monkeypatch.setattr(scraper, "scrape_evening", fake_scrape_evening)
    monkeypatch.setattr(eb, "classify_sentiment", fake_classify)

    result = asyncio.run(eb.collect_and_store_evening_briefing("2026-06-12"))
    assert result["ok"] is True
    assert result["stored"] is True
    assert result["sentiment"] == "risk_on"

    row = eb.get_evening_briefing("2026-06-12")
    assert row is not None
    assert row["sentiment"] == "risk_on"
    assert row["source_ts"] == "2026-06-12T21:47:52Z"
    assert "나스닥100" in row["briefing_text"]
