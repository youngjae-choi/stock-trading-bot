"""콘솔 어시스턴트 공유 대화 — 날짜별 MD 파일 저장소.

웹 콘솔이 현재 화면 컨텍스트+PM 입력을 날짜별 MD에 append하고, CLI의 Claude가 같은
파일을 읽어 "같은 화면을 보고" 답변을 append한다. Anthropic API 미사용(과금 0).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger("ConsoleChatStore")

# backend/services/console_chat_store.py → repo root = parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CHAT_DIR = _REPO_ROOT / "docs" / "agent-comm" / "console_chat"


def _today_kst() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")


def _hhmm_kst() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%H:%M")


def _normalize_date(date_str: str | None) -> str:
    """YYYYMMDD 또는 YYYY-MM-DD 허용 → YYYYMMDD. None이면 오늘(KST)."""
    if not date_str:
        return _today_kst()
    s = str(date_str).replace("-", "").strip()
    if len(s) != 8 or not s.isdigit():
        raise ValueError(f"date must be YYYYMMDD or YYYY-MM-DD: {date_str!r}")
    return s


def chat_file_path(date_str: str | None = None) -> Path:
    """날짜별 대화 MD 경로. 디렉터리는 없으면 생성."""
    _CHAT_DIR.mkdir(parents=True, exist_ok=True)
    return _CHAT_DIR / f"console_chat_{_normalize_date(date_str)}.md"


def append_note(
    *,
    note: str,
    screen_id: str = "",
    screen_context: Any = None,
    author: str = "PM",
    date_str: str | None = None,
) -> dict[str, Any]:
    """대화 한 턴을 날짜별 MD에 append한다.

    Args:
        note: 사용자(또는 Claude) 발화 텍스트.
        screen_id: 현재 화면 식별자(선택).
        screen_context: 화면 컨텍스트(dict/list/str). dict/list면 JSON 펜스로 첨부.
        author: "PM" | "Claude" 등 — 헤더 표식.
        date_str: 기록 대상 날짜(기본 오늘 KST).
    """
    path = chat_file_path(date_str)
    emoji = {"PM": "🧑 PM", "Claude": "🤖 Claude"}.get(author, author)
    head = f"\n## [{_hhmm_kst()}] {emoji}"
    if screen_id:
        head += f" @{screen_id}"
    body = "\n" + (note.strip() if note else "") + "\n"
    block = head + body
    if screen_context not in (None, "", {}, []):
        if isinstance(screen_context, (dict, list)):
            ctx = json.dumps(screen_context, ensure_ascii=False, indent=2)
        else:
            ctx = str(screen_context)
        block += "\n```json\n" + ctx + "\n```\n"
    # 파일 새로 만들 때 제목 1회
    new_file = not path.exists()
    with open(path, "a", encoding="utf-8") as f:
        if new_file:
            f.write(f"# 콘솔 어시스턴트 대화 — {_normalize_date(date_str)}\n")
        f.write(block)
    logger.info("SUCCESS: console_chat append author=%s screen=%s file=%s", author, screen_id, path.name)
    return {"ok": True, "file": path.name, "date": _normalize_date(date_str)}


def read_chat(date_str: str | None = None) -> str:
    """날짜별 대화 MD 전체 내용 반환. 없으면 빈 문자열."""
    path = chat_file_path(date_str)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")
