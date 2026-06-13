"""P4 콘솔 UI 3종 — 백엔드 API TDD 테스트.

운영 DB 미접촉: settings.APP_DB_PATH 를 tmp_path 로 monkeypatch 후 스키마 초기화.

검증 항목:
  ① False Positive 목록 기간 필터 — /list start/end 생략 시 오늘 기본값(하위 호환)
  ② Missed(missed_opportunity/shadow_trading) 목록 기간 필터 — start/end 추가
  ③ shadow_trades 장중 최저가/최고가/종가 저장 (get_daily_chart mock)
  ④ intraday-events 계약 회귀 — 간단 호출만 (P3 상세 테스트와 중복 금지)
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient

import backend.main as main_mod
import backend.services.engine.missed_opportunity as mo
from backend.config import settings
from backend.services.db import get_connection, initialize_database
from backend.services.engine.shadow_trading import create_shadow_trade

client = TestClient(main_mod.app)


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    """격리된 임시 SQLite DB로 APP_DB_PATH 교체 + 스키마 초기화."""
    db_file = tmp_path / "test_p4.sqlite3"
    monkeypatch.setattr(settings, "APP_DB_PATH", str(db_file))
    initialize_database()
    yield db_file


def _today_kst() -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# ① False Positive 목록 기간 필터
# ---------------------------------------------------------------------------

def _insert_fp(trade_date: str, symbol: str) -> str:
    row_id = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO false_positive_cases
                (id, trade_date, symbol, symbol_name, false_positive_type, created_at)
            VALUES (?, ?, ?, ?, 'entry_fail', ?)
            """,
            (row_id, trade_date, symbol, symbol, trade_date + "T16:00:00+09:00"),
        )
    return row_id


def test_fp_list_range_filter(isolated_db):
    """start/end 범위 내 케이스만 반환한다."""
    _insert_fp("2026-06-01", "A00001")
    _insert_fp("2026-06-05", "A00002")
    _insert_fp("2026-06-10", "A00003")

    r = client.get("/api/v1/false-positive/list?start=2026-06-04&end=2026-06-09")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    symbols = {it["symbol"] for it in body["payload"]["items"]}
    assert symbols == {"A00002"}


def test_fp_list_defaults_to_today(isolated_db):
    """start/end 생략 시 오늘(KST) 하루만 조회한다 (하위 호환 기본값)."""
    today = _today_kst()
    _insert_fp("2026-01-02", "OLD001")
    _insert_fp(today, "NEW001")

    r = client.get("/api/v1/false-positive/list")
    assert r.status_code == 200
    items = r.json()["payload"]["items"]
    symbols = {it["symbol"] for it in items}
    assert symbols == {"NEW001"}


# ---------------------------------------------------------------------------
# ② Missed 목록 기간 필터 (missed_opportunity + shadow_trading)
# ---------------------------------------------------------------------------

def _insert_missed(trade_date: str, symbol: str) -> str:
    row_id = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO missed_opportunities
                (id, trade_date, symbol, symbol_name, missed_stage, missed_reason,
                 price_at_missed, improvement_candidate, created_at)
            VALUES (?, ?, ?, ?, 'S3_FILTER', '테스트', 10000, 0, ?)
            """,
            (row_id, trade_date, symbol, symbol, trade_date + "T09:30:00+09:00"),
        )
    return row_id


def test_missed_opportunity_range_filter(isolated_db):
    """missed-opportunity /today 에 start/end 를 주면 기간 조회한다."""
    _insert_missed("2026-06-02", "M00001")
    _insert_missed("2026-06-08", "M00002")

    r = client.get("/api/v1/missed-opportunity/today?start=2026-06-01&end=2026-06-05")
    assert r.status_code == 200
    rows = r.json()["payload"]
    assert {x["symbol"] for x in rows} == {"M00001"}


def test_missed_opportunity_defaults_to_today(isolated_db):
    """start/end 생략 시 기존처럼 오늘만 반환한다 (하위 호환)."""
    today = _today_kst()
    _insert_missed("2026-01-02", "MOLD01")
    _insert_missed(today, "MNEW01")

    r = client.get("/api/v1/missed-opportunity/today")
    assert r.status_code == 200
    rows = r.json()["payload"]
    assert {x["symbol"] for x in rows} == {"MNEW01"}


def test_shadow_trading_range_filter(isolated_db):
    """shadow-trading /today 에 start/end 를 주면 기간 조회한다."""
    create_shadow_trade(
        trade_date="2026-06-02", symbol="S00001", symbol_name="섀도1",
        missed_stage="S6_NO_SIGNAL", entry_price=10000.0,
        entry_time="2026-06-02T10:00:00+09:00",
    )
    create_shadow_trade(
        trade_date="2026-06-08", symbol="S00002", symbol_name="섀도2",
        missed_stage="S6_NO_SIGNAL", entry_price=10000.0,
        entry_time="2026-06-08T10:00:00+09:00",
    )

    r = client.get("/api/v1/shadow-trading/today?start=2026-06-07&end=2026-06-09")
    assert r.status_code == 200
    rows = r.json()["payload"]
    assert {x["symbol"] for x in rows} == {"S00002"}


# ---------------------------------------------------------------------------
# ③ shadow_trades 장중 최저가/최고가/종가 저장
# ---------------------------------------------------------------------------

def _mock_daily_chart(monkeypatch, *, hgpr: float, lwpr: float, clpr: float):
    async def fake_daily_chart(symbol, period_code="D", adjusted_price="1"):
        return {
            "output": [
                {"stck_hgpr": str(hgpr), "stck_lwpr": str(lwpr), "stck_clpr": str(clpr)}
            ]
        }

    import backend.services.kis.domestic.service as kis_service

    monkeypatch.setattr(kis_service, "get_daily_chart", fake_daily_chart, raising=False)


def test_shadow_eod_update_saves_low_high_close(isolated_db, monkeypatch):
    """update_missed_returns 가 shadow_trades 에 intraday_low/high/close_price 를 저장한다."""
    trade_date = "2026-06-08"
    row = create_shadow_trade(
        trade_date=trade_date, symbol="S10001", symbol_name="섀도",
        missed_stage="S4_SELECTED_NOT_ENTERED", entry_price=10000.0,
        entry_time=trade_date + "T09:05:00+09:00",
    )
    _mock_daily_chart(monkeypatch, hgpr=10600.0, lwpr=9700.0, clpr=10200.0)

    result = asyncio.run(mo.update_missed_returns(trade_date))
    assert result["shadow_updated"] == 1

    with get_connection() as conn:
        saved = dict(conn.execute("SELECT * FROM shadow_trades WHERE id = ?", (row["id"],)).fetchone())
    assert saved["intraday_high"] == pytest.approx(10600.0)
    assert saved["intraday_low"] == pytest.approx(9700.0)
    assert saved["close_price"] == pytest.approx(10200.0)
    # 기존 의미 유지: max_return_eod = 장중 최고가 상승률(%)
    assert saved["max_return_eod"] == pytest.approx(6.0)


def test_shadow_eod_update_legacy_rows_compatible(isolated_db, monkeypatch):
    """구 행(신규 컬럼 NULL)도 깨지지 않고 채워진다 (ALTER 마이그레이션 호환)."""
    trade_date = "2026-06-08"
    # 신규 컬럼을 명시하지 않는 구버전 INSERT 경로
    row_id = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO shadow_trades
                (id, trade_date, symbol, symbol_name, missed_stage, entry_price,
                 entry_time, status, created_at)
            VALUES (?, ?, 'S20002', '구행', 'S6_NO_SIGNAL', 20000.0, ?, 'active', ?)
            """,
            (row_id, trade_date, trade_date + "T09:10:00+09:00", trade_date + "T09:10:00+09:00"),
        )
    _mock_daily_chart(monkeypatch, hgpr=21000.0, lwpr=19000.0, clpr=20500.0)

    asyncio.run(mo.update_missed_returns(trade_date))

    with get_connection() as conn:
        saved = dict(conn.execute("SELECT * FROM shadow_trades WHERE id = ?", (row_id,)).fetchone())
    assert saved["intraday_high"] == pytest.approx(21000.0)
    assert saved["intraday_low"] == pytest.approx(19000.0)
    assert saved["close_price"] == pytest.approx(20500.0)
    assert saved["max_return_eod"] == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# ④ intraday-events 계약 회귀 (간단 호출 — P3 상세 테스트와 중복 금지)
# ---------------------------------------------------------------------------

def test_intraday_events_contract_simple(isolated_db):
    """빈 날짜라도 {date, count, events} 계약을 유지한다."""
    r = client.get("/api/v1/daily-plan/intraday-events?date=2026-06-12")
    assert r.status_code == 200
    body = r.json()
    assert body["date"] == "2026-06-12"
    assert body["count"] == 0
    assert body["events"] == []


def test_intraday_events_rejects_bad_date(isolated_db):
    r = client.get("/api/v1/daily-plan/intraday-events?date=2026/06/12")
    assert r.status_code == 400
