"""일자별 KIS 보유 스냅샷 (daily_holdings_snapshot) — 이월(carried-in) 손익의 KIS 검증 단일 소스.

drift로 오염된 trading_orders/fills/cost_basis 대신, 장전 get_balance를 종목별로 스냅샷해
이월 손익을 정확히 계산하기 위한 토대. (Wave2 A-full Part 1)
"""

from __future__ import annotations

import tempfile

import pytest

import backend.services.engine.holdings_snapshot as hs


@pytest.fixture()
def db(monkeypatch):
    from backend.config import settings as cfg
    from backend.services.db import initialize_database

    tmp = tempfile.mktemp(suffix=".sqlite3")
    monkeypatch.setattr(cfg, "APP_DB_PATH", tmp)
    initialize_database()
    return tmp


def test_upsert_and_get_roundtrip(db):
    n = hs.upsert_holdings(
        "2026-08-10",
        [
            {"symbol": "005930", "qty": 100, "avg_price": 70000, "current_price": 71000},
            {"symbol": "000660", "qty": 50, "avg_price": 120000, "current_price": 119000},
        ],
    )
    assert n == 2
    snap = hs.get_holdings("2026-08-10")
    assert set(snap.keys()) == {hs.norm_symbol("005930"), hs.norm_symbol("000660")}
    assert snap[hs.norm_symbol("005930")]["qty"] == 100
    assert snap[hs.norm_symbol("005930")]["avg_price"] == 70000
    assert snap[hs.norm_symbol("005930")]["market_price"] == 71000


def test_upsert_idempotent(db):
    hs.upsert_holdings("2026-08-10", [{"symbol": "005930", "qty": 100, "avg_price": 70000}])
    hs.upsert_holdings("2026-08-10", [{"symbol": "005930", "qty": 80, "avg_price": 69000}])
    snap = hs.get_holdings("2026-08-10")
    assert len(snap) == 1
    assert snap[hs.norm_symbol("005930")]["qty"] == 80  # 재캡처 시 최신으로 덮어씀(idempotent)


def test_filters_zero_qty_and_empty_symbol(db):
    n = hs.upsert_holdings(
        "2026-08-10",
        [
            {"symbol": "005930", "qty": 0, "avg_price": 70000},   # qty 0 제외
            {"symbol": "", "qty": 100, "avg_price": 70000},        # 심볼 없음 제외
            {"symbol": "000660", "qty": 50, "avg_price": 120000},  # 유효
        ],
    )
    assert n == 1
    assert set(hs.get_holdings("2026-08-10").keys()) == {hs.norm_symbol("000660")}


def test_capture_from_balance_parses_kis_output1(db):
    balance = {
        "output1": [
            {"pdno": "005930", "prdt_name": "삼성전자", "hldg_qty": "100",
             "pchs_avg_pric": "70000", "prpr": "71000"},
            {"pdno": "000660", "prdt_name": "SK하이닉스", "hldg_qty": "50",
             "pchs_avg_pric": "120000", "prpr": "119000"},
        ],
        "output2": [{"tot_evlu_amt": "10000000"}],
    }
    n = hs.capture_from_balance("2026-08-10", balance)
    assert n == 2
    snap = hs.get_holdings("2026-08-10")
    assert snap[hs.norm_symbol("005930")]["avg_price"] == 70000
    assert snap[hs.norm_symbol("005930")]["market_price"] == 71000
    assert snap[hs.norm_symbol("000660")]["qty"] == 50


def test_has_snapshot(db):
    assert hs.has_snapshot("2026-08-10") is False
    hs.upsert_holdings("2026-08-10", [{"symbol": "005930", "qty": 100, "avg_price": 70000}])
    assert hs.has_snapshot("2026-08-10") is True
    assert hs.has_snapshot("2026-08-11") is False  # 다른 날은 없음
