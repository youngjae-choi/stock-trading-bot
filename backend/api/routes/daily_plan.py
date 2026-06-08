"""Daily Trading Plan API."""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query

from ...services.engine.daily_plan import (
    get_today_daily_plan,
    run_daily_plan_generation,
    _validate_plan,
)
from ...services.db import get_connection
from ...services.engine.pipeline_audit import finish_pipeline_run, normalize_trigger_source, start_pipeline_run
from .status_envelope import build_pipeline_read_envelope

router = APIRouter(prefix="/api/v1/daily-plan", tags=["daily-plan"])
logger = logging.getLogger("DailyPlanAPI")


def _today_kst() -> str:
    """Return today's Asia/Seoul date as YYYY-MM-DD."""
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


@router.get("/today")
def get_today(trade_date: str | None = Query(default=None)):
    """Return today's Daily Plan. trade_date를 전달하면 해당 날짜 기준으로 조회한다."""
    target = trade_date or _today_kst()
    plan = get_today_daily_plan(target)
    return build_pipeline_read_envelope(payload=plan, result=plan, trade_date=target)


@router.get("/{date}")
def get_by_date(date: str):
    """Return a Daily Plan for a specific date with explicit result state."""
    plan = get_today_daily_plan(date)
    if not plan:
        raise HTTPException(status_code=404, detail="Daily plan not found")
    return build_pipeline_read_envelope(payload=plan, result=plan, trade_date=date)


@router.post("/generate")
async def generate(
    trigger_source: str = Query(default="api_manual"),
    force: bool = Query(default=False, description="장중 차단 우회(운영자 인시던트 복구용)"),
):
    """S5 수동 즉시 실행 — 장중(09:00~15:30 KST) 금지. force=true면 우회(감사 로그 기록)."""
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    market_start = now_kst.replace(hour=9, minute=0, second=0, microsecond=0)
    market_end = now_kst.replace(hour=15, minute=30, second=0, microsecond=0)
    if market_start <= now_kst <= market_end:
        if not force:
            logger.warning("WARN: [DailyPlanAPI] manual generation blocked during market hours")
            raise HTTPException(
                status_code=403,
                detail="장중(09:00~15:30 KST) 수동 재실행 금지. 장 종료 후 실행하세요.",
            )
        logger.warning(
            "WARN: [DailyPlanAPI] 장중 강제 재실행(force=true) — 운영자 인시던트 복구 source=%s",
            trigger_source,
        )
    result = await run_daily_plan_generation(
        trade_date=_today_kst(),
        creation_mode="manual",
        created_by="console_user" if normalize_trigger_source(trigger_source) == "console_manual" else "api_user",
        trigger_source=trigger_source,
    )
    return {"ok": True, "payload": result}


@router.post("/validate")
async def validate_plan(trigger_source: str = Query(default="api_manual")):
    """오늘 draft plan 검증만 실행 (활성화 없음)."""
    today = _today_kst()
    safe_source = normalize_trigger_source(trigger_source)
    run_audit_id = start_pipeline_run(
        trade_date=today,
        step="S5-V",
        trigger_source=safe_source,
        display_source="manual-like-console" if safe_source == "console_manual" else safe_source,
    )
    plan = get_today_daily_plan(_today_kst())
    if not plan:
        finish_pipeline_run(run_id=run_audit_id, status="failed", message="No plan found for today")
        raise HTTPException(status_code=404, detail="No plan found for today")
    validation = _validate_plan({
        "trading_intensity": plan.get("trading_intensity"),
        "new_entry_allowed": plan.get("new_entry_allowed"),
        "symbol_assignments": plan.get("symbol_assignments", []),
        "daily_overrides": plan.get("daily_overrides", {}),
    })
    all_pass = all(v == "pass" for v in validation.values())
    finish_pipeline_run(
        run_id=run_audit_id,
        status="success" if all_pass else "failed",
        result_ref_id=str(plan.get("id") or ""),
        message="validation_pass" if all_pass else "validation_failed",
        metadata={"validation": validation, "trigger_source": safe_source},
    )
    return {"ok": True, "payload": {"validation": validation, "all_pass": all_pass, "trigger_source": safe_source}}


@router.post("/activate")
def activate(trigger_source: str = Query(default="api_manual")):
    """검증 통과된 plan을 active 상태로 전환."""
    today = _today_kst()
    safe_source = normalize_trigger_source(trigger_source)
    run_audit_id = start_pipeline_run(
        trade_date=today,
        step="S5-A",
        trigger_source=safe_source,
        display_source="manual-like-console" if safe_source == "console_manual" else safe_source,
    )
    plan = get_today_daily_plan(today)
    if not plan:
        finish_pipeline_run(run_id=run_audit_id, status="failed", message="No plan found for today")
        raise HTTPException(status_code=404, detail="No plan found for today")
    if plan.get("status") not in ("validated", "active"):
        finish_pipeline_run(run_id=run_audit_id, status="failed", result_ref_id=str(plan.get("id") or ""), message=f"invalid_status={plan.get('status')}")
        raise HTTPException(status_code=400, detail=f"Plan status is '{plan.get('status')}', must be validated first")

    with get_connection() as conn:
        now = datetime.now().isoformat()
        conn.execute(
            "UPDATE daily_trading_plans SET status = 'active', activated_at = ? WHERE trade_date = ?",
            (now, today),
        )
    logger.info("SUCCESS: [DailyPlanAPI] activated trade_date=%s", today)
    finish_pipeline_run(
        run_id=run_audit_id,
        status="success",
        result_ref_id=str(plan.get("id") or ""),
        message="activated",
        metadata={"trigger_source": safe_source},
    )
    return {"ok": True, "payload": {"trade_date": today, "status": "active", "trigger_source": safe_source}}
