"""Alert integrations (telegram)."""

from __future__ import annotations

from typing import Any

import httpx

from ..config import settings, telegram_enabled


async def send_telegram_alert(title: str, body: str) -> bool:
    if not telegram_enabled():
        return False

    token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.TELEGRAM_CHAT_ID
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    text = f"[{title}]\n{body}"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.post(url, json={"chat_id": chat_id, "text": text})
        return response.status_code == 200
    except Exception:
        return False


async def send_telegram_with_inline_button(
    text: str,
    button_text: str,
    callback_data: str,
) -> bool:
    """인라인 버튼이 포함된 텔레그램 메시지를 발송한다."""
    if not telegram_enabled():
        return False

    token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.TELEGRAM_CHAT_ID
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": {
            "inline_keyboard": [[{"text": button_text, "callback_data": callback_data}]]
        },
    }
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.post(url, json=payload)
        return response.status_code == 200
    except Exception:
        return False


async def answer_telegram_callback(callback_query_id: str, text: str = "") -> bool:
    """인라인 버튼 클릭 응답 (로딩 스피너 해제)."""
    if not telegram_enabled():
        return False
    token = settings.TELEGRAM_BOT_TOKEN
    url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            await client.post(url, json={"callback_query_id": callback_query_id, "text": text})
        return True
    except Exception:
        return False
