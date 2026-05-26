"""장중 시장 재평가 & 후보 재선별 (S3-Light → S4 → S5 갱신 → S6 후보 교체).

스케줄: 09:30 / 10:30 / 11:30 / 13:00 / 14:00 KST (각 슬롯 1회)
- 매 슬롯: KIS 거래량 상위 종목 평균 등락률로 아침 플랜 대비 시장 변화 감지
- 변화 감지 시: S3 재실행 → S4 재실행 → S5 후보 목록 갱신 → S6 후보 교체
- 미감지 시: 1분 이내 스킵
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection
from ..settings_store import get_setting

logger = logging.getLogger("IntradayRefresh")

KST = ZoneInfo("Asia/Seoul")

# 재평가 트리거 기준 등락률 (절댓값)
# 주의: daily_plan은 "normal"을 쓰고, market_tone 코드는 "neutral"을 쓴다.
# 두 어휘가 동일 개념을 가리키므로 둘 다 받는다.
_REFRESH_THRESHOLD: dict[str, float] = {
    "defensive": 2.0,   # 아침 defensive인데 시장이 +2% 이상 오름
    "aggressive": 2.0,  # 아침 aggressive인데 시장이 -2% 이하 빠짐
    "neutral": 3.0,     # neutral인데 ±3% 이상 이탈
    "normal": 3.0,      # daily_plan이 기록하는 어휘
}
_NEUTRAL_INTENSITIES = {"neutral", "normal"}
_DEFAULT_THRESHOLD = 3.0

# 같은 방향으로 이미 trigger됐어도, 시장 평균이 직전 trigger 대비 이 폭만큼 더
# 변하면 재평가를 허용한다. 점진적 강세/약세를 무시하지 않기 위함.
_RETRIGGER_DELTA = 1.0

# 허용 슬롯. 13:00/14:00은 lunch_slots_enabled kill switch로만 제어한다.
_BASE_ALLOWED_SLOTS = {"09:30", "10:30", "11:30"}
_LUNCH_ALLOWED_SLOTS = {"13:00", "14:00"}


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _today() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def _get_morning_plan(trade_date: str) -> dict[str, Any] | None:
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT market_tone, trading_intensity, symbol_assignments FROM daily_trading_plans WHERE trade_date=? LIMIT 1",
                (trade_date,),
            ).fetchone()
        return dict(row) if row else None
    except Exception as exc:
        logger.warning("WARN: IntradayRefresh 아침 플랜 조회 실패 — %s", exc)
        return None


def _get_refresh_log(trade_date: str) -> list[dict[str, Any]]:
    """오늘 재평가 이력 조회 (system_settings 키 기반)."""
    results = []
    try:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT key, value_json FROM system_settings WHERE key LIKE ?",
                (f"intraday_refresh.{trade_date}.%",),
            ).fetchall()
        for row in rows:
            try:
                results.append({"slot": row["key"].split(".")[-1], **json.loads(row["value_json"])})
            except Exception:
                pass
    except Exception:
        pass
    return results


def _save_refresh_log(trade_date: str, slot: str, data: dict[str, Any]) -> None:
    key = f"intraday_refresh.{trade_date}.{slot}"
    value = json.dumps(data, ensure_ascii=False)
    try:
        with get_connection() as conn:
            existing = conn.execute("SELECT key FROM system_settings WHERE key=?", (key,)).fetchone()
            if existing:
                conn.execute("UPDATE system_settings SET value_json=? WHERE key=?", (value, key))
            else:
                conn.execute(
                    """
                    INSERT INTO system_settings (key, value_json, value_type, description, updated_at, updated_by)
                    VALUES (?, ?, 'json', '장중 재선별 슬롯 실행 로그', ?, 'intraday_refresh')
                    """,
                    (key, value, datetime.now(KST).isoformat()),
                )
    except Exception as exc:
        logger.warning("WARN: IntradayRefresh 이력 저장 실패 — %s", exc)


def _already_ran(trade_date: str, slot: str) -> bool:
    key = f"intraday_refresh.{trade_date}.{slot}"
    try:
        with get_connection() as conn:
            row = conn.execute("SELECT value_json FROM system_settings WHERE key=?", (key,)).fetchone()
        if row:
            data = json.loads(row["value_json"])
            return data.get("ran", False)
    except Exception:
        pass
    return False


def _setting_bool(key: str, default: bool) -> bool:
    """매 호출마다 kill switch 값을 읽어 재시작 없이 토글을 반영한다."""
    try:
        value = get_setting(key, default)
    except Exception as exc:
        logger.warning("WARN: IntradayRefresh setting read failed key=%s reason=%s", key, exc)
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


async def _fetch_market_snapshot() -> dict[str, Any]:
    """장중 한국 시장 종합 스냅샷 조회 (지수 + 시총상위 + 거래대금 + 업종)."""
    try:
        from ..kis.domestic.universe_service import fetch_intraday_kr_market_snapshot
        result = await fetch_intraday_kr_market_snapshot()
        if not result.get("ok") or result.get("avg_change") is None:
            return {"ok": False, "reason": "no_items", "avg_change": None, "items": []}
        return result
    except Exception as exc:
        logger.warning("WARN: IntradayRefresh 시장 스냅샷 조회 실패 — %s", exc)
        return {"ok": False, "reason": str(exc), "avg_change": None, "items": []}


def _needs_refresh(
    avg_change: float,
    morning_intensity: str,
    existing_logs: list[dict[str, Any]],
) -> tuple[bool, str]:
    """재평가 필요 여부 판단.

    Returns:
        (필요 여부, 이유 문자열)
    """
    intensity = (morning_intensity or "neutral").lower()
    threshold = _REFRESH_THRESHOLD.get(intensity, _DEFAULT_THRESHOLD)

    # 이미 오늘 같은 방향으로 재평가 완료했으면 스킵하되,
    # 직전 trigger 대비 |Δ| >= _RETRIGGER_DELTA 이면 점진 변화 반영을 위해 재평가 허용
    already_triggered = [log for log in existing_logs if log.get("triggered")]
    if already_triggered:
        last = already_triggered[-1]
        last_avg = last.get("avg_change", 0.0) or 0.0
        delta = avg_change - last_avg
        if abs(delta) < _RETRIGGER_DELTA:
            if avg_change > 0 and last_avg > 0:
                return False, (
                    f"already_triggered_positive (last={last_avg:+.2f}%, delta={delta:+.2f}% < ±{_RETRIGGER_DELTA}%)"
                )
            if avg_change < 0 and last_avg < 0:
                return False, (
                    f"already_triggered_negative (last={last_avg:+.2f}%, delta={delta:+.2f}% < ±{_RETRIGGER_DELTA}%)"
                )

    if intensity == "defensive" and avg_change >= threshold:
        return True, f"defensive 플랜인데 시장 avg_change={avg_change:+.2f}% (>= +{threshold}%)"
    if intensity == "aggressive" and avg_change <= -threshold:
        return True, f"aggressive 플랜인데 시장 avg_change={avg_change:+.2f}% (<= -{threshold}%)"
    if intensity in _NEUTRAL_INTENSITIES and abs(avg_change) >= threshold:
        return True, f"{intensity} 플랜인데 시장 avg_change={avg_change:+.2f}% (>= ±{threshold}%)"

    return False, f"변화 미감지 intensity={intensity} avg_change={avg_change:+.2f}% threshold=±{threshold}%"


async def _run_reselection(trade_date: str) -> dict[str, Any]:
    """S2 → S3 → S4 → S5 순서로 재실행하고 결과 요약 반환."""
    result: dict[str, Any] = {}

    # S2: Market Tone 재분석 — 아침 mixed 판단을 장중 변화에 반영
    try:
        from .market_tone import run_market_tone_analysis
        s2 = await run_market_tone_analysis(trigger_source="intraday_refresh")
        result["s2"] = {
            "ok": s2.get("ok", False),
            "tone": s2.get("tone"),
            "confidence": s2.get("confidence"),
        }
        logger.info(
            "INFO: [IntradayRefresh] S2 완료 tone=%s confidence=%s",
            s2.get("tone"),
            s2.get("confidence"),
        )
    except Exception as exc:
        result["s2"] = {"ok": False, "error": str(exc)}
        logger.warning("WARN: [IntradayRefresh] S2 실패 (후속 단계는 진행) — %s", exc)

    # S3: Universe Filter 재실행
    try:
        from .universe_filter import run_universe_filter
        s3 = await run_universe_filter(trigger_source="intraday_refresh")
        result["s3"] = {"ok": s3.get("ok", False), "count": s3.get("filtered_count", 0)}
        logger.info("INFO: [IntradayRefresh] S3 완료 filtered=%d", s3.get("filtered_count", 0))
    except Exception as exc:
        result["s3"] = {"ok": False, "error": str(exc)}
        logger.error("FAIL: [IntradayRefresh] S3 실패 — %s", exc)
        return result

    # S4: Hybrid Screening 재실행 (기존 후보 포함)
    try:
        from .hybrid_screening import run_hybrid_screening
        s4 = await run_hybrid_screening(trigger_source="intraday_refresh")
        result["s4"] = {
            "ok": s4.get("ok", False),
            "output_count": s4.get("output_count", 0),
            "overall_confidence": s4.get("overall_confidence"),
        }
        logger.info(
            "INFO: [IntradayRefresh] S4 완료 candidates=%d overall_conf=%.2f",
            s4.get("output_count", 0),
            s4.get("overall_confidence") or 0.0,
        )
    except Exception as exc:
        result["s4"] = {"ok": False, "error": str(exc)}
        logger.error("FAIL: [IntradayRefresh] S4 실패 — %s", exc)
        return result

    # S5: Daily Plan 후보 목록 갱신
    try:
        from .daily_plan import run_daily_plan_generation
        s5 = await run_daily_plan_generation(trigger_source="intraday_refresh")
        new_assignments = s5.get("symbol_assignments", [])
        result["s5"] = {"ok": s5.get("ok", False), "assignment_count": len(new_assignments)}
        logger.info("INFO: [IntradayRefresh] S5 완료 assignments=%d", len(new_assignments))
    except Exception as exc:
        result["s5"] = {"ok": False, "error": str(exc)}
        logger.warning("WARN: [IntradayRefresh] S5 실패 (S6 갱신은 진행) — %s", exc)

    # S6: Decision Engine 후보 교체
    try:
        from .decision_engine import decision_engine
        if decision_engine.is_active():
            s6 = await decision_engine.refresh_candidates()
            result["s6"] = s6
            logger.info(
                "INFO: [IntradayRefresh] S6 후보 교체 완료 old=%d new=%d",
                s6.get("old_count", 0),
                s6.get("new_count", 0),
            )
        else:
            result["s6"] = {"skipped": True, "reason": "decision_engine_inactive"}
    except Exception as exc:
        result["s6"] = {"ok": False, "error": str(exc)}
        logger.error("FAIL: [IntradayRefresh] S6 후보 교체 실패 — %s", exc)

    return result


async def _send_telegram_notify(
    slot: str,
    avg_change: float,
    reason: str,
    reselection_result: dict[str, Any],
) -> None:
    try:
        from ..alert_service import send_telegram_alert
        s4 = reselection_result.get("s4", {})
        s6 = reselection_result.get("s6", {})
        new_count = s6.get("new_count", s4.get("output_count", "?"))
        await send_telegram_alert(
            f"장중 재선별 - {slot}",
            f"✅ 트리거됨 — {reason}\n신규 후보 {new_count}종목, 보유 종목 유지",
        )
    except Exception as exc:
        logger.warning("WARN: IntradayRefresh 텔레그램 알림 실패 — %s", exc)


async def _send_telegram_skip(slot: str, avg_change: float | None, reason: str) -> None:
    """재선별 스킵도 운영자가 확인할 수 있게 텔레그램 알림을 보낸다."""
    try:
        from ..alert_service import send_telegram_alert

        avg_text = "확인불가" if avg_change is None else f"{avg_change:+.1f}%"
        await send_telegram_alert(f"장중 재선별 - {slot}", f"⏭️ 스킵 — 시장 평균 {avg_text} ({reason})")
    except Exception as exc:
        logger.warning("WARN: IntradayRefresh 스킵 텔레그램 알림 실패 — %s", exc)


async def _send_sector_rotation_notify(slot: str, sector_result: dict[str, Any], reselection_result: dict[str, Any]) -> None:
    """섹터 회전으로 트리거된 경우 별도 알림을 발송한다."""
    try:
        from ..alert_service import send_telegram_alert

        s4 = reselection_result.get("s4", {})
        s6 = reselection_result.get("s6", {})
        new_count = s6.get("new_count", s4.get("output_count", "?"))
        await send_telegram_alert(
            f"섹터 회전 감지 - {slot}",
            f"🔄 {sector_result.get('reason', '')}\n재선별 트리거됨. 신규 후보 {new_count}종목.",
        )
    except Exception as exc:
        logger.warning("WARN: IntradayRefresh 섹터 회전 텔레그램 알림 실패 — %s", exc)


# ---------------------------------------------------------------------------
# 공개 인터페이스
# ---------------------------------------------------------------------------

async def check_and_refresh(slot: str) -> dict[str, Any]:
    """장중 재평가 슬롯 실행 진입점.

    Args:
        slot: "09:30" | "10:30" | "11:30" | "13:00" | "14:00"

    Returns:
        실행 결과 딕셔너리
    """
    trade_date = _today()
    logger.info("START: [IntradayRefresh] slot=%s trade_date=%s", slot, trade_date)

    master_enabled = _setting_bool("intraday_refresh.master_enabled", True)
    lunch_slots_enabled = master_enabled and _setting_bool("intraday_refresh.lunch_slots_enabled", True)
    allowed_slots = set(_BASE_ALLOWED_SLOTS)
    if lunch_slots_enabled:
        allowed_slots.update(_LUNCH_ALLOWED_SLOTS)
    if slot not in allowed_slots:
        return {"ok": False, "reason": f"invalid_slot: {slot}"}

    if _already_ran(trade_date, slot):
        logger.info("INFO: [IntradayRefresh] 이미 실행됨 slot=%s — 스킵", slot)
        return {"ok": True, "skipped": True, "reason": "already_ran"}

    # 1. 시장 스냅샷 조회
    snapshot = await _fetch_market_snapshot()
    if not snapshot.get("ok") or snapshot.get("avg_change") is None:
        log_data = {"ran": True, "triggered": False, "reason": snapshot.get("reason", "snapshot_failed"), "avg_change": None}
        _save_refresh_log(trade_date, slot, log_data)
        logger.warning("WARN: [IntradayRefresh] 시장 스냅샷 조회 실패 — 스킵 slot=%s", slot)
        await _send_telegram_skip(slot, None, "시장 스냅샷 조회 실패")
        return {"ok": False, "reason": "snapshot_failed"}

    avg_change = snapshot["avg_change"]

    # 2. 아침 플랜 조회
    morning_plan = _get_morning_plan(trade_date)
    intensity = (morning_plan or {}).get("trading_intensity", "neutral")

    # 3. 재평가 필요 여부 판단
    existing_logs = _get_refresh_log(trade_date)
    market_triggered, market_reason = _needs_refresh(avg_change, intensity, existing_logs)
    sector_result: dict[str, Any] = {"enabled": False, "triggered": False, "reason": "master_disabled"}
    if master_enabled:
        try:
            from .sector_rotation import detect_sector_rotation

            sector_result = detect_sector_rotation(snapshot, slot=slot, trade_date=trade_date)
        except Exception as exc:
            sector_result = {"ok": False, "enabled": True, "triggered": False, "reason": str(exc), "gap_pct": 0.0}
            logger.warning("WARN: [IntradayRefresh] 섹터 회전 판단 실패 — %s", exc)

    triggered = market_triggered or bool(sector_result.get("triggered"))
    reason = market_reason if market_triggered else str(sector_result.get("reason") or market_reason)

    logger.info(
        "INFO: [IntradayRefresh] 판단 slot=%s avg_change=%+.2f%% intensity=%s triggered=%s reason=%s",
        slot, avg_change, intensity, triggered, reason,
    )

    if not triggered:
        log_data = {
            "ran": True,
            "triggered": False,
            "reason": reason,
            "avg_change": avg_change,
            "sector_rotation": sector_result,
        }
        _save_refresh_log(trade_date, slot, log_data)
        await _send_telegram_skip(slot, avg_change, reason)
        return {"ok": True, "triggered": False, "reason": reason, "avg_change": avg_change}

    # 4. S3 → S4 → S5 → S6 재실행
    reselection = await _run_reselection(trade_date)

    log_data = {
        "ran": True,
        "triggered": True,
        "reason": reason,
        "avg_change": avg_change,
        "market_triggered": market_triggered,
        "sector_rotation": sector_result,
        "reselection": reselection,
    }
    _save_refresh_log(trade_date, slot, log_data)

    await _send_telegram_notify(slot, avg_change, reason, reselection)
    if sector_result.get("triggered"):
        await _send_sector_rotation_notify(slot, sector_result, reselection)

    logger.info("SUCCESS: [IntradayRefresh] 재선별 완료 slot=%s", slot)
    return {
        "ok": True,
        "triggered": True,
        "avg_change": avg_change,
        "reason": reason,
        "market_triggered": market_triggered,
        "sector_rotation": sector_result,
        "reselection": reselection,
    }


def get_today_refresh_status(trade_date: str | None = None) -> list[dict[str, Any]]:
    """오늘 재평가 이력 반환 (콘솔 UI용)."""
    if trade_date is None:
        trade_date = _today()
    return _get_refresh_log(trade_date)
