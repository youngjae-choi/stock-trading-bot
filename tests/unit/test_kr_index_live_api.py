"""Tests for GET /api/v1/market/kr-index-live (Today Control 라이브 국내지수)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

import backend.main as main_mod
import backend.api.routes.market as market_mod

client = TestClient(main_mod.app)

KST = ZoneInfo("Asia/Seoul")


def _snapshot_ok():
    return {
        "ok": True,
        "fetched_at": "2026-06-08T10:00:00+09:00",
        "kospi": {"code": "0001", "price": 2700.55, "change_rate": 1.23},
        "kosdaq": {"code": "1001", "price": 880.10, "change_rate": -0.45},
        "top10": [],
        "vol30_avg_change": 0.5,
        "avg_change": 0.5,
        "items": [],
        "sectors": [],
        "count": 0,
    }


def test_kr_index_live_maps_change_rate(monkeypatch):
    """(a) kospi/kosdaq price·change_rate가 payload에 정확히 매핑된다."""
    async def _fake_snapshot():
        return _snapshot_ok()

    monkeypatch.setattr(market_mod, "fetch_intraday_kr_market_snapshot", _fake_snapshot)

    r = client.get("/api/v1/market/kr-index-live")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    p = body["payload"]
    assert p["kospi"]["price"] == 2700.55
    assert p["kospi"]["change_rate"] == 1.23
    assert p["kosdaq"]["price"] == 880.10
    assert p["kosdaq"]["change_rate"] == -0.45
    assert "market_open" in p
    assert "as_of" in p


def test_market_open_true_during_trading_hours(monkeypatch):
    """(b) KST 거래일 09:00~15:30 사이면 market_open=True."""
    async def _fake_snapshot():
        return _snapshot_ok()

    monkeypatch.setattr(market_mod, "fetch_intraday_kr_market_snapshot", _fake_snapshot)
    # 2026-06-08 (월) 10:00 KST = 거래일 장중
    fixed = datetime(2026, 6, 8, 10, 0, tzinfo=KST)
    monkeypatch.setattr(market_mod, "_now_kst", lambda: fixed)

    r = client.get("/api/v1/market/kr-index-live")
    assert r.json()["payload"]["market_open"] is True


def test_market_open_false_before_open(monkeypatch):
    """(b) 거래일이라도 09:00 이전이면 market_open=False."""
    async def _fake_snapshot():
        return _snapshot_ok()

    monkeypatch.setattr(market_mod, "fetch_intraday_kr_market_snapshot", _fake_snapshot)
    fixed = datetime(2026, 6, 8, 8, 25, tzinfo=KST)  # 프리마켓
    monkeypatch.setattr(market_mod, "_now_kst", lambda: fixed)

    r = client.get("/api/v1/market/kr-index-live")
    assert r.json()["payload"]["market_open"] is False


def test_market_open_false_after_close(monkeypatch):
    """(b) 거래일이라도 15:30 이후면 market_open=False."""
    async def _fake_snapshot():
        return _snapshot_ok()

    monkeypatch.setattr(market_mod, "fetch_intraday_kr_market_snapshot", _fake_snapshot)
    fixed = datetime(2026, 6, 8, 16, 0, tzinfo=KST)
    monkeypatch.setattr(market_mod, "_now_kst", lambda: fixed)

    r = client.get("/api/v1/market/kr-index-live")
    assert r.json()["payload"]["market_open"] is False


def test_market_open_false_on_weekend(monkeypatch):
    """(b) 주말은 장중 시각이어도 market_open=False."""
    async def _fake_snapshot():
        return _snapshot_ok()

    monkeypatch.setattr(market_mod, "fetch_intraday_kr_market_snapshot", _fake_snapshot)
    fixed = datetime(2026, 6, 6, 10, 0, tzinfo=KST)  # 2026-06-06 토요일(현충일)
    monkeypatch.setattr(market_mod, "_now_kst", lambda: fixed)

    r = client.get("/api/v1/market/kr-index-live")
    assert r.json()["payload"]["market_open"] is False


def test_snapshot_exception_graceful(monkeypatch):
    """(c) 스냅샷 예외 시 ok=true 유지, price/change_rate는 None, market_open은 시간 기준."""
    async def _boom():
        raise RuntimeError("KIS down")

    monkeypatch.setattr(market_mod, "fetch_intraday_kr_market_snapshot", _boom)
    fixed = datetime(2026, 6, 8, 10, 0, tzinfo=KST)  # 거래일 장중
    monkeypatch.setattr(market_mod, "_now_kst", lambda: fixed)

    r = client.get("/api/v1/market/kr-index-live")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    p = body["payload"]
    assert p["kospi"]["price"] is None
    assert p["kospi"]["change_rate"] is None
    assert p["kosdaq"]["price"] is None
    assert p["kosdaq"]["change_rate"] is None
    assert p["market_open"] is True  # 시간 기준은 유지
