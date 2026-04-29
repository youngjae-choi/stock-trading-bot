"""Alert integrations (telegram)."""

from __future__ import annotations

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
