"""Shared API dependencies/helpers."""

from __future__ import annotations

import logging

from fastapi.responses import JSONResponse

from ..config import get_kis_config_status

logger = logging.getLogger("BackendAPI")


def kis_config_error_response(endpoint: str) -> JSONResponse:
    config_status = get_kis_config_status()
    logger.error(
        "FAIL: %s - Missing KIS configuration: %s",
        endpoint,
        ", ".join(config_status["missing"]),
    )
    return JSONResponse(
        status_code=503,
        content={
            "ok": False,
            "error": {
                "code": "KIS_CONFIG_MISSING",
                "message": "KIS API credentials are not configured.",
                "missing_fields": config_status["missing"],
            },
        },
    )
