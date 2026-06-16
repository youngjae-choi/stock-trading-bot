"""콘솔 어시스턴트 날짜별 MD 저장소 — append/read 정합."""

import json

import backend.services.console_chat_store as store


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_CHAT_DIR", tmp_path / "console_chat")


def test_append_creates_dated_file_with_title(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    res = store.append_note(note="안녕", screen_id="today", date_str="2026-06-16")
    assert res["ok"] and res["date"] == "20260616"
    p = store.chat_file_path("20260616")
    assert p.exists() and p.name == "console_chat_20260616.md"
    text = p.read_text(encoding="utf-8")
    assert "# 콘솔 어시스턴트 대화 — 20260616" in text
    assert "🧑 PM @today" in text and "안녕" in text


def test_screen_context_json_fenced(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    ctx = {"win": 3, "loss": 4, "symbols": ["005930"]}
    store.append_note(note="분석해줘", screen_id="daily-results", screen_context=ctx, date_str="20260616")
    text = store.read_chat("20260616")
    assert "```json" in text
    # JSON 블록이 파싱 가능해야 함
    block = text.split("```json", 1)[1].split("```", 1)[0].strip()
    assert json.loads(block)["win"] == 3


def test_append_is_additive_and_author_marked(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    store.append_note(note="질문", author="PM", date_str="20260616")
    store.append_note(note="답변", author="Claude", date_str="20260616")
    text = store.read_chat("20260616")
    assert "🧑 PM" in text and "🤖 Claude" in text
    assert text.index("질문") < text.index("답변")  # 시간순 누적


def test_read_missing_returns_empty(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    assert store.read_chat("20260101") == ""


def test_invalid_date_rejected(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    try:
        store.chat_file_path("2026/6/16")
        assert False, "should raise"
    except ValueError:
        pass
