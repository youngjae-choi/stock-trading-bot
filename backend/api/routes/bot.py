"""Console-facing bot operation routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ...services.console_state import (
    get_api_audit_logs,
    get_console_overview,
    get_data_health,
    get_rulepack_today,
    record_api_audit_log,
    trigger_emergency_halt,
)

logger = logging.getLogger("BackendBotConsoleAPI")
router = APIRouter(prefix="/api/v1/bot", tags=["bot-console"])


def _build_logged_success_response(
    *,
    endpoint: str,
    method: str,
    payload: dict,
    source: str,
    message: str,
    feature_name: str,
    purpose: str,
    result_summary: str,
    mock: bool,
) -> dict:
    """Persist a success audit log entry and return the API response body."""
    logger.info("START: bot._build_logged_success_response - %s %s", method, endpoint)
    record_api_audit_log(
        endpoint,
        method,
        "success",
        source,
        message,
        live=not mock,
        status_code=200,
        feature_name=feature_name,
        purpose=purpose,
        result_summary=result_summary,
    )
    logger.info("SUCCESS: bot._build_logged_success_response - %s %s", method, endpoint)
    return {"ok": True, "mock": mock, "source": source, "live": not mock, "payload": payload}


def _build_logged_error_response(*, endpoint: str, method: str, error_message: str) -> JSONResponse:
    """Persist a failure audit log entry and return a JSON error response."""
    logger.error("FAIL: %s - %s", endpoint, error_message)
    record_api_audit_log(
        endpoint,
        method,
        "error",
        "backend",
        error_message,
        live=False,
        status_code=500,
    )
    return JSONResponse(status_code=500, content={"ok": False, "error": error_message, "source": "backend", "live": False})


@router.get("/overview")
async def get_bot_overview():
    """Return mock-safe overview data for the console dashboard."""
    endpoint = "/api/v1/bot/overview"
    try:
        logger.info("START: %s", endpoint)
        payload = get_console_overview()
        logger.info("SUCCESS: %s", endpoint)
        return _build_logged_success_response(
            endpoint=endpoint,
            method="GET",
            payload=payload,
            source="mock",
            message="Console overview served from mock-safe backend state.",
            feature_name="운영 개요 조회",
            purpose="운영 화면에서 엔진 상태와 리스크 상태를 한 번에 확인",
            result_summary="성공 mock 운영 개요와 오늘 상태 요약을 반환",
            mock=True,
        )
    except Exception as exc:
        return _build_logged_error_response(endpoint=endpoint, method="GET", error_message=f"Failed to load bot overview: {str(exc)}")


@router.get("/rulepack/today")
async def get_bot_rulepack_today():
    """Return today's rulepack summary for the console."""
    endpoint = "/api/v1/bot/rulepack/today"
    try:
        logger.info("START: %s", endpoint)
        payload = get_rulepack_today()
        logger.info("SUCCESS: %s", endpoint)
        return _build_logged_success_response(
            endpoint=endpoint,
            method="GET",
            payload=payload,
            source="mock",
            message="RulePack summary served from mock-safe backend state.",
            feature_name="오늘 RulePack 조회",
            purpose="당일 진입 규칙과 리스크 한도를 운영 화면에서 확인",
            result_summary="성공 오늘 RulePack 요약과 검증 상태를 반환",
            mock=True,
        )
    except Exception as exc:
        return _build_logged_error_response(endpoint=endpoint, method="GET", error_message=f"Failed to load rulepack: {str(exc)}")


@router.get("/data-health")
async def get_bot_data_health():
    """Return backend data-health details for the console."""
    endpoint = "/api/v1/bot/data-health"
    try:
        logger.info("START: %s", endpoint)
        payload = get_data_health()
        logger.info("SUCCESS: %s", endpoint)
        return _build_logged_success_response(
            endpoint=endpoint,
            method="GET",
            payload=payload,
            source="mock",
            message="Data health served without live KIS dependency.",
            feature_name="데이터 상태 점검",
            purpose="KIS, WebSocket, 런타임 연결 상태와 품질 점검 결과를 확인",
            result_summary="성공 mock 데이터 상태와 품질 점검 결과를 반환",
            mock=True,
        )
    except Exception as exc:
        return _build_logged_error_response(endpoint=endpoint, method="GET", error_message=f"Failed to load data health: {str(exc)}")


@router.post("/control/halt")
async def halt_bot_control():
    """Apply a mock-safe emergency halt state for the console."""
    endpoint = "/api/v1/bot/control/halt"
    try:
        logger.info("START: %s", endpoint)
        payload = trigger_emergency_halt()
        logger.info("SUCCESS: %s", endpoint)
        return _build_logged_success_response(
            endpoint=endpoint,
            method="POST",
            payload=payload,
            source="backend",
            message="Emergency halt request recorded by backend control API.",
            feature_name="긴급정지 실행",
            purpose="이상 징후 발생 시 신규 자동 주문을 즉시 차단",
            result_summary="성공 긴급정지를 기록하고 엔진 상태를 HALT로 전환",
            mock=True,
        )
    except Exception as exc:
        return _build_logged_error_response(endpoint=endpoint, method="POST", error_message=f"Failed to halt bot control: {str(exc)}")


@router.get("/api-logs")
async def get_bot_api_logs():
    """Return recent backend API audit logs for the admin console."""
    endpoint = "/api/v1/bot/api-logs"
    try:
        logger.info("START: %s", endpoint)
        record_api_audit_log(
            endpoint,
            "GET",
            "success",
            "backend",
            "Administrative API log feed requested.",
            live=False,
            status_code=200,
            feature_name="API 로그 조회",
            purpose="운영자가 최근 API 호출 목적과 결과를 빠르게 확인",
            result_summary="성공 최근 관리용 API 로그 목록을 반환",
        )
        payload = get_api_audit_logs()
        logger.info("SUCCESS: %s", endpoint)
        return {"ok": True, "mock": False, "source": "backend", "live": False, "payload": payload}
    except Exception as exc:
        return _build_logged_error_response(endpoint=endpoint, method="GET", error_message=f"Failed to load API logs: {str(exc)}")
