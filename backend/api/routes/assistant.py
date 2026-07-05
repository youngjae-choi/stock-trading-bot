"""콘솔 어시스턴트 — 화면 컨텍스트/대화를 날짜별 공유 MD에 기록·조회.

Anthropic API 미사용. 웹 콘솔이 현재 화면을 MD에 append하고, CLI의 Claude가 같은 파일을
읽어 답변을 append한다(턴제). 모든 쓰기는 콘솔 인증 뒤에서만.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ...api.dependencies import require_console_user
from ...services.console_chat_store import append_note, append_screenshot, read_chat

logger = logging.getLogger("ConsoleAssistantAPI")
router = APIRouter(
    prefix="/api/v1/assistant",
    tags=["assistant"],
    dependencies=[Depends(require_console_user)],
)


class NoteRequest(BaseModel):
    """패널에서 보내는 한 턴: 발화 + 현재 화면 컨텍스트."""

    note: str = ""
    screen_id: str = ""
    screen_context: Any = None
    date: str | None = None


@router.post("/note")
async def post_note(request: NoteRequest) -> dict:
    """현재 화면 컨텍스트+노트를 날짜별 MD에 append (작성자=PM)."""
    logger.info("START: POST /api/v1/assistant/note screen=%s", request.screen_id)
    res = append_note(
        note=request.note,
        screen_id=request.screen_id,
        screen_context=request.screen_context,
        author="PM",
        date_str=request.date,
    )
    logger.info("SUCCESS: POST /api/v1/assistant/note file=%s", res.get("file"))
    return {"ok": True, "payload": res}


class ScreenshotRequest(BaseModel):
    """카메라 버튼: DOM 스크린샷(dataURL) + 발화 + 화면 식별자."""

    image: str                       # "data:image/png;base64,..."
    screen_id: str = ""
    note: str = ""
    date: str | None = None


@router.post("/screenshot")
async def post_screenshot(request: ScreenshotRequest) -> dict:
    """DOM 스크린샷을 파일로 저장하고 MD에 이미지 참조를 append (작성자=PM)."""
    logger.info("START: POST /api/v1/assistant/screenshot screen=%s", request.screen_id)
    try:
        res = append_screenshot(
            image_data_url=request.image,
            screen_id=request.screen_id,
            note=request.note,
            author="PM",
            date_str=request.date,
        )
    except ValueError as exc:
        logger.warning("WARN: POST /api/v1/assistant/screenshot rejected: %s", exc)
        return {"ok": False, "error": str(exc)}
    logger.info(
        "SUCCESS: POST /api/v1/assistant/screenshot file=%s image=%s bytes=%s",
        res.get("file"), res.get("image"), res.get("bytes"),
    )
    return {"ok": True, "payload": res}


@router.get("/note")
async def get_note(date: str | None = Query(default=None)) -> dict:
    """날짜별 대화 MD 전체 내용 조회(패널 폴링용)."""
    content = read_chat(date)
    return {"ok": True, "payload": {"content": content, "date": date or "today"}}
