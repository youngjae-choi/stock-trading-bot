"""Shared FastAPI dependencies for authentication and authorization."""

from __future__ import annotations

from fastapi import Cookie, HTTPException, status
from fastapi.responses import JSONResponse

from ..config import get_kis_config_status
from ..services.auth_service import SESSION_COOKIE_NAME, get_session_user


def kis_config_error_response(endpoint: str) -> JSONResponse:
    """Return a clear JSON response when KIS credentials are missing."""
    config_status = get_kis_config_status()
    return JSONResponse(
        status_code=503,
        content={
            "ok": False,
            "error": {
                "code": "KIS_CONFIG_MISSING",
                "message": "KIS API credentials are not configured.",
                "missing_fields": config_status["missing"],
                "endpoint": endpoint,
            },
        },
    )


async def require_console_user(dantabot_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME)) -> dict:
    """Require a valid console session cookie and return the current user."""
    user = get_session_user(dantabot_session)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="LOGIN_REQUIRED")
    return user
