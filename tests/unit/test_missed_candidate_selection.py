"""Missed Entry 선별 기준 개선 TDD 테스트.

운영 DB를 건드리지 않도록 settings.APP_DB_PATH 를 tmp_path 로 monkeypatch 한 뒤
스키마를 초기화해 격리된 SQLite 파일에서만 검증한다.

검증 항목:
  (a) intraday_high_return >= threshold 이면 improvement_candidate=1, 미만이면 0
  (b) intraday_low_return 음수가 저장된다
  (c) review_audit._load_missed_entries 가 improvement_candidate=1 행만 반환
  (d) get_daily_chart mock 으로 stck_hgpr/stck_lwpr/price_at_missed 계산 검증
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

import backend.services.engine.missed_opportunity as mo
import backend.services.engine.review_audit as ra
from backend.config import settings
from backend.services.db import get_connection, initialize_database


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    """격리된 임시 SQLite DB로 APP_DB_PATH 를 교체하고 스키마를 초기화."""
    db_file = tmp_path / "test_missed_candidate.sqlite3"
    monkeypatch.setattr(settings, "APP_DB_PATH", str(db_file))
    initialize_database()
    yield db_file


def _insert_missed(
    *,
    trade_date: str,
    symbol: str,
    price_at_missed: float,
    created_at: str = "2026-06-07T09:30:00+09:00",
) -> str:
    """pending(미업데이트) missed_opportunities 1행 삽입 후 id 반환."""
    row_id = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO missed_opportunities
                (id, trade_date, symbol, symbol_name, missed_stage, missed_reason,
                 price_at_missed, improvement_candidate, created_at)
            VALUES (?, ?, ?, ?, 'S3_FILTER', '테스트 제외', ?, 0, ?)
            """,
            (row_id, trade_date, symbol, symbol, float(price_at_missed), created_at),
        )
    return row_id


def _fetch(row_id: str) -> dict:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM missed_opportunities WHERE id = ?", (row_id,)
        ).fetchone()
    return dict(row)


def _mock_daily_chart(monkeypatch, *, hgpr: float, lwpr: float, clpr: float = 0.0):
    """get_daily_chart 를 고정된 고가/저가/종가로 mock."""
    async def fake_daily_chart(symbol, period_code="D", adjusted_price="1"):
        return {
            "output": [
                {
                    "stck_hgpr": str(hgpr),
                    "stck_lwpr": str(lwpr),
                    "stck_clpr": str(clpr),
                }
            ]
        }

    async def fake_intraday_chart(*args, **kwargs):  # 호출되면 실패하도록 (분봉 폐기 검증)
        raise AssertionError("get_intraday_chart 는 호출되면 안 된다 (분봉 폐기)")

    import backend.services.kis.domestic.service as kis_service

    monkeypatch.setattr(kis_service, "get_daily_chart", fake_daily_chart, raising=False)
    monkeypatch.setattr(kis_service, "get_intraday_chart", fake_intraday_chart, raising=False)


def test_high_return_at_or_above_threshold_marks_candidate(isolated_db, monkeypatch):
    """장중 최고가 상승률 >= threshold 이면 candidate=1."""
    trade_date = "2026-06-07"
    # price 10000, 고가 10300 -> +3% >= 2% threshold -> candidate
    row_id = _insert_missed(trade_date=trade_date, symbol="000001", price_at_missed=10000.0)
    _mock_daily_chart(monkeypatch, hgpr=10300.0, lwpr=9800.0)

    result = asyncio.run(mo.update_missed_returns(trade_date))
    assert result["updated"] == 1

    row = _fetch(row_id)
    assert row["improvement_candidate"] == 1
    assert row["max_return_until_eod"] == pytest.approx(3.0)
    # (d) 계산 검증: 고가 상승률
    assert row["max_return_until_eod"] == pytest.approx((10300 - 10000) / 10000 * 100)


def test_high_return_below_threshold_not_candidate(isolated_db, monkeypatch):
    """장중 최고가 상승률 < threshold 이면 candidate=0."""
    trade_date = "2026-06-07"
    # price 10000, 고가 10100 -> +1% < 2% threshold -> not candidate
    row_id = _insert_missed(trade_date=trade_date, symbol="000002", price_at_missed=10000.0)
    _mock_daily_chart(monkeypatch, hgpr=10100.0, lwpr=9900.0)

    asyncio.run(mo.update_missed_returns(trade_date))

    row = _fetch(row_id)
    assert row["improvement_candidate"] == 0
    assert row["max_return_until_eod"] == pytest.approx(1.0)


def test_intraday_low_return_negative_stored(isolated_db, monkeypatch):
    """장중 최저가 상승률(음수)이 intraday_low_return 에 저장된다."""
    trade_date = "2026-06-07"
    # price 10000, 저가 9500 -> -5%
    row_id = _insert_missed(trade_date=trade_date, symbol="000003", price_at_missed=10000.0)
    _mock_daily_chart(monkeypatch, hgpr=10500.0, lwpr=9500.0)

    asyncio.run(mo.update_missed_returns(trade_date))

    row = _fetch(row_id)
    assert row["intraday_low_return"] == pytest.approx(-5.0)
    assert row["intraday_low_return"] < 0


def test_threshold_read_from_settings(isolated_db, monkeypatch):
    """threshold 를 settings 값으로 보정한다 (설정 5% 이면 +3% 는 non-candidate)."""
    from backend.services import settings_store

    settings_store.upsert_setting(
        "missed.improvement_threshold", 5.0, "number", "test", "test"
    )
    trade_date = "2026-06-07"
    row_id = _insert_missed(trade_date=trade_date, symbol="000004", price_at_missed=10000.0)
    _mock_daily_chart(monkeypatch, hgpr=10300.0, lwpr=9800.0)  # +3%

    asyncio.run(mo.update_missed_returns(trade_date))  # 명시값 없음 -> 설정 5% 사용

    row = _fetch(row_id)
    assert row["improvement_candidate"] == 0  # 3% < 5%


def test_load_missed_entries_returns_only_candidates(isolated_db):
    """_load_missed_entries 는 improvement_candidate=1 행만 반환한다."""
    trade_date = "2026-06-07"
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO missed_opportunities
                (id, trade_date, symbol, symbol_name, missed_stage, missed_reason,
                 price_at_missed, max_return_until_eod, intraday_low_return,
                 improvement_candidate, created_at)
            VALUES (?, ?, 'C0001', 'cand', 'S3_FILTER', 'r', 10000, 3.0, -2.0, 1, ?)
            """,
            (str(uuid.uuid4()), trade_date, "2026-06-07T09:30:00+09:00"),
        )
        conn.execute(
            """
            INSERT INTO missed_opportunities
                (id, trade_date, symbol, symbol_name, missed_stage, missed_reason,
                 price_at_missed, max_return_until_eod, intraday_low_return,
                 improvement_candidate, created_at)
            VALUES (?, ?, 'N0002', 'noncand', 'S3_FILTER', 'r', 10000, 1.0, -1.0, 0, ?)
            """,
            (str(uuid.uuid4()), trade_date, "2026-06-07T09:31:00+09:00"),
        )

    entries = ra._load_missed_entries(trade_date)
    mo_entries = [e for e in entries if e.get("source") == "missed_opportunities"]
    symbols = {e["symbol"] for e in mo_entries}
    assert "C0001" in symbols
    assert "N0002" not in symbols
    # intraday_low_return 노출 확인
    cand = next(e for e in mo_entries if e["symbol"] == "C0001")
    assert cand["intraday_low_return"] == pytest.approx(-2.0)


def test_build_missed_entry_memory_includes_opinion(isolated_db):
    """learning_memory 가 '거르지 말 것' 의견 문구를 recommendation 에 생성한다."""
    import backend.services.engine.learning_memory as lm

    entry = {
        "symbol": "000005",
        "symbol_name": "테스트",
        "missed_stage": "S3_FILTER",
        "missed_reason": "거래량 부족",
        "price_at_missed": 10000.0,
        "max_return_until_eod": 4.5,
        "intraday_low_return": -1.5,
        "source": "missed_opportunities",
    }
    memory = lm._build_missed_entry_memory(
        trade_date="2026-06-07",
        entry=entry,
        created_at="2026-06-07T22:00:00+09:00",
        expires_at="2026-06-14T22:00:00+09:00",
    )
    rec = memory["recommendation"]
    opinion = str(rec.get("opinion") or rec.get("note") or "")
    assert "4.5" in opinion
    assert "-1.5" in opinion or "1.5" in opinion
