"""Engine Test API for manual S1-S5 backend checks."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ...api.dependencies import require_console_user

logger = logging.getLogger("BackendEngineTestAPI")

router = APIRouter(
    prefix="/api/v1/engine",
    tags=["engine-test"],
    dependencies=[Depends(require_console_user)],
)

_LOG_FILE = Path(__file__).resolve().parents[3] / "logs" / "server.log"


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
    logger.info("START: GET /api/v1/engine/logs lines=%d filter=%s", lines, filter)
    try:
        if not _LOG_FILE.exists():
            logger.info("SUCCESS: GET /api/v1/engine/logs log_file_missing path=%s", _LOG_FILE)
            return {
                "ok": True,
                "source": "backend",
                "live": True,
                "payload": {"lines": [], "total": 0, "log_path": str(_LOG_FILE)},
            }

        with _LOG_FILE.open("r", encoding="utf-8", errors="replace") as log_file:
            all_lines = log_file.readlines()

        recent = all_lines[-min(len(all_lines), lines * 5):]
        if filter:
            keyword = filter.lower()
            recent = [line for line in recent if keyword in line.lower()]

        result_lines = [line.rstrip("\n") for line in recent[-lines:]]

        logger.info("SUCCESS: GET /api/v1/engine/logs returned=%d", len(result_lines))
        return {
            "ok": True,
            "source": "backend",
            "live": True,
            "payload": {
                "lines": result_lines,
                "total": len(result_lines),
                "log_path": str(_LOG_FILE),
            },
        }
    except Exception as exc:
        logger.error("FAIL: GET /api/v1/engine/logs - %s", exc)
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": str(exc), "source": "backend", "live": True},
        )
