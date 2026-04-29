"""Mock console state for the static operations dashboard."""

from __future__ import annotations

import copy
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("BackendConsoleState")
_API_LOG_LIMIT = 50

_API_LOG_METADATA: dict[str, dict[str, str]] = {
    "/api/v1/bot/overview": {
        "feature_name": "운영 개요 조회",
        "purpose": "운영 화면에서 엔진 상태와 리스크 상태를 한 번에 확인",
        "result_summary": "성공 mock 운영 개요와 오늘 상태 요약을 반환",
    },
    "/api/v1/bot/rulepack/today": {
        "feature_name": "오늘 RulePack 조회",
        "purpose": "당일 진입 규칙과 리스크 한도를 운영 화면에서 확인",
        "result_summary": "성공 오늘 RulePack 요약과 검증 상태를 반환",
    },
    "/api/v1/bot/data-health": {
        "feature_name": "데이터 상태 점검",
        "purpose": "KIS, WebSocket, 런타임 연결 상태와 품질 점검 결과를 확인",
        "result_summary": "성공 mock 데이터 상태와 품질 점검 결과를 반환",
    },
    "/api/v1/bot/control/halt": {
        "feature_name": "긴급정지 실행",
        "purpose": "이상 징후 발생 시 신규 자동 주문을 즉시 차단",
        "result_summary": "성공 긴급정지를 기록하고 엔진 상태를 HALT로 전환",
    },
    "/api/v1/bot/api-logs": {
        "feature_name": "API 로그 조회",
        "purpose": "운영자가 최근 API 호출 목적과 결과를 빠르게 확인",
        "result_summary": "성공 최근 관리용 API 로그 목록을 반환",
    },
}


def _build_api_audit_log_entry(
    endpoint: str,
    method: str,
    status: str,
    source: str,
    message: str,
    *,
    live: bool,
    status_code: int,
    feature_name: str | None = None,
    purpose: str | None = None,
    result_summary: str | None = None,
) -> dict[str, Any]:
    """Build one API audit log entry while keeping legacy and human-readable fields together."""
    metadata = _API_LOG_METADATA.get(endpoint, {})
    called_at = _utc_now_iso()
    return {
        "endpoint": endpoint,
        "method": method.upper(),
        "status": status,
        "status_code": status_code,
        "source": source,
        "live": live,
        "timestamp": called_at,
        "called_at": called_at,
        "message": message,
        "feature_name": feature_name or metadata.get("feature_name", endpoint),
        "purpose": purpose or metadata.get("purpose", message),
        "api_name_or_path": f"{method.upper()} {endpoint}",
        "result_summary": result_summary or metadata.get("result_summary", message),
    }

_CONSOLE_STATE: dict[str, Any] = {
    "mode": "AUTO",
    "engine_status": "running",
    "emergency_halt": False,
    "mock_mode": True,
    "api_logs": [
        {
            "endpoint": "/api/v1/bot/overview",
            "method": "GET",
            "status": "success",
            "status_code": 200,
            "source": "mock",
            "live": False,
            "timestamp": "2026-04-29T07:45:00+09:00",
            "called_at": "2026-04-29T07:45:00+09:00",
            "message": "Console overview mock snapshot served.",
            "feature_name": "운영 개요 조회",
            "purpose": "운영 화면에서 엔진 상태와 리스크 상태를 한 번에 확인",
            "api_name_or_path": "GET /api/v1/bot/overview",
            "result_summary": "성공 mock 운영 개요와 오늘 상태 요약을 반환",
        },
        {
            "endpoint": "/api/v1/bot/rulepack/today",
            "method": "GET",
            "status": "success",
            "status_code": 200,
            "source": "mock",
            "live": False,
            "timestamp": "2026-04-29T08:45:00+09:00",
            "called_at": "2026-04-29T08:45:00+09:00",
            "message": "RulePack summary served from mock-safe backend state.",
            "feature_name": "오늘 RulePack 조회",
            "purpose": "당일 진입 규칙과 리스크 한도를 운영 화면에서 확인",
            "api_name_or_path": "GET /api/v1/bot/rulepack/today",
            "result_summary": "성공 오늘 RulePack 요약과 검증 상태를 반환",
        },
        {
            "endpoint": "/api/v1/bot/data-health",
            "method": "GET",
            "status": "success",
            "status_code": 200,
            "source": "mock",
            "live": False,
            "timestamp": "2026-04-29T09:00:00+09:00",
            "called_at": "2026-04-29T09:00:00+09:00",
            "message": "Data health served without live KIS dependency.",
            "feature_name": "데이터 상태 점검",
            "purpose": "KIS, WebSocket, 런타임 연결 상태와 품질 점검 결과를 확인",
            "api_name_or_path": "GET /api/v1/bot/data-health",
            "result_summary": "성공 mock 데이터 상태와 품질 점검 결과를 반환",
        },
    ],
    "overview": {
        "trade_date": "2026-04-29",
        "pnl_percent": 0.12,
        "daily_loss_limit_percent": -2.0,
        "open_positions": 1,
        "max_positions": 5,
        "rulepack_ready": True,
        "rulepack_id": "RP-20260430-SCALP-001",
        "timeline": [
            {"time": "07:45", "name": "KIS 토큰 갱신"},
            {"time": "08:00", "name": "AI 시장 톤 분석"},
            {"time": "08:15", "name": "유니버스 필터"},
            {"time": "08:30", "name": "AI 스크리닝"},
            {"time": "08:45", "name": "RulePack 생성"},
            {"time": "09:00", "name": "실시간 매매 시작"},
            {"time": "11:30", "name": "중간 리포트"},
            {"time": "15:20", "name": "당일매매 청산"},
            {"time": "15:30", "name": "장 마감"},
            {"time": "16:00", "name": "AI 복기 리포트"},
            {"time": "16:30", "name": "일일 리포트 발송"},
            {"time": "18:00", "name": "데이터 백업"},
        ],
        "next_job": {"time": "11:30", "name": "중간 리포트"},
        "health": {
            "kis_rest": {"status": "ok", "detail": "서버 라우트 정상"},
            "websocket": {"status": "mock", "detail": "실시간 엔진 미연결, 콘솔 mock 상태"},
            "rulepack": {"status": "ok", "detail": "운영용 mock RulePack 검증 완료"},
            "risk_guard": {"status": "ok", "detail": "신규 진입 허용"},
        },
        "funnel": {
            "market_total": 2500,
            "layer1": 200,
            "layer2": 15,
            "entry_waiting": 4,
            "holding": 1,
        },
        "logs": [
            {"time": "07:45", "text": "KIS 토큰 갱신 완료. 백엔드 헬스체크 통과."},
            {"time": "08:00", "text": "AI 시장 톤 분석 mock 결과 반영. 리스크 중간."},
            {"time": "08:15", "text": "Layer 1 Universe mock 집계 완료. 200개 통과."},
            {"time": "08:45", "text": "RulePack JSON mock 생성 완료."},
            {"time": "09:00", "text": "실거래 엔진 미구현. 콘솔은 안전한 상태 조회만 제공합니다."},
        ],
    },
    "rulepack": {
        "rulepack_id": "RP-20260430-SCALP-001",
        "trade_date": "2026-04-29",
        "mode": "auto",
        "status": "mock",
        "summary": "실거래 자동매매 엔진은 미구현이며, 콘솔은 운영 연결 형태만 제공합니다.",
        "changes": [
            "거래량 기준 1.8배 -> 2.0배 상향",
            "RSI 상단 72 -> 70 조정",
            "테마 비중 20% -> 15% 하향",
        ],
        "machine_rules": {
            "layer3_entry": {
                "above_vwap": True,
                "min_volume_ratio": 2.0,
                "above_ma20": True,
                "rsi_min": 40,
                "rsi_max": 70,
                "max_spread_rate": 0.003,
                "index_sync_required": True,
                "min_ai_confidence": 0.65,
            },
            "risk_limits": {
                "daily_loss_limit": -0.02,
                "max_positions": 5,
                "max_position_rate_per_stock": 0.10,
            },
        },
        "validation": {
            "schema": "pass",
            "risk_policy": "pass",
            "runtime": "mock",
        },
    },
    "data_health": {
        "status": "degraded",
        "services": [
            {"name": "KIS Token", "status": "ok", "detail": "설정 키 존재 여부는 /health에서 확인 가능"},
            {"name": "KIS REST", "status": "ok", "detail": "FastAPI 라우트 응답 가능"},
            {"name": "WebSocket", "status": "mock", "detail": "자동매매 엔진 미연결"},
            {"name": "RulePack Runtime", "status": "mock", "detail": "실운영 적용 대신 mock 상태"},
        ],
        "checks": [
            {"name": "종목코드 포맷 오류", "status": "ok", "count": 0},
            {"name": "현재가 누락", "status": "ok", "count": 0},
            {"name": "거래량 이상치", "status": "warn", "count": 1},
        ],
        "note": "실거래/실시간 자동매매는 아직 구현되지 않았습니다. 이 응답은 콘솔 통합용 mock 상태입니다.",
    },
}


def _utc_now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _clone_state() -> dict[str, Any]:
    """Return a deep copy so callers cannot mutate shared state directly."""
    return copy.deepcopy(_CONSOLE_STATE)


def record_api_audit_log(
    endpoint: str,
    method: str,
    status: str,
    source: str,
    message: str,
    *,
    live: bool,
    status_code: int,
    feature_name: str | None = None,
    purpose: str | None = None,
    result_summary: str | None = None,
) -> dict[str, Any]:
    """Append one backend API audit log entry and return a detached copy."""
    logger.info("START: console_state.record_api_audit_log - %s %s", method, endpoint)
    entry = _build_api_audit_log_entry(
        endpoint,
        method,
        status,
        source,
        message,
        live=live,
        status_code=status_code,
        feature_name=feature_name,
        purpose=purpose,
        result_summary=result_summary,
    )
    _CONSOLE_STATE["api_logs"].insert(0, entry)
    del _CONSOLE_STATE["api_logs"][_API_LOG_LIMIT:]
    logger.info("SUCCESS: console_state.record_api_audit_log - %s %s", method, endpoint)
    return copy.deepcopy(entry)


def get_api_audit_logs() -> dict[str, Any]:
    """Return recent backend API audit logs for the admin console screen."""
    logger.info("START: console_state.get_api_audit_logs")
    logs = copy.deepcopy(_CONSOLE_STATE["api_logs"])
    payload = {
        "items": logs,
        "count": len(logs),
        "mock_mode": _CONSOLE_STATE["mock_mode"],
        "updated_at": _utc_now_iso(),
        "note": "LIVE는 외부 실호출, MOCK은 mock-safe 응답, BACKEND는 내부 관리 API 호출입니다.",
    }
    logger.info("SUCCESS: console_state.get_api_audit_logs")
    return payload


def get_console_overview() -> dict[str, Any]:
    """Return the current console overview payload."""
    logger.info("START: console_state.get_console_overview")
    payload = _clone_state()["overview"]
    payload["mode"] = _CONSOLE_STATE["mode"]
    payload["engine_status"] = _CONSOLE_STATE["engine_status"]
    payload["emergency_halt"] = _CONSOLE_STATE["emergency_halt"]
    payload["mock_mode"] = _CONSOLE_STATE["mock_mode"]
    payload["updated_at"] = _utc_now_iso()
    logger.info("SUCCESS: console_state.get_console_overview")
    return payload


def get_rulepack_today() -> dict[str, Any]:
    """Return today's mock rulepack payload for the console."""
    logger.info("START: console_state.get_rulepack_today")
    payload = _clone_state()["rulepack"]
    payload["emergency_halt"] = _CONSOLE_STATE["emergency_halt"]
    payload["updated_at"] = _utc_now_iso()
    logger.info("SUCCESS: console_state.get_rulepack_today")
    return payload


def get_data_health() -> dict[str, Any]:
    """Return backend data-health information for the console."""
    logger.info("START: console_state.get_data_health")
    payload = _clone_state()["data_health"]
    payload["emergency_halt"] = _CONSOLE_STATE["emergency_halt"]
    payload["updated_at"] = _utc_now_iso()
    logger.info("SUCCESS: console_state.get_data_health")
    return payload


def trigger_emergency_halt() -> dict[str, Any]:
    """Set the console to halted mode and append an audit log entry."""
    logger.info("START: console_state.trigger_emergency_halt")
    _CONSOLE_STATE["mode"] = "HALT"
    _CONSOLE_STATE["engine_status"] = "halted"
    _CONSOLE_STATE["emergency_halt"] = True
    _CONSOLE_STATE["overview"]["health"]["risk_guard"] = {
        "status": "halted",
        "detail": "긴급정지 요청으로 신규 진입 차단",
    }
    now = datetime.now(timezone.utc).astimezone()
    _CONSOLE_STATE["overview"]["logs"].insert(
        0,
        {
            "time": now.strftime("%H:%M"),
            "text": "긴급정지 실행. 신규 자동 주문이 즉시 차단되었습니다. 실주문 엔진은 mock 상태입니다.",
        },
    )
    logger.info("SUCCESS: console_state.trigger_emergency_halt")
    return {
        "halted": True,
        "mode": _CONSOLE_STATE["mode"],
        "engine_status": _CONSOLE_STATE["engine_status"],
        "updated_at": _utc_now_iso(),
        "live": False,
        "source": "backend",
        "message": "Emergency halt applied. Automated live trading remains unimplemented; console is now mock-halted.",
    }
