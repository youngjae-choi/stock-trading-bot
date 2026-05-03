"""Symbol Override API."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.db import get_connection

router = APIRouter(prefix="/api/v1/symbol-overrides", tags=["symbol-overrides"])
logger = logging.getLogger("SymbolOverrideAPI")


class OverrideBody(BaseModel):
    symbol_name: str = ""
    default_profile: str = "MID_VOL"
    override_values: dict[str, Any] = {}
    is_active: bool = True


@router.get("")
def list_overrides():
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM symbol_overrides ORDER BY updated_at DESC").fetchall()
    return {"ok": True, "payload": [dict(r) for r in rows]}


@router.put("/{symbol_code}")
def upsert_override(symbol_code: str, body: OverrideBody):
    now = datetime.now(timezone.utc).isoformat()
    _PROFILES = ("LOW_VOL", "MID_VOL", "HIGH_VOL", "THEME_SPIKE")
    if body.default_profile not in _PROFILES:
        raise HTTPException(status_code=400, detail=f"Invalid profile: {body.default_profile}")

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM symbol_overrides WHERE symbol_code = ?", (symbol_code,)
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE symbol_overrides
                   SET symbol_name=?, default_profile=?, override_values=?, is_active=?, updated_at=?
                   WHERE symbol_code=?""",
                (body.symbol_name, body.default_profile,
                 json.dumps(body.override_values, ensure_ascii=False),
                 1 if body.is_active else 0, now, symbol_code),
            )
        else:
            conn.execute(
                """INSERT INTO symbol_overrides
                   (id, symbol_code, symbol_name, default_profile, override_values, is_active, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), symbol_code, body.symbol_name, body.default_profile,
                 json.dumps(body.override_values, ensure_ascii=False),
                 1 if body.is_active else 0, now, now),
            )
    logger.info("SUCCESS: [SymbolOverrideAPI] upserted symbol_code=%s", symbol_code)
    return {"ok": True, "payload": {"symbol_code": symbol_code}}


@router.delete("/{symbol_code}")
def delete_override(symbol_code: str):
    with get_connection() as conn:
        conn.execute("DELETE FROM symbol_overrides WHERE symbol_code = ?", (symbol_code,))
    return {"ok": True, "payload": {"symbol_code": symbol_code}}
