"""(Wave2 A-full Part 2) 이월 손익 = KIS 검증 open 스냅샷 × 금일 매도가로 정확 산출.

drift로 오염된 trade_pairs 다중일 wavg 뭉침(예: 매드업 -4.5M 착시) 대신,
daily_holdings_snapshot(장전 KIS 실보유)을 이월 수량·원가의 단일 진실로 삼는다.
스냅샷 없는 과거일은 None → 총액 fallback(가짜 숫자 금지).
"""

from __future__ import annotations

import tempfile

import pytest

import backend.services.engine.holdings_snapshot as hs
import backend.services.engine.review_audit as ra


@pytest.fixture()
def db(monkeypatch):
    from backend.config import settings as cfg
    from backend.services.db import initialize_database

    tmp = tempfile.mktemp(suffix=".sqlite3")
    monkeypatch.setattr(cfg, "APP_DB_PATH", tmp)
    initialize_database()
    return tmp


def test_today_sells_by_norm_filters_and_wavg():
    pairs = [{
        "symbol": "005930",
        "orders": [
            {"side": "sell", "trade_date": "2026-08-11", "fill_qty": 60, "fill_price": 71000},
            {"side": "sell", "trade_date": "2026-08-11", "fill_qty": 40, "fill_price": 72000},
            {"side": "sell", "trade_date": "2026-08-10", "fill_qty": 100, "fill_price": 69000},  # 전일 제외
            {"side": "buy", "trade_date": "2026-08-11", "fill_qty": 100, "fill_price": 70000},   # 매수 제외
        ],
    }]
    out = ra._today_sells_by_norm(pairs, "2026-08-11")
    nsym = ra.norm_symbol("005930")
    assert out[nsym]["sell_qty"] == 100
    assert out[nsym]["sell_avg"] == (60 * 71000 + 40 * 72000) / 100  # 71,400


def test_carried_accurate_from_snapshot(db):
    hs.upsert_holdings("2026-08-11", [{"symbol": "005930", "qty": 100, "avg_price": 70000}])
    pairs = [{
        "symbol": "005930", "name": "삼성전자",
        "orders": [{"side": "sell", "trade_date": "2026-08-11", "fill_qty": 100, "fill_price": 71000}],
    }]
    res = ra._compute_carried_from_snapshot("2026-08-11", pairs)
    assert res is not None
    assert len(res["items"]) == 1
    it = res["items"][0]
    assert it["qty"] == 100
    assert it["buy_price"] == 70000
    assert it["sell_price"] == 71000
    assert it["pnl_amount"] == 100000  # (71000-70000)*100
    assert res["total"] == 100000


def test_carried_none_when_no_snapshot(db):
    pairs = [{
        "symbol": "005930",
        "orders": [{"side": "sell", "trade_date": "2026-08-11", "fill_qty": 100, "fill_price": 71000}],
    }]
    assert ra._compute_carried_from_snapshot("2026-08-11", pairs) is None  # 스냅샷 없음 → 총액 fallback


def test_carried_excludes_symbol_not_sold_today(db):
    hs.upsert_holdings("2026-08-11", [{"symbol": "005930", "qty": 100, "avg_price": 70000}])
    res = ra._compute_carried_from_snapshot("2026-08-11", [])  # 오늘 청산 없음
    assert res is not None
    assert res["items"] == []  # 이월분 미청산 → 이월청산 항목 없음


def test_carried_matched_capped_by_min_qty(db):
    """이월 100주인데 오늘 60주만 청산 → matched 60주만 이월손익."""
    hs.upsert_holdings("2026-08-11", [{"symbol": "005930", "qty": 100, "avg_price": 70000}])
    pairs = [{
        "symbol": "005930",
        "orders": [{"side": "sell", "trade_date": "2026-08-11", "fill_qty": 60, "fill_price": 71000}],
    }]
    res = ra._compute_carried_from_snapshot("2026-08-11", pairs)
    assert res is not None
    assert res["items"][0]["qty"] == 60
    assert res["items"][0]["pnl_amount"] == 60000
