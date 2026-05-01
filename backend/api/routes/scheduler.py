"""Scheduler 상태 조회 API.

GET /api/v1/scheduler/status
  - 등록된 job 목록, next_run_time, 스케줄러 실행 여부를 반환한다.
  - 인증: require_console_user (콘솔 세션 필요)
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends

from ...api.dependencies import require_console_user
from ...services.scheduler import scheduler_instance

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
            next_run = job.next_run_time
            jobs.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run_time": next_run.isoformat() if next_run else None,
                }
            )

        payload = {"jobs": jobs, "running": running}
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
