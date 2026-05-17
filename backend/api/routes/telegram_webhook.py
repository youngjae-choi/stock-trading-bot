"""Telegram webhook — 인라인 버튼 콜백 처리."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request

from ...services.alert_service import answer_telegram_callback
from ...services.db import get_connection

router = APIRouter(prefix="/api/v1/telegram", tags=["telegram"])
logger = logging.getLogger("TelegramWebhook")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.post("/webhook")
async def telegram_webhook(request: Request) -> dict[str, Any]:
    """텔레그램 봇 webhook — callback_query 처리.

    callback_data 형식: mute_stock_{stock_id}
    """
    try:
        body = await request.json()
    except Exception:
        return {"ok": True}

    callback = body.get("callback_query")
    if not callback:
        return {"ok": True}

    callback_id = callback.get("id", "")
    data = callback.get("data", "")
    logger.info("INFO: telegram_webhook callback_data=%s", data)

    if data.startswith("mute_stock_"):
        stock_id = data[len("mute_stock_"):]
        now = _now_iso()
        try:
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT name, code FROM dividend_stocks WHERE id = ? AND is_active = 1",
                    (stock_id,),
                ).fetchone()
                if row:
                    conn.execute(
                        "UPDATE dividend_stocks SET notification_muted = 1, updated_at = ? WHERE id = ?",
                        (now, stock_id),
                    )
                    name = row["name"]
                    logger.info("INFO: telegram_webhook muted stock_id=%s name=%s", stock_id, name)
                    await answer_telegram_callback(callback_id, f"✅ {name} 배당락일 알림이 꺼졌습니다.")
                else:
                    await answer_telegram_callback(callback_id, "종목을 찾을 수 없습니다.")
        except Exception as exc:
            logger.error("FAIL: telegram_webhook mute stock_id=%s reason=%s", stock_id, exc)
            await answer_telegram_callback(callback_id, "오류가 발생했습니다.")

    return {"ok": True}
