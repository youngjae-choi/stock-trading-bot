"""Alert routes."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ...config import telegram_enabled
from ...services.alert_service import send_telegram_alert
from ..models import TelegramTestRequest

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])


@router.post("/telegram/test")
async def telegram_test(payload: TelegramTestRequest):
    if not telegram_enabled():
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "Telegram settings are missing. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID."},
        )

    ok = await send_telegram_alert("KIS ALERT TEST", payload.message)
    if ok:
        return {"ok": True}
    return JSONResponse(status_code=502, content={"ok": False, "error": "Telegram API request failed"})
