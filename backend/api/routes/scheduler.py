"""Scheduler 상태 조회 API.

GET /api/v1/scheduler/status
  - 등록된 job 목록, next_run_time, 스케줄러 실행 여부를 반환한다.
  - 인증: require_console_user (콘솔 세션 필요)
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends

from ...api.dependencies import require_console_user
from ...services.engine.pipeline_audit import get_recent_pipeline_runs
from ...services.scheduler import get_schedule_skip_today_status, scheduler_instance

logger = logging.getLogger("SchedulerAPI")
router = APIRouter(prefix="/api/v1/scheduler", tags=["scheduler"])


@router.get("/status")
async def get_scheduler_status(
    _user: Annotated[dict, Depends(require_console_user)],
) -> dict:
    """등록된 스케줄 job 목록과 스케줄러 실행 상태를 반환한다.

    Returns:
        표준 envelope: {ok, source, live, payload: {jobs, running}}
        - jobs: 등록된 job 목록 (id, name, next_run_time)
        - running: 스케줄러 실행 중 여부
    """
    logger.info("START: GET /api/v1/scheduler/status")
    try:
        running = scheduler_instance.running

        jobs = []
        for job in scheduler_instance.get_jobs():
            next_run = getattr(job, "next_run_time", None)
            if next_run is None:
                next_run = getattr(job, "next_fire_time", None)
            jobs.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run_time": next_run.isoformat() if next_run else None,
                    "timezone": "Asia/Seoul",
                }
            )

        skip_today = get_schedule_skip_today_status()
        today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
        last_run = None
        last_run_step = None
        last_run_status = None
        try:
            runs = get_recent_pipeline_runs(today, limit=20)
            last_s1 = next((row for row in runs if str(row.get("step_id") or "") == "s1"), None)
            if last_s1:
                last_run = last_s1.get("finished_at_kst") or last_s1.get("started_at_kst") or last_s1.get("finished_at") or last_s1.get("started_at")
                last_run_step = last_s1.get("step")
                last_run_status = last_s1.get("status")
        except Exception as exc:
            logger.warning("WARN: GET /api/v1/scheduler/status last_run lookup failed - %s", exc)

        payload = {
            "jobs": jobs,
            "running": running,
            "timezone": "Asia/Seoul",
            "schedule_skip_today": skip_today,
            "last_run": last_run,
            "last_run_step": last_run_step,
            "last_run_status": last_run_status,
        }
        logger.info("SUCCESS: GET /api/v1/scheduler/status — running=%s, jobs=%d", running, len(jobs))
        return {
            "ok": True,
            "source": "scheduler",
            "live": True,
            "payload": payload,
        }
    except Exception as exc:
        logger.error("FAIL: GET /api/v1/scheduler/status — %s", exc)
        raise
