"""scrape_both_live + /api/v1/market-briefing/live 테스트.

네트워크 미접촉: index_board_scraper.fetch_html을 monkeypatch.
캐시 TTL 격리: 각 테스트 시작 시 _LIVE_CACHE 초기화.
"""

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

import backend.main as main_mod
from backend.services.engine import index_board_scraper as s

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "index_board_briefing_sample.html"


def _reset_cache():
    s._LIVE_CACHE["data"] = None
    s._LIVE_CACHE["ts"] = 0.0


def _load_html() -> str:
    return _FIXTURE.read_text(encoding="utf-8")


def test_scrape_both_live_parses_morning_and_evening(monkeypatch):
    _reset_cache()
    html = _load_html()

    async def fake_fetch(*args, **kwargs):
        return html

    monkeypatch.setattr(s, "fetch_html", fake_fetch)

    data = asyncio.run(s.scrape_both_live())
    assert data["ok"] is True
    assert data["cached"] is False
    assert data["morning"] is not None
    assert data["morning"]["type"] == "pre"
    assert data["morning"]["market"] == "kospi"
    assert data["morning"]["text"]
    assert data["evening"] is not None
    assert data["evening"]["type"] == "post"
    assert data["evening"]["market"] == "nasdaq"


def test_scrape_both_live_caches_second_call(monkeypatch):
    _reset_cache()
    html = _load_html()
    calls = {"n": 0}

    async def fake_fetch(*args, **kwargs):
        calls["n"] += 1
        return html

    monkeypatch.setattr(s, "fetch_html", fake_fetch)

    first = asyncio.run(s.scrape_both_live())
    second = asyncio.run(s.scrape_both_live())

    assert first["cached"] is False
    assert second["cached"] is True
    assert calls["n"] == 1  # fetch_html은 1회만 호출


def test_scrape_both_live_fetch_failure_returns_not_ok(monkeypatch):
    _reset_cache()

    async def fake_fetch(*args, **kwargs):
        return None

    monkeypatch.setattr(s, "fetch_html", fake_fetch)

    data = asyncio.run(s.scrape_both_live())
    assert data["ok"] is False
    assert data["morning"] is None
    assert data["evening"] is None
    assert data["cached"] is False


def test_live_endpoint_reads_db_only(monkeypatch):
    """웜 캐시면 화면 엔드포인트는 DB만 읽는다(스냅샷/스크랩 호출 금지) — A안 핵심."""
    import backend.api.routes.market_briefing as route_mod

    def fake_read(_trade_date):
        return {
            "ok": True,
            "morning": {"text": "장전 시황", "type": "pre", "market": "kospi", "generated_at": "2026-06-13T08:00:00Z"},
            "intraday": {"text": "장중 시황", "type": "regular", "market": "kospi", "generated_at": "2026-06-13T05:31:00Z"},
            "evening": {"text": "장후 시황", "type": "post", "market": "nasdaq", "generated_at": "2026-06-13T21:47:00Z"},
            "source": "db",
            "updated_at": "2026-06-13T00:31:00Z",
        }

    async def _no_snap(*args, **kwargs):
        raise AssertionError("웜 캐시면 snapshot_briefing_to_db(스크랩) 호출 금지")

    monkeypatch.setattr(route_mod, "read_briefing_db", fake_read)
    monkeypatch.setattr(route_mod, "snapshot_briefing_to_db", _no_snap)

    client = TestClient(main_mod.app)
    resp = client.get("/api/v1/market-briefing/live")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["payload"]["morning"]["text"] == "장전 시황"
    assert body["payload"]["intraday"]["text"] == "장중 시황"
    assert body["payload"]["evening"]["text"] == "장후 시황"
    assert body["payload"]["cached"] is True
    assert body["payload"]["source"] == "db"


def test_live_endpoint_cold_cache_snapshots_once(monkeypatch):
    """콜드 캐시(DB 빔)면 1회 스냅샷 후 DB 재조회하는 안전망."""
    import backend.api.routes.market_briefing as route_mod

    reads = {"n": 0}
    snapped = {"n": 0}

    def fake_read(_trade_date):
        reads["n"] += 1
        if reads["n"] == 1:  # 최초: 콜드
            return {"ok": False, "morning": None, "intraday": None, "evening": None, "source": "db", "updated_at": None}
        return {"ok": True, "morning": {"text": "채워짐"}, "intraday": None, "evening": None, "source": "db", "updated_at": "x"}

    async def fake_snap(_trade_date):
        snapped["n"] += 1
        return {"ok": True}

    monkeypatch.setattr(route_mod, "read_briefing_db", fake_read)
    monkeypatch.setattr(route_mod, "snapshot_briefing_to_db", fake_snap)

    client = TestClient(main_mod.app)
    resp = client.get("/api/v1/market-briefing/live")
    assert resp.status_code == 200
    assert snapped["n"] == 1        # 콜드일 때만 1회 스냅샷
    assert reads["n"] == 2          # 스냅샷 후 재조회
    assert resp.json()["payload"]["morning"]["text"] == "채워짐"
