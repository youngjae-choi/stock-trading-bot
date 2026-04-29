"""Health route."""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter

from ...config import get_kis_config_status
from ...utils import get_kis_rate_limiter_runtime_status

logger = logging.getLogger("BackendHealthAPI")
router = APIRouter()


@router.get("/health")
async def health_check():
    """Return backend liveness and KIS configuration status."""
    try:
        logger.info("START: /health")
        config_status = get_kis_config_status()
        kis_rate_limit_status = get_kis_rate_limiter_runtime_status()
        payload = {
            "status": "healthy",
            "timestamp": time.time(),
            "version": "0.3.0",
            "kis_configured": config_status["configured"],
            "missing_kis_config": config_status["missing"],
            "kis_rate_limit": kis_rate_limit_status,
        }
        logger.info("SUCCESS: /health")
        return payload
    except Exception as exc:
        logger.error("FAIL: /health - %s", str(exc))
        raise
