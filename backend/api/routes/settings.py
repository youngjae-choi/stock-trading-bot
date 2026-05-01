"""System settings routes backed by SQLite."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ...api.dependencies import require_console_user
from ...services.settings_store import list_settings, upsert_setting

logger = logging.getLogger("BackendSettingsAPI")
router = APIRouter(prefix="/api/v1/settings", tags=["settings"], dependencies=[Depends(require_console_user)])


class SettingUpdateRequest(BaseModel):
    """Request body for creating or updating a system setting."""

    value: Any
    value_type: str = "json"
    description: str = ""


@router.get("")
async def get_settings():
    """Return persisted system settings for the console."""
    logger.info("START: GET /api/v1/settings")
    payload = {"items": list_settings()}
    logger.info("SUCCESS: GET /api/v1/settings")
    return {"ok": True, "source": "backend", "live": False, "payload": payload}


@router.put("/{key}")
async def put_setting(key: str, request: SettingUpdateRequest, user: dict = Depends(require_console_user)):
    """Persist one system setting and identify the updating user."""
    logger.info("START: PUT /api/v1/settings/%s", key)
    payload = upsert_setting(key, request.value, request.value_type, request.description, user["username"])
    logger.info("SUCCESS: PUT /api/v1/settings/%s", key)
    return {"ok": True, "source": "backend", "live": False, "payload": payload}
