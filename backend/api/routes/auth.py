"""Authentication routes for the operations console."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel

from ...api.dependencies import require_console_user
from ...services.auth_service import (
    SESSION_COOKIE_NAME,
    authenticate_user,
    complete_mfa_enrollment,
    create_session,
    create_mfa_challenge,
    delete_session,
    mfa_methods_for_user,
    start_mfa_enrollment,
    verify_mfa_login,
)

logger = logging.getLogger("BackendAuthAPI")
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    """Login request body."""

    username: str
    password: str


class MfaEnrollStartRequest(BaseModel):
    """MFA enrollment start request body."""

    challenge_id: str
    method_type: str


class MfaVerifyRequest(BaseModel):
    """MFA verification request body."""

    challenge_id: str
    code: str = ""


def _set_session_cookie(response: Response, user_id: str) -> str:
    """Create a session and set the console session cookie."""
    session_id = create_session(user_id)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=60 * 60 * 12,
        path="/",
    )
    return session_id


@router.post("/login")
async def login(request: LoginRequest, response: Response):
    """Authenticate a console user and require MFA before setting the session cookie."""
    logger.info("START: /api/v1/auth/login username=%s", request.username)
    user = authenticate_user(request.username.strip(), request.password)
    if user is None:
        logger.warning("WARN: /api/v1/auth/login failed username=%s", request.username)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="INVALID_CREDENTIALS")

    methods = mfa_methods_for_user(user["id"])
    if not methods:
        challenge_id = create_mfa_challenge(user["id"], "enroll")
        logger.info("INFO: /api/v1/auth/login mfa enrollment required username=%s", user["username"])
        return {
            "ok": True,
            "source": "backend",
            "live": False,
            "payload": {
                "status": "mfa_enrollment_required",
                "challenge_id": challenge_id,
                "methods": [
                    {"method_type": "totp", "label": "인증 앱"},
                    {"method_type": "backup_codes", "label": "백업 코드"},
                ],
            },
        }

    challenge_id = create_mfa_challenge(user["id"], "login")
    logger.info("INFO: /api/v1/auth/login mfa required username=%s", user["username"])
    return {
        "ok": True,
        "source": "backend",
        "live": False,
        "payload": {
            "status": "mfa_required",
            "challenge_id": challenge_id,
            "methods": methods,
        },
    }


@router.post("/mfa/enroll/start")
async def mfa_enroll_start(request: MfaEnrollStartRequest):
    """Start MFA enrollment for the user's selected method."""
    logger.info("START: /api/v1/auth/mfa/enroll/start method=%s", request.method_type)
    payload = start_mfa_enrollment(request.challenge_id, request.method_type)
    if payload is None:
        logger.warning("WARN: /api/v1/auth/mfa/enroll/start invalid challenge or method")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="INVALID_MFA_ENROLLMENT")
    logger.info("SUCCESS: /api/v1/auth/mfa/enroll/start method=%s", request.method_type)
    return {"ok": True, "source": "backend", "live": False, "payload": payload}


@router.post("/mfa/enroll/verify")
async def mfa_enroll_verify(request: MfaVerifyRequest, response: Response):
    """Complete MFA enrollment and set the first authenticated session cookie."""
    logger.info("START: /api/v1/auth/mfa/enroll/verify")
    user = complete_mfa_enrollment(request.challenge_id, request.code)
    if user is None:
        logger.warning("WARN: /api/v1/auth/mfa/enroll/verify failed")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="INVALID_MFA_CODE")
    _set_session_cookie(response, user["id"])
    logger.info("SUCCESS: /api/v1/auth/mfa/enroll/verify username=%s", user["username"])
    return {"ok": True, "source": "backend", "live": False, "payload": {"user": {"username": user["username"], "role": user["role"]}}}


@router.post("/mfa/verify")
async def mfa_verify(request: MfaVerifyRequest, response: Response):
    """Verify a second factor and set the authenticated session cookie."""
    logger.info("START: /api/v1/auth/mfa/verify")
    user = verify_mfa_login(request.challenge_id, request.code)
    if user is None:
        logger.warning("WARN: /api/v1/auth/mfa/verify failed")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="INVALID_MFA_CODE")
    _set_session_cookie(response, user["id"])
    logger.info("SUCCESS: /api/v1/auth/mfa/verify username=%s", user["username"])
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
