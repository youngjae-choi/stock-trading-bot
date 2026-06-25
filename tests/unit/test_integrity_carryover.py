"""무결성 경고 — 전일 보유분(carryover) 오탐 방지 (TASK A3).

전일 매수 → 당일 매도한 종목은 당일 창에서 buy_qty=0/sell_qty>0 으로 보여
'순매도 음수'·'매도 초과' 오탐이 났다. opening_position(당일 이전 활성 매수-매도)을
가용수량에 더해 sell > (opening + today_buy) 일 때만 경고한다.

실제 케이스:
  · 198440: 6/22 매수 11135, 6/23 매도 11135 → opening 11135 → 경고 없음
  · 276650: 매수 이력 없음, 6/23 매도 87 → opening 0 → 경고 유지
  · 484130: 6/22 매수·전량매도 → opening 0, 6/23 매도 1561 → 경고 유지
"""

import tempfile
import uuid

import pytest


@pytest.fixture()
def db(monkeypatch):
    from backend.config import settings as cfg
    from backend.services.db import initialize_database
    from backend.services.engine.order_executor import _ensure_orders_table
    from backend.services.engine.fill_poller import _ensure_fills_table

    tmp = tempfile.mktemp(suffix=".sqlite3")
    monkeypatch.setattr(cfg, "APP_DB_PATH", tmp)
    initialize_database()
    _ensure_orders_table()
    _ensure_fills_table()
    return tmp


def _insert(symbol, side, qty, trade_date, status="filled", price=1000):
    from backend.services.db import get_connection
    oid = str(uuid.uuid4())
    with get_connection() as c:
        c.execute(
            "INSERT INTO trading_orders (id, trade_date, signal_id, symbol, name, side, order_type, qty, price, kis_order_no, status, reason, created_at) "
            "VALUES (?, ?, '', ?, ?, ?, 'market', ?, ?, '', ?, '', ?)",
            (oid, trade_date, symbol, symbol, side, qty, price, status, trade_date + "T10:00:00"),
        )
    return oid


def _warn_symbols(trade_date):
    """summarize_order_integrity의 두 경고 payload에서 종목 집합 추출."""
    from backend.services.engine.position_integrity import summarize_order_integrity
    s = summarize_order_integrity(trade_date)
    neg = {str(i.get("symbol")) for i in s.get("net_negative_positions", [])}
    exc = {str(i.get("symbol")) for i in s.get("sell_qty_exceeds_buy_qty", [])}
    return neg, exc, s


def test_carryover_balanced_no_warning(db):
    """198440: 전일 매수 11135, 당일 매도 11135 → 경고 없음."""
    _insert("198440", "buy", 11135, "2026-06-22")
    _insert("198440", "sell", 11135, "2026-06-23")
    neg, exc, _ = _warn_symbols("2026-06-23")
    assert "198440" not in neg
    assert "198440" not in exc


def test_phantom_never_bought_still_warns(db):
    """276650: 매수 이력 없이 당일 매도 87 → 경고 유지."""
    _insert("276650", "sell", 87, "2026-06-23")
    neg, exc, _ = _warn_symbols("2026-06-23")
    assert "276650" in neg
    assert "276650" in exc


def test_fully_sold_prior_day_still_warns(db):
    """484130: 6/22 매수·전량매도(opening 0), 6/23 매도 1561 → 경고 유지."""
    _insert("484130", "buy", 1561, "2026-06-22")
    _insert("484130", "sell", 1561, "2026-06-22")
    _insert("484130", "sell", 1561, "2026-06-23")
    neg, exc, _ = _warn_symbols("2026-06-23")
    assert "484130" in neg
    assert "484130" in exc


def test_normal_same_day_round_trip_no_warning(db):
    """당일 매수 100 → 당일 매도 100 → 경고 없음."""
    _insert("000660", "buy", 100, "2026-06-23")
    _insert("000660", "sell", 100, "2026-06-23")
    neg, exc, _ = _warn_symbols("2026-06-23")
    assert "000660" not in neg
    assert "000660" not in exc


def test_carryover_partial_oversell_warns_with_excess(db):
    """opening 100, 당일 매도 150 → 50 초과분만 경고, excess_qty=50."""
    _insert("111111", "buy", 100, "2026-06-22")
    _insert("111111", "sell", 150, "2026-06-23")
    neg, exc, s = _warn_symbols("2026-06-23")
    assert "111111" in neg and "111111" in exc
    item = next(i for i in s["sell_qty_exceeds_buy_qty"] if i["symbol"] == "111111")
    assert item["excess_qty"] == 50
