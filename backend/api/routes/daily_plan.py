"""Daily Trading Plan API."""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException

from ...services.engine.daily_plan import (
    get_today_daily_plan,
    run_daily_plan_generation,
    _validate_plan,
)
from ...services.db import get_connection

router = APIRouter(prefix="/api/v1/daily-plan", tags=["daily-plan"])
logger = logging.getLogger("DailyPlanAPI")


def _today_kst() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


@router.get("/today")
def get_today():
    plan = get_today_daily_plan(_today_kst())
    return {"ok": True, "payload": plan}


@router.get("/{date}")
def get_by_date(date: str):
    plan = get_today_daily_plan(date)
    if not plan:
        raise HTTPException(status_code=404, detail="Daily plan not found")
    return {"ok": True, "payload": plan}


@router.post("/generate")
async def generate():
    """S5 수동 즉시 실행 — 장중(09:00~15:30 KST) 금지."""
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    market_start = now_kst.replace(hour=9, minute=0, second=0, microsecond=0)
    market_end = now_kst.replace(hour=15, minute=30, second=0, microsecond=0)
    if market_start <= now_kst <= market_end:
        logger.warning("WARN: [DailyPlanAPI] manual generation blocked during market hours")
        raise HTTPException(
            status_code=403,
            detail="장중(09:00~15:30 KST) 수동 재실행 금지. 장 종료 후 실행하세요.",
        )
    result = await run_daily_plan_generation(
        trade_date=_today_kst(),
        creation_mode="manual",
        created_by="user",
    )
    return {"ok": True, "payload": result}


@router.post("/validate")
async def validate_plan():
    """오늘 draft plan 검증만 실행 (활성화 없음)."""
    plan = get_today_daily_plan(_today_kst())
    if not plan:
        raise HTTPException(status_code=404, detail="No plan found for today")
    validation = _validate_plan({
        "trading_intensity": plan.get("trading_intensity"),
        "new_entry_allowed": plan.get("new_entry_allowed"),
        "symbol_assignments": plan.get("symbol_assignments", []),
        "daily_overrides": plan.get("daily_overrides", {}),
    })
    all_pass = all(v == "pass" for v in validation.values())
    return {"ok": True, "payload": {"validation": validation, "all_pass": all_pass}}


@router.post("/activate")
def activate():
    """검증 통과된 plan을 active 상태로 전환."""
    today = _today_kst()
    plan = get_today_daily_plan(today)
    if not plan:
        raise HTTPException(status_code=404, detail="No plan found for today")
    if plan.get("status") not in ("validated", "active"):
        raise HTTPException(status_code=400, detail=f"Plan status is '{plan.get('status')}', must be validated first")

    with get_connection() as conn:
        now = datetime.now().isoformat()
        conn.execute(
            "UPDATE daily_trading_plans SET status = 'active', activated_at = ? WHERE trade_date = ?",
            (now, today),
        )
    logger.info("SUCCESS: [DailyPlanAPI] activated trade_date=%s", today)
    return {"ok": True, "payload": {"trade_date": today, "status": "active"}}
