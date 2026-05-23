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

    elif data.startswith("approve_action_plan_"):
        approval_id = data[len("approve_action_plan_"):]
        now = _now_iso()
        try:
            import json as _json

            payload_json = "{}"
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT payload_json FROM human_approval_queue WHERE id = ?",
                    (approval_id,),
                ).fetchone()
                if row:
                    payload_json = row["payload_json"] or "{}"
                conn.execute(
                    "UPDATE human_approval_queue SET status = 'approved', decided_at = ? WHERE id = ?",
                    (now, approval_id),
                )
                conn.execute(
                    """INSERT INTO approval_decision_logs (id, request_id, action, reason, created_at)
                       VALUES (?, ?, 'approved', '텔레그램 승인', ?)""",
                    (str(__import__("uuid").uuid4()), approval_id, now),
                )
            applied_settings: list[str] = []
            try:
                payload = _json.loads(payload_json)
                settings_changes = payload.get("settings_changes") or {}
                if settings_changes:
                    from ...services.settings_store import upsert_setting

                    for key, change in settings_changes.items():
                        new_val = change.get("new")
                        reason = change.get("reason", "PM 텔레그램 승인")
                        if new_val is None:
                            continue
                        upsert_setting(
                            key=key,
                            value=new_val,
                            value_type="number",
                            description=reason,
                            actor="telegram_approval",
                        )
                        applied_settings.append(f"{key}={new_val}")
                        logger.info(
                            "INFO: telegram_webhook approved setting key=%s new=%s",
                            key,
                            new_val,
                        )
            except Exception as apply_exc:
                logger.warning("WARN: telegram_webhook settings apply failed reason=%s", apply_exc)
            logger.info("INFO: telegram_webhook approved action_plan approval_id=%s", approval_id)
            if applied_settings:
                await answer_telegram_callback(
                    callback_id,
                    f"✅ 액션 플랜 승인 완료. 설정 변경: {', '.join(applied_settings)}",
                )
            else:
                await answer_telegram_callback(callback_id, "✅ 액션 플랜이 승인되었습니다.")
        except Exception as exc:
            logger.error("FAIL: telegram_webhook approve action_plan approval_id=%s reason=%s", approval_id, exc)
            await answer_telegram_callback(callback_id, "오류가 발생했습니다.")

    elif data.startswith("reject_action_plan_"):
        approval_id = data[len("reject_action_plan_"):]
        now = _now_iso()
        try:
            import json as _json
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT payload_json FROM human_approval_queue WHERE id = ?",
                    (approval_id,),
                ).fetchone()
                conn.execute(
                    "UPDATE human_approval_queue SET status = 'rejected', decided_at = ? WHERE id = ?",
                    (now, approval_id),
                )
                conn.execute(
                    """INSERT INTO approval_decision_logs (id, request_id, action, reason, created_at)
                       VALUES (?, ?, 'rejected', '텔레그램 거절', ?)""",
                    (str(__import__("uuid").uuid4()), approval_id, now),
                )
                # 거절 시 해당 날짜의 learning_memories 비활성화 — S5가 반영하지 않도록
                if row:
                    try:
                        payload = _json.loads(row["payload_json"] or "{}")
                        trade_date = payload.get("trade_date")
                        if trade_date:
                            result = conn.execute(
                                "UPDATE learning_memories SET status = 'inactive' WHERE trade_date = ? AND status = 'active'",
                                (trade_date,),
                            )
                            deactivated = result.rowcount
                            logger.info(
                                "INFO: telegram_webhook rejected → deactivated learning_memories "
                                "approval_id=%s trade_date=%s count=%d",
                                approval_id, trade_date, deactivated,
                            )
                    except Exception as mem_exc:
                        logger.warning("WARN: telegram_webhook failed to deactivate memories reason=%s", mem_exc)
            logger.info("INFO: telegram_webhook rejected action_plan approval_id=%s", approval_id)
            await answer_telegram_callback(callback_id, "❌ 액션 플랜이 거절되었습니다. 학습 메모리가 비활성화됩니다.")
        except Exception as exc:
            logger.error("FAIL: telegram_webhook reject action_plan approval_id=%s reason=%s", approval_id, exc)
            await answer_telegram_callback(callback_id, "오류가 발생했습니다.")

    return {"ok": True}
