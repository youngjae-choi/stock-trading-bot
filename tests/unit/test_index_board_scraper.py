"""index-board.space 스크래퍼 파싱 단위 테스트 (고정 HTML fixture, 네트워크 의존 제거)."""
from pathlib import Path

from backend.services.engine.index_board_scraper import parse_briefings, select_latest

FIXTURE = Path(__file__).parent.parent / "fixtures" / "index_board_briefing_sample.html"


def test_parse_extracts_pre_and_post():
    html = FIXTURE.read_text(encoding="utf-8")
    items = parse_briefings(html)
    types = {(b["type"], b["market"]) for b in items}
    assert ("pre", "kospi") in types
    assert ("post", "nasdaq") in types


def test_parse_text_content():
    html = FIXTURE.read_text(encoding="utf-8")
    items = parse_briefings(html)
    pre = select_latest(items, "pre", "kospi")
    assert pre is not None
    assert "코스피" in pre["text"]
    assert pre["generated_at"].startswith("2026-06-12")


def test_select_latest_picks_newest():
    items = [
        {"text": "old", "type": "pre", "market": "kospi", "generated_at": "2026-06-12T02:52:00"},
        {"text": "new", "type": "pre", "market": "kospi", "generated_at": "2026-06-12T08:56:00"},
    ]
    assert select_latest(items, "pre", "kospi")["text"] == "new"


def test_select_latest_missing_returns_none():
    assert select_latest([], "pre", "kospi") is None


def test_parse_empty_html_returns_empty():
    assert parse_briefings("<html></html>") == []
