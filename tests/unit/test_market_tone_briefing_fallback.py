"""아침 경로 회귀: index-board 스크랩 실패(None) 시 결정론 중립 폴백으로 흐름이 유지되는지 검증.

스크래핑은 입력 보강일 뿐이므로 실패해도 regime 분석/저장 흐름이 깨지면 안 된다.
[LLM 제거 2026-08-05] 폴백은 더 이상 LLM이 아니라 결정론 중립(provider=none)이다. 네트워크 의존 0.
"""
import asyncio

from backend.config import settings
import backend.services.db as db_mod
import backend.services.engine.market_tone as mt
import backend.services.engine.index_board_scraper as scraper
import backend.services.engine.market_data_fetcher as mdf


def _iso_db(tmp_path, monkeypatch):
    p = tmp_path / "market_tone.sqlite3"
    monkeypatch.setattr(settings, "APP_DB_PATH", str(p))
    db_mod.initialize_database()


def test_morning_falls_back_when_scrape_returns_none(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)

    async def fake_scrape_morning():
        return None

    async def fake_overnight():
        return {"vix": {"price": 18.0, "change_pct": -1.0}, "ok": True}

    def fake_format(_data):
        return "[전날 밤 해외 시장 현황]\n  나스닥 +0.5%"

    monkeypatch.setattr(scraper, "scrape_morning", fake_scrape_morning)
    monkeypatch.setattr(mdf, "fetch_overnight_market_summary", fake_overnight)
    monkeypatch.setattr(mdf, "format_for_prompt", fake_format)

    # 스크랩 None → briefing_text 없음 → 결정론 중립 폴백(provider=none, tone=neutral).
    result = asyncio.run(mt.run_market_tone_analysis(trigger_source="auto_scheduler"))
    assert result["ok"] is True
    assert result["tone"] == "neutral"
    assert result["provider"] == "none"
