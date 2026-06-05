"""아침 거래 준비 자가진단 — S1~S5 파이프라인·활성 플랜·엔진 활성 점검.

문제(issues) 리스트만 반환한다. 알림 발송/스케줄 등록은 scheduler가 담당.
탐지 전용 — 자동복구는 하지 않는다(엔진 미활성은 워치독이 별도 자가복구).
"""

from __future__ import annotations

import logging
from typing import Any

from ..db import get_connection
from .daily_plan import get_today_daily_plan
from .decision_engine import decision_engine

logger = logging.getLogger("MorningDiagnostic")

_PIPELINE_STEPS = ("S1", "S2", "S3", "S4", "S5")
_CRITICAL_STEPS = ("S4", "S5")


def _latest_step_statuses(trade_date: str) -> dict[str, str]:
    """오늘 각 파이프라인 단계의 최신 status를 반환."""
    out: dict[str, str] = {}
    try:
        with get_connection() as conn:
            for step in _PIPELINE_STEPS:
                row = conn.execute(
                    "SELECT status FROM pipeline_run_audit WHERE trade_date = ? AND step = ? "
                    "ORDER BY started_at DESC LIMIT 1",
                    (trade_date, step),
                ).fetchone()
                if row is not None:
                    out[step] = str(row["status"])
    except Exception as exc:
        logger.warning("WARN: 파이프라인 status 조회 실패 — %s", exc)
    return out


def _active_plan(trade_date: str) -> dict[str, Any] | None:
    """오늘 active Daily Plan (status=active)만 반환, 없으면 None."""
    try:
        plan = get_today_daily_plan(trade_date)
        if plan and str(plan.get("status")) == "active":
            return plan
    except Exception as exc:
        logger.warning("WARN: 활성 플랜 조회 실패 — %s", exc)
    return None


def _plan_assignment_count(plan: dict[str, Any] | None) -> int:
    if not plan:
        return 0
    sa = plan.get("symbol_assignments")
    if isinstance(sa, list):
        return len(sa)
    return 0


def _engine_is_active() -> bool:
    try:
        return bool(decision_engine.is_active())
    except Exception as exc:
        logger.warning("WARN: 엔진 활성 조회 실패 — %s", exc)
        return False


def run_morning_diagnostic(trade_date: str) -> dict[str, Any]:
    """아침 거래 준비 자가진단. {trade_date, ok, issues:[{severity,alert_type,title,detail}]}."""
    issues: list[dict[str, str]] = []

    statuses = _latest_step_statuses(trade_date)
    for step in _PIPELINE_STEPS:
        st = statuses.get(step)
        if st != "success":
            sev = "CRITICAL" if step in _CRITICAL_STEPS else "WARNING"
            issues.append({
                "severity": sev,
                "alert_type": "morning_diagnostic",
                "title": f"{step} 미완료 ({st or '미실행'})",
                "detail": f"오늘 {step} 파이프라인 단계가 success가 아님 (status={st or 'none'}).",
            })

    plan = _active_plan(trade_date)
    if not plan:
        issues.append({
            "severity": "CRITICAL",
            "alert_type": "morning_diagnostic",
            "title": "활성 Daily Plan 없음",
            "detail": "오늘 active 상태 Daily Plan이 없어 매수가 불가합니다.",
        })
    elif _plan_assignment_count(plan) == 0:
        issues.append({
            "severity": "WARNING",
            "alert_type": "morning_diagnostic",
            "title": "Daily Plan 배정 종목 0",
            "detail": "플랜은 active이나 배정된 종목이 없습니다(매수 대상 없음).",
        })

    # 엔진은 플랜이 있을 때만 활성 의미가 있음 (플랜 없으면 위에서 이미 CRITICAL)
    if plan and not _engine_is_active():
        issues.append({
            "severity": "CRITICAL",
            "alert_type": "morning_diagnostic",
            "title": "Decision Engine 비활성",
            "detail": "활성 플랜이 있으나 매수 엔진이 꺼져 있습니다(워치독 자동복구 실패 의심).",
        })

    return {"trade_date": trade_date, "ok": len(issues) == 0, "issues": issues}
