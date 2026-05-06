"""Engine Test API for manual S1-S5 backend checks."""

from __future__ import annotations

import logging
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ...api.dependencies import require_console_user
from ...services.engine.pipeline_audit import get_recent_pipeline_runs

logger = logging.getLogger("BackendEngineTestAPI")

router = APIRouter(
    prefix="/api/v1/engine",
    tags=["engine-test"],
    dependencies=[Depends(require_console_user)],
)

_LOG_FILE = Path(__file__).resolve().parents[3] / "logs" / "server.log"
_KST = ZoneInfo("Asia/Seoul")


@router.post("/token-refresh", summary="S1: KIS 토큰 수동 갱신")
async def token_refresh():
    """Invalidate the cached KIS access token and request a fresh token."""
    logger.info("START: POST /api/v1/engine/token-refresh (manual)")
    try:
        from ...services.kis.common.client import kis_client

        kis_client.token = None
        kis_client.token_expires_at = 0.0
        token = await kis_client.get_token()

        logger.info("SUCCESS: POST /api/v1/engine/token-refresh")
        return {
            "ok": True,
            "source": "backend",
            "live": True,
            "payload": {
                "step": "S1",
                "result": "KIS 토큰 갱신 완료",
                "token_preview": f"{str(token)[:8]}..." if token else "none",
            },
        }
    except Exception as exc:
        logger.error("FAIL: POST /api/v1/engine/token-refresh - %s", exc)
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": str(exc), "source": "backend", "live": True},
        )


@router.get("/logs", summary="서버 로그 최근 N줄 조회")
async def get_engine_logs(
    lines: int = Query(default=80, ge=10, le=500),
    filter: str = Query(default="", description="포함할 키워드 (빈 문자열이면 전체)"),
):
    """Return recent server.log lines, optionally filtered by a case-insensitive keyword."""
    try:
        payload_path = str(_LOG_FILE)
        if not _LOG_FILE.exists():
            logger.info("SUCCESS: GET /api/v1/engine/logs log_file_missing path=%s", _LOG_FILE)
            return {
                "ok": True,
                "source": "backend",
                "live": True,
                "payload": {
                    "lines": [],
                    "total": 0,
                    "log_path": payload_path,
                    "exists": False,
                    "message": f"로그 파일을 찾을 수 없습니다: {payload_path}",
                },
            }

        with _LOG_FILE.open("r", encoding="utf-8", errors="replace") as log_file:
            all_lines = log_file.readlines()

        if not all_lines:
            logger.info("SUCCESS: GET /api/v1/engine/logs empty path=%s", _LOG_FILE)
            return {
                "ok": True,
                "source": "backend",
                "live": True,
                "payload": {
                    "lines": [],
                    "total": 0,
                    "log_path": payload_path,
                    "exists": True,
                    "message": f"서버 로그 파일은 비어 있습니다: {payload_path}",
                },
            }

        recent = all_lines[-min(len(all_lines), lines * 5):]
        if filter:
            keyword = filter.lower()
            recent = [line for line in recent if keyword in line.lower()]

        result_lines = [line.rstrip("\n") for line in recent[-lines:]]
        message = (
            f"필터와 일치하는 로그가 없습니다: {filter}"
            if not result_lines and filter
            else f"서버 로그 {len(result_lines)}줄을 불러왔습니다."
        )

        logger.info("SUCCESS: GET /api/v1/engine/logs returned=%d", len(result_lines))
        return {
            "ok": True,
            "source": "backend",
            "live": True,
            "payload": {
                "lines": result_lines,
                "total": len(result_lines),
                "log_path": payload_path,
                "exists": True,
                "message": message,
            },
        }
    except Exception as exc:
        logger.error("FAIL: GET /api/v1/engine/logs - %s", exc)
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": str(exc), "source": "backend", "live": True},
        )


def _today_kst() -> str:
    """Return today's KST date for read-only Diagnostics audit queries."""
    return datetime.now(_KST).strftime("%Y-%m-%d")


def _to_kst_display(value: str | None) -> str:
    """Convert an ISO timestamp to a compact KST display string.

    Args:
        value: ISO timestamp persisted in pipeline_run_audit.
    """
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
        return parsed.astimezone(_KST).strftime("%Y-%m-%d %H:%M:%S KST")
    except ValueError:
        return str(value)


def _audit_step_dom_id(step: str) -> str:
    """Map persisted audit step labels to Diagnostics card ids.

    Args:
        step: Pipeline step label from pipeline_run_audit.
    """
    normalized = str(step or "").strip().upper().replace("_", "-")
    mapping = {"S5-V": "s5v", "S5-A": "s5a"}
    return mapping.get(normalized, normalized.lower())


def _decorate_audit_run(run: dict) -> dict:
    """Add UI-friendly fields while preserving raw pipeline audit columns.

    Args:
        run: Raw audit row returned by get_recent_pipeline_runs.
    """
    item = dict(run)
    item["step_id"] = _audit_step_dom_id(item.get("step", ""))
    item["started_at_kst"] = _to_kst_display(item.get("started_at"))
    item["finished_at_kst"] = _to_kst_display(item.get("finished_at"))
    return item


@router.get("/audit/today", summary="오늘 pipeline_run_audit 조회")
async def get_today_pipeline_audit(limit: int = Query(default=50, ge=1, le=200)):
    """Return today's pipeline_run_audit rows for Diagnostics cards."""
    today = _today_kst()
    endpoint = "/api/v1/engine/audit/today"
    logger.info("START: GET %s trade_date=%s limit=%d", endpoint, today, limit)
    try:
        runs = [_decorate_audit_run(row) for row in get_recent_pipeline_runs(today, limit=limit)]
        by_step = {}
        for run in runs:
            step_id = run.get("step_id")
            if step_id and step_id not in by_step:
                by_step[step_id] = run

        logger.info("SUCCESS: GET %s rows=%d", endpoint, len(runs))
        return {
            "ok": True,
            "source": "backend",
            "live": True,
            "payload": {"trade_date": today, "runs": runs, "by_step": by_step},
        }
    except Exception as exc:
        logger.error("FAIL: GET %s - %s", endpoint, exc)
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": str(exc), "source": "backend", "live": True},
        )
