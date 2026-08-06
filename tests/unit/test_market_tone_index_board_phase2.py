"""Phase 2 — index-board 시황 단일출처 검증.

- 장중(intraday)도 index-board(scrape_intraday/regular)를 주력으로 사용 → Opus SKIP.
- 스크랩 실패(None) → provider='none'(중립 폴백), stale → provider='heuristic-stale' + 운영 알림 1회. LLM 미사용.
- classify_regime_heuristic의 numbers 결합(객관 수치) 동작 및 하위호환.
- parsed_numbers가 market_tone_results에 저장되는지.

네트워크/LLM/알림 전부 mock — 네트워크 의존 0. DB는 격리 sqlite.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone

from backend.config import settings
import backend.services.db as db_mod
import backend.services.engine.market_tone as mt
import backend.services.engine.index_board_scraper as scraper
import backend.services.engine.market_data_fetcher as mdf
import backend.services.engine.alert_center as alert_center


def _iso_db(tmp_path, monkeypatch):
    p = tmp_path / "market_tone_p2.sqlite3"
    monkeypatch.setattr(settings, "APP_DB_PATH", str(p))
    db_mod.initialize_database()


def _fresh_iso(minutes_ago: float = 0.0):
    t = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return t.strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def _common_mocks(monkeypatch):
    async def fake_overnight():
        return {"vix": {"price": 18.0, "change_pct": -1.0}, "ok": True}

    def fake_format(_data):
        return "[전날 밤 해외 시장 현황]\n  나스닥 +0.5%"

    monkeypatch.setattr(mdf, "fetch_overnight_market_summary", fake_overnight)
    monkeypatch.setattr(mdf, "format_for_prompt", fake_format)

    import backend.services.kis.domestic.service as kis_svc
    import backend.services.kis.domestic.universe_service as kis_uni

    async def _no_nf():
        return None

    async def _no_snap():
        return {"ok": False}

    monkeypatch.setattr(kis_svc, "get_kospi_night_futures", _no_nf, raising=False)
    monkeypatch.setattr(kis_uni, "fetch_intraday_kr_market_snapshot", _no_snap, raising=False)


def _capture_alerts(monkeypatch):
    fired = []

    def fake_create_alert(alert_type, title, severity="WARNING", detail="", trade_date=None):
        fired.append({"alert_type": alert_type, "title": title, "severity": severity, "detail": detail})
        return {"id": "x"}

    monkeypatch.setattr(alert_center, "create_alert", fake_create_alert)
    return fired


# ─────────────────────────────────────────────────────────────────────────────
# classify_regime_heuristic — numbers 결합
# ─────────────────────────────────────────────────────────────────────────────

def test_classify_numbers_none_unchanged():
    """numbers=None이면 기존 키워드-only 동작과 동일(하위호환)."""
    text = "약세 하락 부진 경계 위축"  # off 키워드 다수 → risk_off
    base = mt.classify_regime_heuristic(text)
    with_none = mt.classify_regime_heuristic(text, market_data=None, numbers=None)
    assert base["regime"] == with_none["regime"] == "risk_off"
    assert base["numbers"] == {}


def test_classify_extreme_fear_and_negative_futures_risk_off_higher_conf():
    """극단 공포 + 강한 음의 선물 → risk_off, 키워드와 코로보레이트 시 confidence 상승."""
    text = "약세 하락 우려"  # off=2 → net=-2 (risk_off lean)
    numbers = {
        "vix": 22.0,
        "fear_greed": 18,  # extreme fear
        "kospi200_futures_pct": -1.7,  # strongly negative
    }
    weak = mt.classify_regime_heuristic(text)  # numbers 없는 동일 텍스트
    res = mt.classify_regime_heuristic(text, numbers=numbers)
    assert res["regime"] == "risk_off"
    assert res["risk_level"] == "normal"  # 22 → normal
    assert res["confidence"] >= weak["confidence"]  # 코로보레이트로 가산
    assert res["numbers"]["fear_greed"] == 18


def test_classify_vix_high_risk_level():
    """numbers vix>30 → risk_level high."""
    res = mt.classify_regime_heuristic("혼조 변동성", numbers={"vix": 34.0})
    assert res["risk_level"] == "high"


def test_classify_vix_low_from_numbers():
    res = mt.classify_regime_heuristic("평이", numbers={"vix": 15.0})
    assert res["risk_level"] == "low"


def test_classify_numbers_override_neutral_keywords():
    """키워드가 중립이어도 극단 탐욕+강한 양의 선물이면 risk_on으로 끌어올림."""
    text = "특이사항 없음"  # 키워드 net=0
    numbers = {"fear_greed": 82, "kospi200_futures_pct": 1.5}  # extreme greed + strong up
    res = mt.classify_regime_heuristic(text, numbers=numbers)
    assert res["regime"] == "risk_on"
    assert res["confidence"] >= 0.6


def test_classify_conflict_lowers_confidence():
    """키워드는 risk_on인데 객관 수치가 risk_off면 confidence 감산."""
    text = "강세 회복 반등 우호적"  # on 다수 → risk_on lean
    numbers = {"fear_greed": 15, "kospi200_futures_pct": -1.8}  # risk_off
    base = mt.classify_regime_heuristic(text)
    res = mt.classify_regime_heuristic(text, numbers=numbers)
    assert res["confidence"] <= base["confidence"]


# ─────────────────────────────────────────────────────────────────────────────
# 장중 — index-board 주력 (Opus SKIP)
# ─────────────────────────────────────────────────────────────────────────────

def test_intraday_uses_index_board_primary(tmp_path, monkeypatch):
    """장중 fresh regular 브리핑 → provider=index-board, call_llm 미호출, regime이 수치 반영."""
    _iso_db(tmp_path, monkeypatch)
    _common_mocks(monkeypatch)
    fired = _capture_alerts(monkeypatch)

    intraday_calls = {"n": 0}

    async def fake_scrape_intraday():
        intraday_calls["n"] += 1
        return {
            "text": "장중 약세 하락 지속. VIX가 33.0, 공포&탐욕 지수가 18점(Fear), "
                    "코스피200 선물 약세(-1.73%).",
            "type": "regular",
            "market": "kospi",
            "generated_at": _fresh_iso(10),  # 10분 전 → fresh (기본 120분 이내)
        }

    monkeypatch.setattr(scraper, "scrape_intraday", fake_scrape_intraday)

    result = asyncio.run(mt.run_market_tone_analysis(trigger_source="intraday_refresh"))

    assert intraday_calls["n"] == 1
    assert result["ok"] is True
    assert result["provider"] == "index-board"
    assert result["regime"] == "risk_off"
    assert result["risk_level"] == "high"  # VIX 33
    assert fired == []  # 정상 경로 → 알림 없음

    # parsed_numbers 저장 확인
    import backend.services.db as _db
    with _db.get_connection() as conn:
        row = conn.execute(
            "SELECT parsed_numbers, provider FROM market_tone_results WHERE trade_date=?",
            (result["trade_date"],),
        ).fetchone()
    pn = json.loads(row["parsed_numbers"])
    assert pn["vix"] == 33.0
    assert pn["fear_greed"] == 18
    assert pn["kospi200_futures_pct"] == -1.73
    assert row["provider"] == "index-board"


# ─────────────────────────────────────────────────────────────────────────────
# 백업 경로 — 미수신 / stale
# ─────────────────────────────────────────────────────────────────────────────

def test_intraday_scrape_none_falls_back_to_neutral(tmp_path, monkeypatch):
    """장중 스크랩 None → 결정론적 중립 폴백(provider=none), LLM 미사용, 알림 1회(reason=missing)."""
    _iso_db(tmp_path, monkeypatch)
    _common_mocks(monkeypatch)
    fired = _capture_alerts(monkeypatch)

    async def fake_scrape_intraday():
        return None

    monkeypatch.setattr(scraper, "scrape_intraday", fake_scrape_intraday)

    result = asyncio.run(mt.run_market_tone_analysis(trigger_source="intraday_refresh"))

    assert result["provider"] == "none"
    assert result["tone"] == "neutral"
    assert result["regime"] == "neutral"
    assert result["risk_level"] == "normal"
    assert result["confidence"] == 0.0
    assert len(fired) == 1
    assert fired[0]["alert_type"] == "ops_watch"
    assert fired[0]["severity"] == "WARNING"
    assert "index-board 시황 미수신" in fired[0]["title"]
    assert "reason=missing" in fired[0]["detail"]


def test_morning_scrape_none_fires_backup_alert(tmp_path, monkeypatch):
    """아침 스크랩 None → 중립 폴백(provider=none) + 운영 알림 정확히 1회."""
    _iso_db(tmp_path, monkeypatch)
    _common_mocks(monkeypatch)
    fired = _capture_alerts(monkeypatch)

    async def fake_scrape_morning():
        return None

    monkeypatch.setattr(scraper, "scrape_morning", fake_scrape_morning)

    result = asyncio.run(mt.run_market_tone_analysis(trigger_source="auto_scheduler"))
    assert result["provider"] == "none"
    assert len(fired) == 1
    assert fired[0]["alert_type"] == "ops_watch"
    assert fired[0]["severity"] == "WARNING"


def test_stale_briefing_falls_back_to_heuristic_stale(tmp_path, monkeypatch):
    """장중 stale 브리핑(오래된 generated_at) → provider=heuristic-stale(중립강제 아님) + 알림 reason=stale."""
    _iso_db(tmp_path, monkeypatch)
    _common_mocks(monkeypatch)
    fired = _capture_alerts(monkeypatch)

    async def fake_scrape_intraday():
        return {
            "text": "장중 약세 하락 부진 경계 위축.",  # off 키워드 다수 → 휴리스틱 risk_off
            "type": "regular",
            "market": "kospi",
            "generated_at": _fresh_iso(minutes_ago=300),  # 5h 전 → 기본 120분 초과 stale
        }

    monkeypatch.setattr(scraper, "scrape_intraday", fake_scrape_intraday)

    result = asyncio.run(mt.run_market_tone_analysis(trigger_source="intraday_refresh"))
    assert result["provider"] == "heuristic-stale"
    # 휴리스틱으로 판정(중립 강제 아님) — off 키워드 다수 → risk_off.
    assert result["regime"] == "risk_off"
    assert len(fired) == 1
    assert fired[0]["alert_type"] == "ops_watch"
    assert fired[0]["severity"] == "WARNING"
    assert "reason=stale" in fired[0]["detail"]


def test_morning_stale_briefing_uses_18h_window(tmp_path, monkeypatch):
    """아침 브리핑은 18h 윈도우 — 10h 전이면 fresh로 index-board 주력."""
    _iso_db(tmp_path, monkeypatch)
    _common_mocks(monkeypatch)
    fired = _capture_alerts(monkeypatch)

    async def fake_scrape_morning():
        return {
            "text": "간밤 위험선호 회복, 강세 출발, 반등 기대. 우호적.",
            "type": "pre",
            "market": "kospi",
            "generated_at": _fresh_iso(minutes_ago=600),  # 10h 전 → 아침 18h 윈도우 내 fresh
        }

    monkeypatch.setattr(scraper, "scrape_morning", fake_scrape_morning)

    result = asyncio.run(mt.run_market_tone_analysis(trigger_source="auto_scheduler"))
    assert result["provider"] == "index-board"
    assert result["regime"] == "risk_on"
    assert fired == []
