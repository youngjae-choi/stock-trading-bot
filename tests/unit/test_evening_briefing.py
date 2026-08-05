"""장후 브리핑 저장/조회 + 결정론적 감성 분류 단위 테스트 (격리 DB).

classify_sentiment는 LLM을 쓰지 않는 동기 함수로, index_board_scraper.parse_briefing_numbers
가 반환한 객관 수치(vix/fear_greed/kospi200_futures_pct)를 임계값 규칙으로
volatile/risk_off/risk_on/neutral 중 하나로 매핑한다.
"""
from backend.config import settings
import backend.services.db as db_mod
import backend.services.engine.evening_briefing as eb
import backend.services.engine.index_board_scraper as scraper


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


def _patch_numbers(monkeypatch, nums):
    """classify_sentiment가 참조하는 parse_briefing_numbers를 고정 dict로 대체."""
    def fake_parse(text):
        return nums

    monkeypatch.setattr(scraper, "parse_briefing_numbers", fake_parse)


def test_classify_sentiment_volatile_from_vix(tmp_path, monkeypatch):
    """VIX>=30 → 극단 변동성(volatile) 최우선."""
    _patch_numbers(
        monkeypatch,
        {"vix": 32.0, "fear_greed": None, "kospi200_futures_pct": None,
         "sox_pct": None, "usdkrw": None},
    )
    assert eb.classify_sentiment("변동성 급등") == "volatile"


def test_classify_sentiment_risk_off_from_negative_futures(tmp_path, monkeypatch):
    """코스피200 야간선물 <= -1.0 → risk_off."""
    _patch_numbers(
        monkeypatch,
        {"vix": None, "fear_greed": None, "kospi200_futures_pct": -1.5,
         "sox_pct": None, "usdkrw": None},
    )
    assert eb.classify_sentiment("야간선물 급락") == "risk_off"


def test_classify_sentiment_risk_on_from_greed(tmp_path, monkeypatch):
    """공포탐욕 >= 65 → risk_on."""
    _patch_numbers(
        monkeypatch,
        {"vix": None, "fear_greed": 70, "kospi200_futures_pct": None,
         "sox_pct": None, "usdkrw": None},
    )
    assert eb.classify_sentiment("탐욕 구간") == "risk_on"


def test_classify_sentiment_neutral_when_mild(tmp_path, monkeypatch):
    """모든 수치가 온화/None → neutral."""
    _patch_numbers(
        monkeypatch,
        {"vix": 18.0, "fear_greed": 50, "kospi200_futures_pct": 0.2,
         "sox_pct": None, "usdkrw": None},
    )
    assert eb.classify_sentiment("특이사항 없음") == "neutral"


def test_classify_sentiment_neutral_on_empty_text(tmp_path, monkeypatch):
    """빈 텍스트 → 파싱 없이 neutral 폴백."""
    called = {"n": 0}

    def fake_parse(text):
        called["n"] += 1
        return {}

    monkeypatch.setattr(scraper, "parse_briefing_numbers", fake_parse)
    assert eb.classify_sentiment("") == "neutral"
    assert called["n"] == 0  # 빈 텍스트는 파싱 자체를 건너뜀


def test_classify_sentiment_neutral_on_parse_exception(tmp_path, monkeypatch):
    """parse_briefing_numbers가 예외를 던지면 neutral 폴백."""
    def fake_parse(text):
        raise ValueError("boom")

    monkeypatch.setattr(scraper, "parse_briefing_numbers", fake_parse)
    assert eb.classify_sentiment("어떤 텍스트") == "neutral"
