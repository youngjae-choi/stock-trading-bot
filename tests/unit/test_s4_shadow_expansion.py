"""A6 — 반사실(shadow) 추적을 S4 선정-미진입 종목까지 확대 TDD 테스트.

운영 DB를 건드리지 않도록 settings.APP_DB_PATH 를 tmp_path 로 monkeypatch 한 뒤
스키마를 초기화해 격리된 SQLite 파일에서만 검증한다.

검증 항목:
  ① 당일 S4 선정 3종목 중 1종목만 매수 → 나머지 2종목이 shadow_trades 에
     missed_stage='S4_SELECTED_NOT_ENTERED' 로 기록된다 (매도 주문은 진입으로 안 침)
  ② 이미 같은 trade_date+symbol 의 shadow 행이 있으면 중복 기록되지 않는다
  ③ 선정 종목 전부 매수 시 0건
  ④ 같은 날 스크리닝 run 이 여러 개면 최신(created_at DESC) run 기준으로 판단한다
  ⑤ 후보에 가격 필드가 없으면 entry_price=0.0 으로 저장된다 (스키마 NOT NULL)

update_missed_returns 자체(KIS get_daily_chart 의존)는 기존 커버리지를 신뢰하고
여기서는 테스트하지 않는다 — record_s4_unentered_shadows 는 순수 DB 로직이다.
"""

from __future__ import annotations

import json
import uuid

import pytest

from backend.config import settings
from backend.services.db import get_connection, initialize_database
from backend.services.engine.missed_opportunity import record_s4_unentered_shadows

TRADE_DATE = "2026-06-10"


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    """격리된 임시 SQLite DB로 APP_DB_PATH 를 교체하고 스키마를 초기화."""
    db_file = tmp_path / "test_s4_shadow.sqlite3"
    monkeypatch.setattr(settings, "APP_DB_PATH", str(db_file))
    initialize_database()
    # hybrid_screening_results / trading_orders 는 각 서비스 모듈이 lazy 생성 — 직접 보장
    from backend.services.engine.hybrid_screening import _ensure_table
    from backend.services.engine.order_executor import _ensure_orders_table

    _ensure_table()
    _ensure_orders_table()
    yield db_file


def _insert_screening(candidates: list[dict], created_at: str = "2026-06-10T08:50:00Z") -> str:
    """hybrid_screening_results 1행(run) 삽입 후 id 반환."""
    row_id = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO hybrid_screening_results
                (id, trade_date, candidates, skipped, overall_confidence,
                 provider, raw_input_count, output_count, created_at)
            VALUES (?, ?, ?, '[]', 0.8, 'test', ?, ?, ?)
            """,
            (row_id, TRADE_DATE, json.dumps(candidates, ensure_ascii=False), len(candidates), len(candidates), created_at),
        )
    return row_id


def _insert_order(symbol: str, side: str = "buy", status: str = "submitted") -> None:
    """trading_orders 1행 삽입 (상태 무관 — cancelled 도 진입 시도로 본다)."""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO trading_orders
                (id, trade_date, signal_id, symbol, name, side, order_type,
                 qty, price, kis_order_no, status, reason, created_at)
            VALUES (?, ?, '', ?, '', ?, 'limit', 10, 1000.0, '', ?, '', ?)
            """,
            (str(uuid.uuid4()), TRADE_DATE, symbol, side, status, "2026-06-10T09:10:00+09:00"),
        )


def _shadow_rows() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM shadow_trades WHERE trade_date = ? ORDER BY symbol", (TRADE_DATE,)
        ).fetchall()
    return [dict(r) for r in rows]


def test_records_unentered_selected_symbols(isolated_db):
    """① 선정 3종목 중 1종목만 매수 → 2종목 shadow 기록 (매도 주문은 무시)."""
    _insert_screening(
        [
            {"symbol": "000111", "name": "종목A", "price": 10000},
            {"symbol": "000222", "name": "종목B", "price": 20000},
            {"symbol": "000333", "name": "종목C", "price": 30000},
        ]
    )
    _insert_order("000111", side="buy", status="cancelled")  # 상태 무관 — 진입 시도로 간주
    _insert_order("000333", side="sell", status="filled")  # 매도 주문은 진입이 아님

    inserted = record_s4_unentered_shadows(TRADE_DATE)

    assert inserted == 2
    rows = _shadow_rows()
    assert [r["symbol"] for r in rows] == ["000222", "000333"]
    for row in rows:
        assert row["missed_stage"] == "S4_SELECTED_NOT_ENTERED"
        assert row["status"] == "active"
        assert row["max_return_eod"] is None  # EOD 갱신 전
    assert rows[0]["entry_price"] == 20000.0
    assert rows[0]["symbol_name"] == "종목B"
    assert rows[1]["entry_price"] == 30000.0


def test_no_duplicate_when_shadow_already_exists(isolated_db):
    """② 같은 trade_date+symbol 의 shadow 행이 이미 있으면 skip (재호출 멱등)."""
    _insert_screening(
        [
            {"symbol": "000111", "name": "종목A", "price": 10000},
            {"symbol": "000222", "name": "종목B", "price": 20000},
        ]
    )
    # 000111 은 S6 단계에서 이미 shadow 기록됨
    from backend.services.engine.shadow_trading import create_shadow_trade

    create_shadow_trade(
        trade_date=TRADE_DATE,
        symbol="000111",
        symbol_name="종목A",
        missed_stage="S6_NO_SIGNAL",
        entry_price=10000.0,
        entry_time="2026-06-10T15:30:00+09:00",
    )

    first = record_s4_unentered_shadows(TRADE_DATE)
    assert first == 1  # 000222 만 추가

    second = record_s4_unentered_shadows(TRADE_DATE)
    assert second == 0  # 재호출 시 중복 없음

    rows = _shadow_rows()
    assert len(rows) == 2
    stages = {r["symbol"]: r["missed_stage"] for r in rows}
    assert stages["000111"] == "S6_NO_SIGNAL"  # 기존 행 보존
    assert stages["000222"] == "S4_SELECTED_NOT_ENTERED"


def test_zero_when_all_selected_entered(isolated_db):
    """③ 선정 종목 전부 buy 주문 존재 → 0건."""
    _insert_screening(
        [
            {"symbol": "000111", "name": "종목A", "price": 10000},
            {"symbol": "000222", "name": "종목B", "price": 20000},
        ]
    )
    _insert_order("000111")
    _insert_order("000222", status="filled")

    assert record_s4_unentered_shadows(TRADE_DATE) == 0
    assert _shadow_rows() == []


def test_uses_latest_screening_run(isolated_db):
    """④ 같은 날 run 여러 개 → 최신 run 의 후보만 대상."""
    _insert_screening(
        [{"symbol": "000111", "name": "구후보", "price": 10000}],
        created_at="2026-06-10T08:50:00Z",
    )
    _insert_screening(
        [{"symbol": "000999", "name": "신후보", "price": 50000}],
        created_at="2026-06-10T10:30:00Z",
    )

    inserted = record_s4_unentered_shadows(TRADE_DATE)

    assert inserted == 1
    rows = _shadow_rows()
    assert [r["symbol"] for r in rows] == ["000999"]


def test_missing_price_stored_as_zero(isolated_db):
    """⑤ 후보에 price 없음 → entry_price=0.0 (NOT NULL 스키마, EOD 갱신은 skip 대상)."""
    _insert_screening([{"symbol": "000444", "name": "무가격"}])

    assert record_s4_unentered_shadows(TRADE_DATE) == 1
    rows = _shadow_rows()
    assert rows[0]["entry_price"] == 0.0


def test_no_screening_returns_zero(isolated_db):
    """스크리닝 결과 자체가 없으면 0건 (에러 없이)."""
    assert record_s4_unentered_shadows(TRADE_DATE) == 0
