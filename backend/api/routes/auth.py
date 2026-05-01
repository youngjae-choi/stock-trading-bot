"""Authentication routes for the operations console."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel

from ...api.dependencies import require_console_user
from ...services.auth_service import (
    SESSION_COOKIE_NAME,
    authenticate_user,
    create_session,
    delete_session,
)

logger = logging.getLogger("BackendAuthAPI")
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    """Login request body."""

    username: str
    password: str


@router.post("/login")
async def login(request: LoginRequest, response: Response):
    """Authenticate a console user and set an HTTP-only session cookie."""
    logger.info("START: /api/v1/auth/login username=%s", request.username)
    user = authenticate_user(request.username.strip(), request.password)
    if user is None:
        logger.warning("WARN: /api/v1/auth/login failed username=%s", request.username)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="INVALID_CREDENTIALS")

    session_id = create_session(user["id"])
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=60 * 60 * 12,
        path="/",
    )
    logger.info("SUCCESS: /api/v1/auth/login username=%s", user["username"])
    return {"ok": True, "source": "backend", "live": False, "payload": {"user": {"username": user["username"], "role": user["role"]}}}


@router.get("/me")
async def me(user: dict = Depends(require_console_user)):
    """Return the current authenticated console user."""
    return {"ok": True, "source": "backend", "live": False, "payload": {"user": {"username": user["username"], "role": user["role"]}}}


@router.post("/logout")
async def logout(response: Response, dantabot_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME)):
    """Clear the active session cookie and delete the server-side session."""
    logger.info("START: /api/v1/auth/logout")
    delete_session(dantabot_session)
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    logger.info("SUCCESS: /api/v1/auth/logout")
    return {"ok": True, "source": "backend", "live": False, "payload": {"logged_out": True}}
