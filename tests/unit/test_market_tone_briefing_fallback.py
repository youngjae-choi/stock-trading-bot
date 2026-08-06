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


def test_morning_scrape_none_keeps_prior_regime(tmp_path, monkeypatch):
    """데이터 부재 시 오늘 직전 레짐이 있으면 중립으로 덮어쓰지 않고 유지(carry-forward).

    실사례: 8/6 아침 negative(-4.9% 폭락일)가 장중 index-board 부재로 neutral로 드리프트하던 문제.
    """
    import uuid
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from backend.services.db import get_connection

    _iso_db(tmp_path, monkeypatch)
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")

    # 오늘 직전 비중립(negative) 톤을 미리 심는다. (테이블은 lazy 생성이라 보장)
    mt._ensure_table()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO market_tone_results (id, trade_date, tone, provider, created_at) VALUES (?,?,?,?,?)",
            (str(uuid.uuid4()), today, "negative", "index-board", today + "T00:01:00Z"),
        )

    async def fake_scrape_morning():
        return None

    async def fake_overnight():
        return {"vix": {"price": 18.0, "change_pct": -1.0}, "ok": True}

    def fake_format(_data):
        return "[전날 밤 해외 시장 현황]\n  나스닥 -0.5%"

    monkeypatch.setattr(scraper, "scrape_morning", fake_scrape_morning)
    monkeypatch.setattr(mdf, "fetch_overnight_market_summary", fake_overnight)
    monkeypatch.setattr(mdf, "format_for_prompt", fake_format)

    result = asyncio.run(mt.run_market_tone_analysis(trigger_source="auto_scheduler"))
    # 직전 레짐 유지 — 중립으로 덮어쓰지 않고 skip.
    assert result.get("provider") == "carry-forward"
    assert result.get("skipped") is True
    # 새 중립 행을 쓰지 않았다 — 여전히 1행(negative)만.
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT tone FROM market_tone_results WHERE trade_date=?", (today,)
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "negative"
