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


def test_live_endpoint_payload_structure(monkeypatch):
    _reset_cache()

    async def fake_scrape(*args, **kwargs):
        return {
            "ok": True,
            "morning": {"text": "장전 시황", "type": "pre", "market": "kospi", "generated_at": "2026-06-13T08:00:00Z"},
            "evening": {"text": "장후 시황", "type": "post", "market": "nasdaq", "generated_at": "2026-06-13T21:47:00Z"},
            "cached": False,
        }

    # 라우트 모듈이 import한 이름을 monkeypatch
    import backend.api.routes.market_briefing as route_mod
    monkeypatch.setattr(route_mod, "scrape_both_live", fake_scrape)

    client = TestClient(main_mod.app)
    resp = client.get("/api/v1/market-briefing/live")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "payload" in body
    assert body["payload"]["morning"]["text"] == "장전 시황"
    assert body["payload"]["evening"]["text"] == "장후 시황"
    assert body["payload"]["cached"] is False
