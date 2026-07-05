"""콘솔 어시스턴트 공유 대화 — 날짜별 MD 파일 저장소.

웹 콘솔이 현재 화면 컨텍스트+PM 입력을 날짜별 MD에 append하고, CLI의 Claude가 같은
파일을 읽어 "같은 화면을 보고" 답변을 append한다. Anthropic API 미사용(과금 0).
"""
from __future__ import annotations

import base64
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger("ConsoleChatStore")

# backend/services/console_chat_store.py → repo root = parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CHAT_DIR = _REPO_ROOT / "docs" / "agent-comm" / "console_chat"
_SHOTS_DIRNAME = "shots"
_MAX_IMAGE_BYTES = 8 * 1024 * 1024   # 8MB 가드 (base64 확장 후 페이로드도 방어)
_SHOT_RETENTION_DAYS = 7              # 오래된 스크린샷 자동 정리(용량 가드)
_DATA_URL_RE = re.compile(r"^data:image/(png|jpeg);base64,(.+)$", re.DOTALL)


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


def _shots_dir() -> Path:
    d = _CHAT_DIR / _SHOTS_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _prune_old_shots(retention_days: int = _SHOT_RETENTION_DAYS) -> None:
    """보존기간 지난 스크린샷 정리(용량/깃 노이즈 가드). 실패는 조용히 무시."""
    try:
        cutoff = time.time() - retention_days * 86400
        for p in _shots_dir().glob("shot_*"):
            try:
                if p.is_file() and p.stat().st_mtime < cutoff:
                    p.unlink()
            except OSError:
                pass
    except Exception:  # noqa: BLE001 — 정리 실패가 스크린샷 저장을 막지 않게
        pass


def append_screenshot(
    *,
    image_data_url: str,
    screen_id: str = "",
    note: str = "",
    author: str = "PM",
    date_str: str | None = None,
) -> dict[str, Any]:
    """DOM 스크린샷(dataURL PNG/JPEG)을 파일로 저장하고 MD에 이미지 참조를 append.

    CLI의 Claude가 MD에서 절대경로를 보고 PNG를 직접 Read해 실제 UI(색·폰트·레이아웃)를
    본다. 텍스트만 담던 append_note를 보완하는 "진짜 이미지" 경로.

    Args:
        image_data_url: "data:image/png;base64,..." 형식의 dataURL.
        screen_id: 현재 화면 식별자(선택).
        note: 함께 보낼 발화 텍스트(선택).
        author: "PM" | "Claude" 등 헤더 표식.
        date_str: 기록 대상 날짜(기본 오늘 KST).

    Raises:
        ValueError: dataURL 형식이 아니거나 이미지가 상한을 초과할 때.
    """
    m = _DATA_URL_RE.match(image_data_url or "")
    if not m:
        raise ValueError("image must be a data:image/png;base64 or jpeg dataURL")
    ext = "png" if m.group(1) == "png" else "jpg"
    try:
        raw = base64.b64decode(m.group(2), validate=True)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"invalid base64 image: {exc}") from exc
    if len(raw) > _MAX_IMAGE_BYTES:
        raise ValueError(f"image too large: {len(raw)} bytes > {_MAX_IMAGE_BYTES}")

    date = _normalize_date(date_str)
    ts = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%H%M%S")
    fname = f"shot_{date}_{ts}.{ext}"
    fpath = _shots_dir() / fname
    fpath.write_bytes(raw)
    _prune_old_shots()

    # MD append — CLI가 읽을 절대경로 + 패널/미리보기용 상대 이미지 참조.
    md_path = chat_file_path(date_str)
    rel = f"{_SHOTS_DIRNAME}/{fname}"
    emoji = {"PM": "🧑 PM", "Claude": "🤖 Claude"}.get(author, author)
    head = f"\n## [{_hhmm_kst()}] {emoji}"
    if screen_id:
        head += f" @{screen_id}"
    body = "\n" + (note.strip() if note else "(화면 스크린샷)") + "\n"
    block = head + body + f"\n📸 스크린샷(CLI가 Read): `{fpath}`\n\n![screenshot]({rel})\n"
    new_file = not md_path.exists()
    with open(md_path, "a", encoding="utf-8") as f:
        if new_file:
            f.write(f"# 콘솔 어시스턴트 대화 — {date}\n")
        f.write(block)
    logger.info(
        "SUCCESS: console_chat screenshot saved file=%s bytes=%d md=%s",
        fname, len(raw), md_path.name,
    )
    return {
        "ok": True, "file": md_path.name, "image": rel,
        "image_path": str(fpath), "bytes": len(raw), "date": date,
    }


def read_chat(date_str: str | None = None) -> str:
    """날짜별 대화 MD 전체 내용 반환. 없으면 빈 문자열."""
    path = chat_file_path(date_str)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")
