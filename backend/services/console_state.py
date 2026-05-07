"""Mock console state for the static operations dashboard."""

from __future__ import annotations

import copy
import logging
from datetime import datetime, timezone
from typing import Any

from .db import get_connection

logger = logging.getLogger("BackendConsoleState")
_API_LOG_LIMIT = 50

_API_LOG_METADATA: dict[str, dict[str, str]] = {
    "/api/v1/bot/overview": {
        "feature_name": "운영 개요 조회",
        "purpose": "운영 화면에서 엔진 상태와 리스크 상태를 한 번에 확인",
        "result_summary": "성공 실 DB 기반 운영 개요 반환",
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
    "/api/v1/bot/control/resume": {
        "feature_name": "운영 재개",
        "purpose": "긴급정지 후 자동 주문 차단을 해제하고 정상 운영 상태로 복귀",
        "result_summary": "성공 긴급정지 해제, 엔진 상태를 AUTO로 전환",
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


def is_emergency_halt_enabled() -> bool:
    """Return whether emergency halt is active from persistent Settings or console memory."""
    try:
        from .settings_store import get_setting

        value = get_setting("risk.emergency_halt_enabled", False)
        if value is True or str(value).lower() == "true":
            return True
    except Exception as exc:
        logger.warning("WARN: console_state.is_emergency_halt_enabled setting read failed - %s", exc)
    return bool(_CONSOLE_STATE["emergency_halt"])


def get_cached_emergency_halt_state() -> bool:
    """Return only the in-memory console emergency halt fallback state."""
    return bool(_CONSOLE_STATE["emergency_halt"])


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
    """Return real-time console overview built from live DB and runtime state."""
    logger.info("START: console_state.get_console_overview")
    from zoneinfo import ZoneInfo

    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    today = now_kst.strftime("%Y-%m-%d")

    # 1. KIS token status
    try:
        from .kis.common.client import kis_client

        kis_ok = kis_client._token_is_valid() if kis_client is not None else False
    except Exception as exc:
        logger.warning("WARN: console_state.get_console_overview kis token check failed - %s", exc)
        kis_ok = False

    # 2. WebSocket runtime status
    try:
        from .kis.realtime_ws import realtime_ws_manager

        ws_connected = realtime_ws_manager.is_connected
        ws_symbols = getattr(realtime_ws_manager, "_symbols", [])
    except Exception as exc:
        logger.warning("WARN: console_state.get_console_overview websocket check failed - %s", exc)
        ws_connected = False
        ws_symbols = []

    # 3. Active RulePack status
    rulepack = None
    try:
        from .engine.rulepack_store import get_active_rulepack_for_date

        rulepack = get_active_rulepack_for_date(today)
        rulepack_ready = rulepack is not None
        rulepack_id = rulepack.get("rulepack_id", "") if rulepack else ""
    except Exception as exc:
        logger.warning("WARN: console_state.get_console_overview rulepack check failed - %s", exc)
        rulepack_ready = False
        rulepack_id = ""

    # 4. Decision engine status
    try:
        from .engine.decision_engine import decision_engine

        engine_active = decision_engine._active
    except Exception as exc:
        logger.warning("WARN: console_state.get_console_overview decision engine check failed - %s", exc)
        engine_active = False

    # 5. Open position count
    try:
        from .engine.position_manager import position_manager

        positions = position_manager.get_positions()
        open_positions = len(positions)
    except Exception as exc:
        logger.warning("WARN: console_state.get_console_overview position check failed - %s", exc)
        open_positions = 0

    # 6. Today's signal/order summary
    signals_pending = 0
    signals_executed = 0
    try:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM trading_signals WHERE trade_date=? GROUP BY status",
                (today,),
            ).fetchall()
        for row in rows:
            if row["status"] == "pending":
                signals_pending = row["cnt"]
            elif row["status"] == "executed":
                signals_executed = row["cnt"]
    except Exception as exc:
        logger.warning("WARN: console_state.get_console_overview trading signal summary failed - %s", exc)

    # 7. Today's realized PnL percentage
    pnl_pct = 0.0
    try:
        with get_connection() as conn:
            row = conn.execute(
                """SELECT realized_pnl_pct FROM daily_trade_summary
                   WHERE trade_date=? ORDER BY created_at DESC LIMIT 1""",
                (today,),
            ).fetchone()
        if row:
            pnl_pct = float(row["realized_pnl_pct"] or 0.0)
    except Exception as exc:
        logger.warning("WARN: console_state.get_console_overview pnl summary unavailable - %s", exc)

    # 8. Funnel aggregation from persisted pipeline outputs
    market_total = 0
    layer1_count = 0
    layer2_count = 0
    try:
        with get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) as cnt FROM symbols WHERE is_active=1").fetchone()
            market_total = row["cnt"] if row else 0
    except Exception as exc:
        logger.warning("WARN: console_state.get_console_overview market count failed - %s", exc)

    try:
        with get_connection() as conn:
            row = conn.execute(
                """SELECT items FROM universe_filter_results
                   WHERE trade_date=? ORDER BY created_at DESC LIMIT 1""",
                (today,),
            ).fetchone()
        if row:
            import json as _json

            data = _json.loads(row["items"] or "[]")
            layer1_count = len(data) if isinstance(data, list) else len(data.get("items", []))
    except Exception as exc:
        logger.warning("WARN: console_state.get_console_overview layer1 count failed - %s", exc)

    try:
        with get_connection() as conn:
            row = conn.execute(
                """SELECT output_count FROM hybrid_screening_results
                   WHERE trade_date=? ORDER BY created_at DESC LIMIT 1""",
                (today,),
            ).fetchone()
        if row:
            layer2_count = row["output_count"] or 0
    except Exception as exc:
        logger.warning("WARN: console_state.get_console_overview layer2 count failed - %s", exc)

    # 9. Timeline step completion checks
    def _step_done(table: str, date_col: str = "trade_date") -> bool:
        """Return whether a date-scoped pipeline table has at least one row for today."""
        try:
            with get_connection() as conn:
                row = conn.execute(
                    f"SELECT 1 FROM {table} WHERE {date_col}=? LIMIT 1", (today,)
                ).fetchone()
            return row is not None
        except Exception:
            return False

    s2_done = _step_done("market_tone_results")
    s3_done = _step_done("universe_filter_results")
    s4_done = _step_done("hybrid_screening_results")
    s5_done = rulepack_ready

    now_time = now_kst.strftime("%H:%M")

    def _tl_status(step_time: str, done: bool) -> str:
        """Map a scheduled step and completion flag to the console timeline status."""
        if done:
            return "완료"
        if now_time >= step_time:
            return "실행중"
        return "대기"

    def _schedule_time(key: str, default: str) -> str:
        """Read one HH:MM scheduler setting for the process-oriented overview timeline."""
        try:
            import json as _json

            with get_connection() as conn:
                row = conn.execute("SELECT value_json FROM system_settings WHERE key = ?", (key,)).fetchone()
            value = _json.loads(row["value_json"]) if row else default
            parts = str(value or "").split(":")
            if len(parts) == 2 and all(part.isdigit() for part in parts):
                hour, minute = int(parts[0]), int(parts[1])
                if 0 <= hour <= 23 and 0 <= minute <= 59:
                    return f"{hour:02d}:{minute:02d}"
        except Exception as exc:
            logger.warning("WARN: console_state schedule setting read failed key=%s reason=%s", key, exc)
        return default

    trade_prep_time = _schedule_time("schedule_trade_prep_time", "07:45")
    s6_time = _schedule_time("schedule_s6_time", "09:45")
    postprocess_time = _schedule_time("schedule_postprocess_time", "15:20")
    backup_time = _schedule_time("schedule_backup_time", "18:00")
    s11_time = _schedule_time("schedule_s11_time", "22:00")
    us_watch_time = _schedule_time("schedule_us_watch_time", "22:00")
    trade_prep_done = s2_done and s3_done and s4_done and s5_done

    timeline = [
        {"time": trade_prep_time, "name": "거래준비 프로세스(S1~S5-A)", "status": _tl_status(trade_prep_time, trade_prep_done)},
        {"time": s6_time, "name": "Decision Engine 활성화", "status": "완료" if engine_active else ("실행중" if now_time >= s6_time else "대기")},
        {"time": postprocess_time, "name": "후처리 프로세스(S9~S10)", "status": _tl_status(postprocess_time, False)},
        {"time": backup_time, "name": "데이터 백업", "status": _tl_status(backup_time, False)},
        {"time": s11_time, "name": "S11 Learning Memory", "status": _tl_status(s11_time, False)},
        {"time": us_watch_time, "name": "미국장 야간 관찰", "status": _tl_status(us_watch_time, False)},
    ]

    schedule_order = [
        (trade_prep_time, "거래준비 프로세스"),
        (s6_time, "Decision Engine 활성화"),
        (postprocess_time, "후처리 프로세스"),
        (backup_time, "데이터 백업"),
        (s11_time, "S11 Learning Memory"),
        (us_watch_time, "미국장 야간 관찰"),
    ]
    next_job = {"time": "-", "name": "-"}
    for scheduled_time, name in sorted(schedule_order):
        if now_time < scheduled_time:
            next_job = {"time": scheduled_time, "name": name}
            break

    # 10. Recent operation logs from DB events
    logs = []
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT time(created_at, '+9 hours') as kst_time, 'AI 시장 톤 분석 완료 tone='||tone as text
                   FROM market_tone_results WHERE trade_date=? ORDER BY created_at DESC LIMIT 1""",
                (today,),
            ).fetchall()
        for row in rows:
            logs.append({"time": (row["kst_time"] or "")[:5], "text": row["text"]})
    except Exception as exc:
        logger.warning("WARN: console_state.get_console_overview market tone log failed - %s", exc)

    try:
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT time(created_at, '+9 hours') as kst_time, raw_input_count, output_count
                   FROM hybrid_screening_results WHERE trade_date=? ORDER BY created_at DESC LIMIT 1""",
                (today,),
            ).fetchall()
        for row in rows:
            logs.append({
                "time": (row["kst_time"] or "")[:5],
                "text": f"AI 스크리닝 완료 - 입력 {row['raw_input_count']}종목 -> 후보 {row['output_count']}종목",
            })
    except Exception as exc:
        logger.warning("WARN: console_state.get_console_overview screening log failed - %s", exc)

    try:
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT time(created_at, '+9 hours') as kst_time, symbol, name, status
                   FROM trading_signals WHERE trade_date=? ORDER BY created_at DESC LIMIT 5""",
                (today,),
            ).fetchall()
        for row in rows:
            logs.append({
                "time": (row["kst_time"] or "")[:5],
                "text": f"매수 신호 - {row['name']}({row['symbol']}) status={row['status']}",
            })
    except Exception as exc:
        logger.warning("WARN: console_state.get_console_overview signal log failed - %s", exc)

    if not logs:
        logs.append({"time": now_time, "text": "오늘 운영 이벤트 없음"})

    logs = sorted(logs, key=lambda x: x["time"], reverse=True)[:10]

    # 11. Risk limits from active RulePack
    max_positions = 5
    daily_loss_limit_pct = -2.0
    try:
        if rulepack:
            machine_rules = rulepack.get("machine_rules") or {}
            if isinstance(machine_rules, str):
                import json as _json2

                machine_rules = _json2.loads(machine_rules)
            risk_limits = machine_rules.get("risk_limits", {})
            max_positions = int(risk_limits.get("max_positions", 5))
            daily_loss_limit_pct = float(risk_limits.get("daily_loss_limit_rate", -0.02)) * 100
    except Exception as exc:
        logger.warning("WARN: console_state.get_console_overview risk limits failed - %s", exc)

    emergency_halt = is_emergency_halt_enabled()
    payload = {
        "trade_date": today,
        "pnl_percent": pnl_pct,
        "daily_loss_limit_percent": daily_loss_limit_pct,
        "open_positions": open_positions,
        "max_positions": max_positions,
        "rulepack_ready": rulepack_ready,
        "rulepack_id": rulepack_id,
        "engine_active": engine_active,
        "signals_pending": signals_pending,
        "signals_executed": signals_executed,
        "timeline": timeline,
        "next_job": next_job,
        "health": {
            "kis_rest": {
                "status": "ok" if kis_ok else "warn",
                "detail": "토큰 유효" if kis_ok else "토큰 없음 또는 만료",
            },
            "websocket": {
                "status": "ok" if ws_connected else "warn",
                "detail": f"연결됨 - {len(ws_symbols)}개 구독중" if ws_connected else "미연결 (S4 완료 후 자동 시작)",
            },
            "rulepack": {
                "status": "ok" if rulepack_ready else "warn",
                "detail": f"활성 RulePack: {rulepack_id}" if rulepack_ready else "오늘 활성 RulePack 없음",
            },
            "risk_guard": {
                "status": "halted" if emergency_halt else "ok",
                "detail": "긴급정지 적용됨" if emergency_halt else "신규 진입 허용",
            },
        },
        "funnel": {
            "market_total": market_total,
            "layer1": layer1_count,
            "layer2": layer2_count,
            "entry_waiting": signals_pending,
            "holding": open_positions,
        },
        "logs": logs,
        "emergency_halt": emergency_halt,
        "mock_mode": False,
        "updated_at": _utc_now_iso(),
        "note": "실 DB 및 런타임 상태 기반 응답",
    }
    logger.info(
        "SUCCESS: console_state.get_console_overview trade_date=%s kis=%s ws=%s rulepack=%s",
        today,
        kis_ok,
        ws_connected,
        rulepack_ready,
    )
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
    """Return backend data-health with real KIS token status."""
    logger.info("START: console_state.get_data_health")

    try:
        from .kis.common.client import kis_client  # noqa: PLC0415

        kis_token_ok = kis_client._token_is_valid()
        kis_status = "ok" if kis_token_ok else "warn"
        kis_detail = "토큰 유효" if kis_token_ok else "토큰 없음 또는 만료"
    except Exception as exc:
        logger.warning("WARN: console_state.get_data_health kis token check failed - %s", exc)
        kis_status = "info"
        kis_detail = "KIS 토큰 상태 확인 불가 - KIS System Test S1으로 확인"

    try:
        from .db import database_status  # noqa: PLC0415

        db_health = database_status()
        db_status = "ok" if db_health.get("ok") else "warn"
        db_detail = str(db_health.get("path") or "DB 경로 확인 불가")
    except Exception as exc:
        logger.warning("WARN: console_state.get_data_health db check failed - %s", exc)
        db_status = "warn"
        db_detail = "DB 상태 확인 불가"

    # KIS WebSocket 실제 연결 상태를 확인해 콘솔 데이터 헬스에 반영한다.
    try:
        from .kis.realtime_ws import realtime_ws_manager  # noqa: PLC0415

        ws_connected = realtime_ws_manager.is_connected
        ws_symbols = getattr(realtime_ws_manager, "_symbols", [])
        if ws_connected:
            ws_status = "ok"
            ws_detail = f"연결됨 — {len(ws_symbols)}개 종목 구독중"
        else:
            ws_status = "warn"
            ws_detail = "미연결 (S4 스크리닝 완료 후 자동 시작)"
    except Exception as exc:
        logger.warning("WARN: console_state.get_data_health kis ws check failed - %s", exc)
        ws_status = "warn"
        ws_detail = "상태 확인 불가"

    try:
        from .scheduler import get_schedule_skip_today_status

        schedule_skip = get_schedule_skip_today_status()
    except Exception as exc:
        logger.warning("WARN: console_state.get_data_health scheduler skip check failed - %s", exc)
        schedule_skip = {"skip": False, "reason": "status_unavailable", "error": str(exc)}

    try:
        from .engine.pipeline_audit import get_recent_pipeline_runs
        from zoneinfo import ZoneInfo

        today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
        pipeline_runs = get_recent_pipeline_runs(today, limit=20)
    except Exception as exc:
        logger.warning("WARN: console_state.get_data_health pipeline audit failed - %s", exc)
        pipeline_runs = []

    payload = {
        "emergency_halt": is_emergency_halt_enabled(),
        "schedule_skip_today": schedule_skip,
        "pipeline_runs": pipeline_runs,
        "updated_at": _utc_now_iso(),
        "metrics": {
            "kis_rest": {"status": kis_status, "detail": kis_detail},
            "kis_ws": {"status": ws_status, "detail": ws_detail},
            "llm_router": {"status": "ok", "detail": "LLM Router 활성화 (/api/v1/market-tone/providers 참조)"},
            "db": {"status": db_status, "detail": db_detail},
            "schedule_skip": {
                "status": "warn" if schedule_skip.get("skip") else "ok",
                "detail": str(schedule_skip.get("reason") or "schedule_skip_today=false"),
            },
        },
        "note": "KIS REST 토큰은 백엔드 singleton 캐시 기준이며, KIS WebSocket은 S4 스크리닝 완료 후 자동 구독됩니다.",
    }
    logger.info("SUCCESS: console_state.get_data_health kis=%s db=%s", kis_status, db_status)
    return payload


def trigger_emergency_halt() -> dict[str, Any]:
    """Set the console to halted mode and append an audit log entry."""
    logger.info("START: console_state.trigger_emergency_halt")
    try:
        from .settings_store import upsert_setting

        upsert_setting(
            key="risk.emergency_halt_enabled",
            value=True,
            value_type="boolean",
            description="긴급정지 신규 주문 차단 상태",
            actor="console_halt",
        )
    except Exception as exc:
        logger.error("FAIL: console_state.trigger_emergency_halt setting update failed - %s", exc)
        raise
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
        "live": True,
        "source": "backend",
        "message": "Emergency halt applied. New BUY orders are blocked by preflight and order executor.",
    }


def trigger_resume() -> dict[str, Any]:
    """Clear the halted state and return to running mode."""
    logger.info("START: console_state.trigger_resume")
    try:
        from .settings_store import upsert_setting

        upsert_setting(
            key="risk.emergency_halt_enabled",
            value=False,
            value_type="boolean",
            description="긴급정지 신규 주문 차단 상태",
            actor="console_resume",
        )
    except Exception as exc:
        logger.error("FAIL: console_state.trigger_resume setting update failed - %s", exc)
        raise
    _CONSOLE_STATE["mode"] = "AUTO"
    _CONSOLE_STATE["engine_status"] = "running"
    _CONSOLE_STATE["emergency_halt"] = False
    _CONSOLE_STATE["overview"]["health"]["risk_guard"] = {
        "status": "ok",
        "detail": "운영 재개. 신규 주문 허용.",
    }
    now = datetime.now(timezone.utc).astimezone()
    _CONSOLE_STATE["overview"]["logs"].insert(
        0,
        {
            "time": now.strftime("%H:%M"),
            "text": "운영 재개. 자동 주문 차단이 해제되었습니다.",
        },
    )
    logger.info("SUCCESS: console_state.trigger_resume")
    return {
        "halted": False,
        "mode": _CONSOLE_STATE["mode"],
        "engine_status": _CONSOLE_STATE["engine_status"],
        "updated_at": _utc_now_iso(),
        "live": True,
        "source": "backend",
        "message": "Resume applied. Console state returned to running.",
    }
