"""index-board 주력 regime (결정론적) 검증.

- 아침 경로 + 브리핑 스크랩 성공 → classify_regime_heuristic 사용 (provider=index-board).
- 브리핑 스크랩 실패(None) → 결정론적 중립 폴백(provider=none) + 운영 알림. LLM 미사용.

네트워크/알림 전부 mock — 네트워크 의존 0. DB는 격리 sqlite.
"""
import asyncio
from datetime import datetime, timezone

from backend.config import settings
import backend.services.db as db_mod
import backend.services.engine.market_tone as mt
import backend.services.engine.index_board_scraper as scraper
import backend.services.engine.market_data_fetcher as mdf
import backend.services.engine.alert_center as alert_center


def _fresh_iso():
    """현재시각(UTC ISO 'Z') — freshness 통과용 generated_at."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z"


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
    # KIS 야간선물/실시간 스냅샷 보강은 비치명 try/except 내부지만 네트워크 호출이므로 무력화.
    import backend.services.kis.domestic.service as kis_svc
    import backend.services.kis.domestic.universe_service as kis_uni

    async def _no_nf():
        return None

    async def _no_snap():
        return {"ok": False}

    monkeypatch.setattr(kis_svc, "get_kospi_night_futures", _no_nf, raising=False)
    monkeypatch.setattr(kis_uni, "fetch_intraday_kr_market_snapshot", _no_snap, raising=False)


def test_briefing_success_skips_llm(tmp_path, monkeypatch):
    """브리핑 스크랩 성공 시 결정론적 휴리스틱으로 처리(provider=index-board)."""
    _iso_db(tmp_path, monkeypatch)
    _common_mocks(monkeypatch)

    async def fake_scrape_morning():
        return {
            "text": "간밤 위험선호 회복, 강세 출발 예상, 반등 기대. 우호적 분위기.",
            "generated_at": _fresh_iso(),
        }

    monkeypatch.setattr(scraper, "scrape_morning", fake_scrape_morning)

    result = asyncio.run(mt.run_market_tone_analysis(trigger_source="auto_scheduler"))

    assert result["ok"] is True
    assert result["provider"] == "index-board"
    assert result["regime"] == "risk_on"
    assert result["tone"] == "positive"
    # morning_context 저장 확인 (provider=index-board)
    mc = mt.get_today_morning_context(result["trade_date"])
    assert mc is not None
    assert mc["provider"] == "index-board"
    assert mc["regime"] == "risk_on"


def test_scrape_none_falls_back_to_neutral(tmp_path, monkeypatch):
    """브리핑 스크랩 실패(None) 시 결정론적 중립 폴백(provider=none) + 운영 알림. LLM 미사용."""
    _iso_db(tmp_path, monkeypatch)
    _common_mocks(monkeypatch)

    fired = []

    def fake_create_alert(alert_type, title, severity="WARNING", detail="", trade_date=None):
        fired.append({"alert_type": alert_type, "title": title, "severity": severity, "detail": detail})
        return {"id": "x"}

    async def fake_scrape_morning():
        return None

    monkeypatch.setattr(scraper, "scrape_morning", fake_scrape_morning)
    monkeypatch.setattr(alert_center, "create_alert", fake_create_alert)

    result = asyncio.run(mt.run_market_tone_analysis(trigger_source="auto_scheduler"))

    assert result["ok"] is True
    # 결정론적 중립 폴백: provider='none', 중립 regime/tone.
    assert result["provider"] == "none"
    assert result["tone"] == "neutral"
    assert result["regime"] == "neutral"
    assert result["risk_level"] == "normal"
    assert result["confidence"] == 0.0
    # index-board 미수신 운영 알림 1회.
    assert len(fired) == 1
    assert fired[0]["alert_type"] == "ops_watch"
    assert fired[0]["severity"] == "WARNING"
    assert "미수신" in fired[0]["title"]
    assert "reason=missing" in fired[0]["detail"]
