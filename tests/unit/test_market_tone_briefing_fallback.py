"""아침 경로 회귀: index-board 스크랩 실패(None) 시 기존 LLM 경로로 폴백하는지 검증.

스크래핑은 입력 보강일 뿐이므로 실패해도 regime 분석/저장 흐름이 깨지면 안 된다.
네트워크/LLM은 전부 mock — 네트워크 의존 0.
"""
import asyncio

from backend.config import settings
import backend.services.db as db_mod
import backend.services.engine.market_tone as mt
import backend.services.engine.index_board_scraper as scraper
import backend.services.engine.market_data_fetcher as mdf
import backend.services.engine.llm_router as llm_router


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

    async def fake_call_llm(prompt, task_name=""):
        # 스크랩 텍스트가 없으므로 보강 문구가 프롬프트에 없어야 한다(폴백 확인).
        assert "외부 AI 시황 브리핑" not in prompt
        return {
            "ok": True,
            "provider": "test",
            "raw": '{"tone":"neutral","confidence":0.5,"summary":"평이",'
            '"regime":"neutral","risk_level":"normal"}',
            "tried": ["test"],
        }

    monkeypatch.setattr(scraper, "scrape_morning", fake_scrape_morning)
    monkeypatch.setattr(mdf, "fetch_overnight_market_summary", fake_overnight)
    monkeypatch.setattr(mdf, "format_for_prompt", fake_format)
    monkeypatch.setattr(llm_router, "call_llm", fake_call_llm)

    result = asyncio.run(mt.run_market_tone_analysis(trigger_source="auto_scheduler"))
    assert result["ok"] is True
    assert result["tone"] == "neutral"
