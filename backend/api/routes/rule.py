"""Rule System API — Base RulePack, Risk Profile Pack, Rule Composition."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.engine.rule_resolver import (
    get_active_base_rulepack,
    get_active_profile_pack,
    get_active_daily_plan,
    get_symbol_overrides,
    resolve_symbol_rule,
)
from ...services.engine.rule_cache import get_all_cached, get_meta
from ...services.db import get_connection
from ...services.settings_store import get_setting

router = APIRouter(prefix="/api/v1/rule", tags=["rule"])
logger = logging.getLogger("RuleAPI")


def _global_risk() -> dict[str, Any]:
    return {
        "daily_loss_limit": float(get_setting("risk.daily_loss_limit_percent", -2.0) or -2.0),
        "max_positions": int(get_setting("risk.max_positions", 5) or 5),
        "max_position_rate_per_stock": float(get_setting("risk.max_position_rate_per_stock", 0.10) or 0.10),
        "force_exit_time": _clock_with_seconds(get_setting("risk.force_exit_time", "15:20") or "15:20", "15:20:00"),
        "new_entry_cutoff_time": _clock_with_seconds(
            get_setting("risk.new_entry_cutoff_time", "15:10") or "15:10",
            "15:10:00",
        ),
    }


def _clock_with_seconds(value: Any, default: str) -> str:
    """Normalize HH:MM settings into HH:MM:SS rule values."""
    text = str(value or "").strip()
    parts = text.split(":")
    if len(parts) == 2 and all(part.isdigit() for part in parts):
        return f"{int(parts[0]):02d}:{int(parts[1]):02d}:00"
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        return f"{int(parts[0]):02d}:{int(parts[1]):02d}:{int(parts[2]):02d}"
    return default


@router.get("/base")
def get_base_rulepack():
    return {"ok": True, "payload": get_active_base_rulepack()}


@router.get("/base/list")
def list_base_rulepacks():
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, version, is_active, created_at FROM base_rulepacks ORDER BY created_at DESC"
        ).fetchall()
    return {"ok": True, "payload": [dict(r) for r in rows]}


@router.get("/profiles")
def get_profile_pack():
    pack = get_active_profile_pack()
    return {"ok": True, "payload": pack}


@router.get("/profiles/list")
def list_profile_packs():
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, version, is_active, created_at FROM risk_profile_packs ORDER BY created_at DESC"
        ).fetchall()
    return {"ok": True, "payload": [dict(r) for r in rows]}


class ProfilePackUpdate(BaseModel):
    profiles: dict[str, Any]


@router.put("/profiles")
def update_profile_pack(body: ProfilePackUpdate):
    """프로필 값 수정 → 새 버전 자동 생성 + 활성화."""
    _PROFILES = ("LOW_VOL", "MID_VOL", "HIGH_VOL", "THEME_SPIKE")
    for p in _PROFILES:
        if p not in body.profiles:
            raise HTTPException(status_code=400, detail=f"Missing profile: {p}")

    # 현재 활성 pack의 버전 조회해 다음 버전 계산
    with get_connection() as conn:
        row = conn.execute(
            "SELECT version FROM risk_profile_packs WHERE is_active = 1 ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    current_version = row["version"] if row else "1.0"
    try:
        major, minor = current_version.split(".")
        new_version = f"{major}.{int(minor) + 1}"
    except Exception:
        new_version = "1.1"

    new_id = f"profile-v{new_version}"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    with get_connection() as conn:
        # 기존 활성 pack 비활성화
        conn.execute("UPDATE risk_profile_packs SET is_active = 0")
        # 신규 버전 삽입
        conn.execute(
            "INSERT INTO risk_profile_packs (id, version, profiles, created_at, is_active) VALUES (?, ?, ?, ?, 1)",
            (new_id, new_version, json.dumps(body.profiles, ensure_ascii=False), now),
        )

    logger.info("SUCCESS: [RuleAPI] profile pack updated id=%s version=%s", new_id, new_version)
    return {"ok": True, "payload": {"id": new_id, "version": new_version}}


@router.get("/composition/today")
def get_rule_composition_today():
    """오늘 캐시된 전체 종목 최종 룰 반환."""
    cached = get_all_cached()
    meta = get_meta()
    return {"ok": True, "payload": {"meta": meta, "compositions": cached}}


@router.get("/composition/{symbol_code}")
def get_rule_composition_symbol(symbol_code: str):
    """특정 종목 최종 룰 미리보기 (캐시 없어도 즉시 계산)."""
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")

    base = get_active_base_rulepack()
    pack = get_active_profile_pack()
    plan = get_active_daily_plan(today)
    overrides = get_symbol_overrides()
    risk = _global_risk()

    final_rule = resolve_symbol_rule(
        symbol_code=symbol_code,
        base_rulepack=base,
        profile_pack=pack,
        daily_plan=plan,
        symbol_overrides=overrides,
        global_risk=risk,
        trade_date=today,
    )
    return {"ok": True, "payload": final_rule}
