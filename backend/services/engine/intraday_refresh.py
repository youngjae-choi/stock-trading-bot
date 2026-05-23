"""장중 시장 재평가 & 후보 재선별 (S3-Light → S4 → S5 갱신 → S6 후보 교체).

스케줄: 09:30 / 10:30 / 11:30 KST (각 슬롯 1회)
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

logger = logging.getLogger("IntradayRefresh")

KST = ZoneInfo("Asia/Seoul")

# 재평가 트리거 기준 등락률 (절댓값)
_REFRESH_THRESHOLD: dict[str, float] = {
    "defensive": 2.0,   # 아침 defensive인데 시장이 +2% 이상 오름
    "aggressive": 2.0,  # 아침 aggressive인데 시장이 -2% 이하 빠짐
    "neutral": 3.0,     # neutral인데 ±3% 이상 이탈
}
_DEFAULT_THRESHOLD = 3.0

# 허용 슬롯
_ALLOWED_SLOTS = {"09:30", "10:30", "11:30"}


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
                "SELECT key, value FROM system_settings WHERE key LIKE ?",
                (f"intraday_refresh.{trade_date}.%",),
            ).fetchall()
        for row in rows:
            try:
                results.append({"slot": row["key"].split(".")[-1], **json.loads(row["value"])})
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
                conn.execute("UPDATE system_settings SET value=? WHERE key=?", (value, key))
            else:
                conn.execute(
                    "INSERT INTO system_settings (key, value) VALUES (?,?)",
                    (key, value),
                )
    except Exception as exc:
        logger.warning("WARN: IntradayRefresh 이력 저장 실패 — %s", exc)


def _already_ran(trade_date: str, slot: str) -> bool:
    key = f"intraday_refresh.{trade_date}.{slot}"
    try:
        with get_connection() as conn:
            row = conn.execute("SELECT value FROM system_settings WHERE key=?", (key,)).fetchone()
        if row:
            data = json.loads(row["value"])
            return data.get("ran", False)
    except Exception:
        pass
    return False


async def _fetch_market_snapshot() -> dict[str, Any]:
    """KIS 거래량 상위 30종목 조회 → 평균 등락률 계산."""
    try:
        from ..kis.domestic.universe_service import get_volume_rank
        result = await get_volume_rank(market_code="J", top_n=30)
        items = result.get("items", []) if isinstance(result, dict) else []
        if not items:
            return {"ok": False, "reason": "no_items", "avg_change": None, "items": []}
        rates = [float(item.get("change_rate") or 0.0) for item in items]
        avg = sum(rates) / len(rates) if rates else 0.0
        return {"ok": True, "avg_change": round(avg, 2), "items": items, "count": len(items)}
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

    # 이미 오늘 같은 방향으로 재평가 완료했으면 스킵
    already_triggered = [log for log in existing_logs if log.get("triggered")]
    if already_triggered:
        last = already_triggered[-1]
        last_avg = last.get("avg_change", 0.0) or 0.0
        # 같은 방향(both positive or both negative)이면 중복 스킵
        if avg_change > 0 and last_avg > 0:
            return False, f"already_triggered_positive (last={last_avg:+.2f}%)"
        if avg_change < 0 and last_avg < 0:
            return False, f"already_triggered_negative (last={last_avg:+.2f}%)"

    if intensity == "defensive" and avg_change >= threshold:
        return True, f"defensive 플랜인데 시장 avg_change={avg_change:+.2f}% (>= +{threshold}%)"
    if intensity == "aggressive" and avg_change <= -threshold:
        return True, f"aggressive 플랜인데 시장 avg_change={avg_change:+.2f}% (<= -{threshold}%)"
    if intensity == "neutral" and abs(avg_change) >= threshold:
        return True, f"neutral 플랜인데 시장 avg_change={avg_change:+.2f}% (>= ±{threshold}%)"

    return False, f"변화 미감지 intensity={intensity} avg_change={avg_change:+.2f}% threshold=±{threshold}%"


async def _run_reselection(trade_date: str) -> dict[str, Any]:
    """S3 → S4 → S5 순서로 재실행하고 결과 요약 반환."""
    result: dict[str, Any] = {}

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
        from ..alert_service import send_telegram_message
        s4 = reselection_result.get("s4", {})
        s6 = reselection_result.get("s6", {})
        new_count = s6.get("new_count", s4.get("output_count", "?"))
        text = (
            f"♻️ [장중 재선별] {slot} 슬롯\n"
            f"감지: {reason}\n"
            f"→ 새 후보 {new_count}종목으로 교체"
        )
        await send_telegram_message(text)
    except Exception as exc:
        logger.warning("WARN: IntradayRefresh 텔레그램 알림 실패 — %s", exc)


# ---------------------------------------------------------------------------
# 공개 인터페이스
# ---------------------------------------------------------------------------

async def check_and_refresh(slot: str) -> dict[str, Any]:
    """장중 재평가 슬롯 실행 진입점.

    Args:
        slot: "09:30" | "10:30" | "11:30"

    Returns:
        실행 결과 딕셔너리
    """
    trade_date = _today()
    logger.info("START: [IntradayRefresh] slot=%s trade_date=%s", slot, trade_date)

    if slot not in _ALLOWED_SLOTS:
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
        return {"ok": False, "reason": "snapshot_failed"}

    avg_change = snapshot["avg_change"]

    # 2. 아침 플랜 조회
    morning_plan = _get_morning_plan(trade_date)
    intensity = (morning_plan or {}).get("trading_intensity", "neutral")

    # 3. 재평가 필요 여부 판단
    existing_logs = _get_refresh_log(trade_date)
    triggered, reason = _needs_refresh(avg_change, intensity, existing_logs)

    logger.info(
        "INFO: [IntradayRefresh] 판단 slot=%s avg_change=%+.2f%% intensity=%s triggered=%s reason=%s",
        slot, avg_change, intensity, triggered, reason,
    )

    if not triggered:
        log_data = {"ran": True, "triggered": False, "reason": reason, "avg_change": avg_change}
        _save_refresh_log(trade_date, slot, log_data)
        return {"ok": True, "triggered": False, "reason": reason, "avg_change": avg_change}

    # 4. S3 → S4 → S5 → S6 재실행
    reselection = await _run_reselection(trade_date)

    log_data = {
        "ran": True,
        "triggered": True,
        "reason": reason,
        "avg_change": avg_change,
        "reselection": reselection,
    }
    _save_refresh_log(trade_date, slot, log_data)

    await _send_telegram_notify(slot, avg_change, reason, reselection)

    logger.info("SUCCESS: [IntradayRefresh] 재선별 완료 slot=%s", slot)
    return {"ok": True, "triggered": True, "avg_change": avg_change, "reason": reason, "reselection": reselection}


def get_today_refresh_status(trade_date: str | None = None) -> list[dict[str, Any]]:
    """오늘 재평가 이력 반환 (콘솔 UI용)."""
    if trade_date is None:
        trade_date = _today()
    return _get_refresh_log(trade_date)
