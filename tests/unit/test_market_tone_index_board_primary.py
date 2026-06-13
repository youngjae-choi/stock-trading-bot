"""index-board 주력 regime (하이브리드) 검증.

- 아침 경로 + 브리핑 스크랩 성공 → classify_regime_heuristic 사용, call_llm 미호출(Opus SKIP).
- 브리핑 스크랩 실패(None) → 기존 call_llm 풀분석 경로로 폴백.

네트워크/LLM 전부 mock — 네트워크 의존 0. DB는 격리 sqlite.
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


def _common_mocks(monkeypatch):
    async def fake_overnight():
        return {"vix": {"price": 18.0, "change_pct": -1.0}, "ok": True}

    def fake_format(_data):
        return "[전날 밤 해외 시장 현황]\n  나스닥 +0.5%"

    monkeypatch.setattr(mdf, "fetch_overnight_market_summary", fake_overnight)
    monkeypatch.setattr(mdf, "format_for_prompt", fake_format)


def test_briefing_success_skips_llm(tmp_path, monkeypatch):
    """브리핑 스크랩 성공 시 휴리스틱으로 처리, call_llm은 절대 호출되지 않아야 한다."""
    _iso_db(tmp_path, monkeypatch)
    _common_mocks(monkeypatch)

    calls = {"llm": 0}

    async def fake_scrape_morning():
        return {
            "text": "간밤 위험선호 회복, 강세 출발 예상, 반등 기대. 우호적 분위기.",
            "generated_at": "2026-06-13T07:30:00Z",
        }

    async def fake_call_llm(prompt, task_name=""):
        calls["llm"] += 1
        raise AssertionError("call_llm must NOT be invoked when briefing scraped")

    monkeypatch.setattr(scraper, "scrape_morning", fake_scrape_morning)
    monkeypatch.setattr(llm_router, "call_llm", fake_call_llm)

    result = asyncio.run(mt.run_market_tone_analysis(trigger_source="auto_scheduler"))

    assert calls["llm"] == 0
    assert result["ok"] is True
    assert result["provider"] == "index-board"
    assert result["regime"] == "risk_on"
    assert result["tone"] == "positive"
    # morning_context 저장 확인 (provider=index-board)
    mc = mt.get_today_morning_context(result["trade_date"])
    assert mc is not None
    assert mc["provider"] == "index-board"
    assert mc["regime"] == "risk_on"


def test_scrape_none_falls_back_to_llm(tmp_path, monkeypatch):
    """브리핑 스크랩 실패(None) 시 기존 call_llm 풀분석 경로를 타야 한다."""
    _iso_db(tmp_path, monkeypatch)
    _common_mocks(monkeypatch)

    calls = {"llm": 0}

    async def fake_scrape_morning():
        return None

    async def fake_call_llm(prompt, task_name=""):
        calls["llm"] += 1
        assert "외부 AI 시황 브리핑" not in prompt
        return {
            "ok": True,
            "provider": "test",
            "raw": '{"tone":"neutral","confidence":0.5,"summary":"평이",'
            '"regime":"neutral","risk_level":"normal"}',
            "tried": ["test"],
        }

    monkeypatch.setattr(scraper, "scrape_morning", fake_scrape_morning)
    monkeypatch.setattr(llm_router, "call_llm", fake_call_llm)

    result = asyncio.run(mt.run_market_tone_analysis(trigger_source="auto_scheduler"))

    assert calls["llm"] == 1
    assert result["ok"] is True
    assert result["provider"] == "test"
    assert result["tone"] == "neutral"
