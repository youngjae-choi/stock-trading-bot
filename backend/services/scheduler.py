"""APScheduler 기반 하루 사이클 자동매매 스케줄러.

S1 단계: Scheduler 뼈대 + KIS 토큰 선제 갱신 (07:45 KST).
S2~S13 단계에서 placeholder job들이 실 구현으로 교체된다.

전역 싱글턴 `scheduler_instance`을 통해 FastAPI lifespan에서 start/stop한다.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from .kis.common.client import kis_client

logger = logging.getLogger("Scheduler")
TRADING_DAY_SETTING_DESCRIPTION = "오늘 S2~S6 자동 스케줄 스킵 여부 (KST 당일 값만 유효)"

# ---------------------------------------------------------------------------
# Job 함수
# ---------------------------------------------------------------------------


def _today_kst() -> str:
    """Return today's date in Asia/Seoul as YYYY-MM-DD for scheduler decisions."""
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


def _today_kst_compact() -> str:
    """Return today's date in Asia/Seoul as YYYYMMDD for KIS trading-day checks."""
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")


def _hhmm_to_minutes(value: str) -> int | None:
    """HH:MM 문자열을 자정 기준 분으로 변환한다."""
    try:
        hour_text, minute_text = str(value).split(":", maxsplit=1)
        hour = int(hour_text)
        minute = int(minute_text)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
        return hour * 60 + minute
    except Exception:
        return None


def _minutes_to_hhmm(value: int) -> str:
    """자정 기준 분 값을 HH:MM 문자열로 변환한다."""
    bounded = max(0, min(value, 23 * 60 + 59))
    return f"{bounded // 60:02d}:{bounded % 60:02d}"


def _apply_market_open_schedule_guards(schedule_times: dict[str, str]) -> dict[str, str]:
    """장 시작 전 랭킹 데이터로 S3가 비는 것을 막기 위해 실행 시간을 보정한다."""
    guarded = dict(schedule_times)
    min_trade_prep = 9 * 60 + 1
    min_s6 = 9 * 60 + 10

    trade_prep_minutes = _hhmm_to_minutes(guarded.get("trade_prep", ""))
    if trade_prep_minutes is not None and trade_prep_minutes < min_trade_prep:
        logger.warning(
            "WARN: Scheduler trade_prep time before market data readiness value=%s effective=%s",
            guarded["trade_prep"],
            _minutes_to_hhmm(min_trade_prep),
        )
        guarded["trade_prep"] = _minutes_to_hhmm(min_trade_prep)
        trade_prep_minutes = min_trade_prep

    s6_minutes = _hhmm_to_minutes(guarded.get("s6", ""))
    required_s6 = max(min_s6, (trade_prep_minutes or min_trade_prep) + 5)
    if s6_minutes is not None and s6_minutes < required_s6:
        logger.warning(
            "WARN: Scheduler S6 time before Daily Plan readiness value=%s effective=%s",
            guarded["s6"],
            _minutes_to_hhmm(required_s6),
        )
        guarded["s6"] = _minutes_to_hhmm(required_s6)
    return guarded


def _set_schedule_skip_today(*, skip: bool, description: str, actor: str) -> None:
    """Persist the scheduler skip flag with the standard safety description.

    Args:
        skip: True only when today is clearly closed.
        description: Operator-facing reason for this write.
        actor: Setting actor recorded in system_settings.
    """
    from .settings_store import upsert_setting

    upsert_setting(
        key="schedule_skip_today",
        value=skip,
        value_type="boolean",
        description=description or TRADING_DAY_SETTING_DESCRIPTION,
        actor=actor,
    )


def _audit_step_start(step: str, metadata: dict[str, Any] | None = None) -> str:
    """Start a pipeline audit row for scheduler-owned substeps.

    Args:
        step: S-step label such as S1, S5-V, or S5-A.
        metadata: Optional JSON metadata to store with the audit row.
    """
    from .engine.pipeline_audit import start_pipeline_run

    return start_pipeline_run(
        trade_date=_today_kst(),
        step=step,
        trigger_source="auto_scheduler",
        display_source="auto_scheduler",
        metadata=metadata or {"pipeline": "scheduler"},
    )


def _audit_step_finish(
    *,
    run_id: str,
    status: str,
    message: str,
    metadata: dict[str, Any] | None = None,
    result_ref_id: str = "",
) -> None:
    """Finish a scheduler-owned pipeline audit row without leaking exceptions.

    Args:
        run_id: Audit id returned from _audit_step_start.
        status: Final audit status.
        message: Human-readable summary.
        metadata: Optional JSON metadata.
        result_ref_id: Optional related DB id.
    """
    try:
        from .engine.pipeline_audit import finish_pipeline_run

        finish_pipeline_run(
            run_id=run_id,
            status=status,
            result_ref_id=result_ref_id,
            message=message,
            metadata=metadata or {"pipeline": "scheduler"},
        )

        # ── 텔레그램 알림 자동 전송 (Phase 5B 추가) ───────────────────────────
        # S1, S5-A, S6, S9, S10, S11 등 주요 단계 종료 시 알림 전송
        try:
            from .alert_service import send_telegram_alert
            from .engine.pipeline_audit import get_connection

            # DB에서 방금 업데이트된 step 정보를 가져옴
            with get_connection() as conn:
                row = conn.execute("SELECT step FROM pipeline_run_audit WHERE id = ?", (run_id,)).fetchone()
                step = row["step"] if row else "Unknown"

            # 알림 대상 단계 필터링
            NOTIFY_STEPS = {"S1", "S2", "S3", "S4", "S5", "S5-A", "S6", "S9", "S10", "S11", "POSTPROCESS"}
            if step in NOTIFY_STEPS or status == "failed":
                emoji = "✅" if status == "success" else "⚠️" if status == "skipped" else "❌"
                title = f"BOT {step} {status.upper()} {emoji}"
                body = f"Message: {message}\nDate: {_today_kst()}"
                
                # 특정 단계 상세 정보 추가
                if step == "S1" and metadata and "s1" in metadata:
                    s1 = metadata["s1"]
                    body += f"\nToken: {s1.get('token_status')}\nMarket: {s1.get('trading_day_status')}"
                elif step == "S9" and metadata and "s9" in metadata:
                    s9 = metadata["s9"]
                    body += f"\nLiquidated: {s9.get('liquidation', {}).get('liquidated', 0)} items"

                import asyncio
                # 동기 환경(APScheduler worker)에서 비동기 함수 호출
                asyncio.create_task(send_telegram_alert(title, body))
        except Exception as alert_exc:
            logger.warning("WARN: scheduler telegram alert failed run_id=%s reason=%s", run_id, alert_exc)

    except Exception as exc:
        logger.warning("WARN: scheduler audit finish failed run_id=%s reason=%s", run_id, exc)


def _audit_skipped_step(step: str, message: str, metadata: dict[str, Any], status: str = "skipped") -> None:
    """Record a skipped or blocked downstream step for scheduler diagnostics.

    Args:
        step: Downstream S-step label.
        message: Skip reason for operator diagnostics.
        metadata: Shared skip metadata.
        status: Final audit status, usually skipped or blocked.
    """
    try:
        run_id = _audit_step_start(step, metadata)
        _audit_step_finish(run_id=run_id, status=status, message=message, metadata=metadata)
    except Exception as exc:
        logger.warning("WARN: scheduler skipped-step audit failed step=%s reason=%s", step, exc)


def get_schedule_skip_today_status() -> dict[str, Any]:
    """Return schedule_skip_today visibility with stale-flag protection.

    The flag is honored only when it was updated for today's Asia/Seoul date.
    Stale true values are reset to false so a previous non-trading-day check does
    not block the next market open.
    """
    today = _today_kst()
    try:
        from .settings_store import get_setting_record, upsert_setting

        record = get_setting_record("schedule_skip_today")
        if not record:
            return {"skip": False, "reason": "missing", "trade_date": today, "updated_at": None, "updated_by": None}
        raw_value = record.get("value")
        skip = raw_value is True or str(raw_value).lower() == "true"
        updated_at = str(record.get("updated_at") or "")
        updated_date = ""
        try:
            parsed = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            updated_date = parsed.astimezone(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
        except Exception:
            updated_date = ""
        if skip and updated_date != today:
            logger.warning(
                "WARN: schedule_skip_today stale true detected updated_at=%s updated_date=%s today=%s — reset false",
                updated_at,
                updated_date,
                today,
            )
            upsert_setting(
                key="schedule_skip_today",
                value=False,
                value_type="boolean",
                description=TRADING_DAY_SETTING_DESCRIPTION,
                actor="scheduler_stale_skip_reset",
            )
            return {
                "skip": False,
                "reason": "stale_true_reset",
                "trade_date": today,
                "updated_at": updated_at,
                "updated_by": record.get("updated_by"),
            }
        return {
            "skip": skip,
            "reason": "schedule_skip_today=true" if skip else "schedule_skip_today=false",
            "trade_date": today,
            "updated_at": updated_at,
            "updated_by": record.get("updated_by"),
        }
    except Exception as exc:
        logger.error("FAIL: schedule_skip_today status read failed — auto jobs continue reason=%s", exc)
        return {"skip": False, "reason": "read_failed_continue", "trade_date": today, "error": str(exc)}


def _should_skip_auto_job(step: str) -> bool:
    """Return whether an automatic S2~S6 scheduler job should skip today.

    Args:
        step: Pipeline step label used in logs and audit metadata.
    """
    status = get_schedule_skip_today_status()
    if status.get("skip"):
        try:
            from .engine.pipeline_audit import finish_pipeline_run, start_pipeline_run

            run_id = start_pipeline_run(
                trade_date=str(status.get("trade_date") or _today_kst()),
                step=step,
                trigger_source="auto_scheduler",
                display_source="auto_scheduler",
                metadata=status,
            )
            finish_pipeline_run(
                run_id=run_id,
                status="skipped",
                message=str(status.get("reason") or "schedule_skip_today=true"),
                metadata=status,
            )
        except Exception as exc:
            logger.warning("WARN: schedule skip audit failed step=%s reason=%s", step, exc)
        logger.warning(
            "SKIP: [%s] schedule_skip_today=true — 오늘 S2~S6 자동 스케줄 스킵 가능 status=%s",
            step,
            status,
        )
        return True
    logger.info("INFO: [%s] schedule_skip_today=false — auto job allowed status=%s", step, status)
    return False


async def job_refresh_kis_token() -> dict[str, Any]:
    """Job 1 (07:45 KST): KIS 액세스 토큰 선제 갱신.

    장 시작 전에 토큰을 미리 발급해 두어 첫 주문 시 지연을 방지한다.
    기존 토큰이 충분히 남아있으면 재발급을 시도하되, 실패(EGW00133 등) 시
    기존 토큰을 복구해 후속 API 호출이 끊기지 않도록 한다.
    """
    import time as _time

    logger.info("START: [Job1] KIS 토큰 선제 갱신")
    token_status = "success"
    token_error = ""

    # 기존 토큰 보존 (재발급 실패 시 롤백용)
    _prev_token = kis_client.token
    _prev_expires_at = kis_client.token_expires_at

    try:
        # 캐시를 무효화해 강제 재발급
        kis_client.token = None
        kis_client.token_expires_at = 0.0
        await kis_client.get_token()
        logger.info("SUCCESS: [Job1] KIS 토큰 선제 갱신 완료")
    except Exception as exc:
        # 재발급 실패 시 기존 유효 토큰 복구 (EGW00133 rate-limit 대응)
        if _prev_token and _prev_expires_at > _time.time() + 60:
            kis_client.token = _prev_token
            kis_client.token_expires_at = _prev_expires_at
            token_status = "success"
            token_error = f"refresh_failed_using_cached: {exc}"
            logger.warning(
                "WARN: [Job1] KIS 토큰 재발급 실패 — 기존 유효 토큰 복구 사용 reason=%s", exc
            )
        else:
            token_status = "failed"
            token_error = str(exc)
            logger.error("FAIL: [Job1] KIS 토큰 갱신 실패 — 유효 토큰 없음 reason=%s", exc)

    trading_day = await refresh_trading_day_skip_flag(actor="scheduler_s1")
    return {
        "token_status": token_status,
        "token_error": token_error,
        "trading_day_status": trading_day.get("status", "unknown"),
        "trading_day": trading_day,
    }


async def refresh_trading_day_skip_flag(actor: str = "scheduler_s1") -> dict[str, str]:
    """Refresh schedule_skip_today using a three-state KIS trading-day result.

    Args:
        actor: system_settings updated_by value for the scheduler write.
    """
    try:
        from .kis.domestic.service import get_trading_day_status

        today_yyyymmdd = _today_kst_compact()
        result = await get_trading_day_status(today_yyyymmdd)
        status = result.get("status", "unknown")
        reason = result.get("reason", "")
        if status == "closed":
            _set_schedule_skip_today(
                skip=True,
                description=TRADING_DAY_SETTING_DESCRIPTION,
                actor=actor,
            )
            logger.info("INFO: [Job1] 오늘(%s)은 명확한 비거래일 — S2~S6 스킵 플래그 세팅 reason=%s", today_yyyymmdd, reason)
            return result
        _set_schedule_skip_today(
            skip=False,
            description=TRADING_DAY_SETTING_DESCRIPTION,
            actor=actor,
        )
        if status == "trading":
            logger.info("INFO: [Job1] 오늘(%s)은 거래일 — 정상 진행 reason=%s", today_yyyymmdd, reason)
        else:
            logger.warning("WARN: [Job1] 거래일 확인 unknown — 자동 프로세스 차단 없이 진행 reason=%s", reason)
        return result
    except Exception as exc:
        logger.error("FAIL: [Job1] 거래일 확인 실패 — 자동 프로세스 차단 없이 진행 reason=%s", exc)
        try:
            _set_schedule_skip_today(
                skip=False,
                description="거래일 확인 실패 시 자동 프로세스 차단 방지를 위해 false로 리셋",
                actor=f"{actor}_check_failed_continue",
            )
            logger.warning("WARN: [Job1] schedule_skip_today=false 리셋 — 거래일 확인 실패로 자동 실행 허용")
        except Exception as reset_exc:
            logger.error("FAIL: [Job1] schedule_skip_today reset failed reason=%s", reset_exc)
        return {"status": "unknown", "reason": f"check_failed: {exc}", "date": _today_kst_compact()}


async def job_market_tone_analysis() -> None:
    """Job 2 (08:00 KST): LLM을 통한 시장 톤 분석 (S2 구현).

    Gemini → Groq → OpenAI GPT 순서로 fallback 호출한다.
    분석 실패 시 neutral 기본값을 저장하고 서버는 계속 실행된다.
    """
    logger.info("START: [Job2] 시장 톤 분석 (08:00 KST)")
    trading_day = await refresh_trading_day_skip_flag(actor="scheduler_s2")
    logger.info("INFO: [Job2] 거래일 상태 확인 완료 trading_day=%s", trading_day)
    if _should_skip_auto_job("S2"):
        logger.warning("SKIP: [Job2] 명확한 비거래일 — 시장 톤 분석 미실행 trading_day=%s", trading_day)
        return

    try:
        from .engine.market_tone import run_market_tone_analysis
        result = await run_market_tone_analysis(trigger_source="auto_scheduler")
        logger.info(
            "SUCCESS: [Job2] 시장 톤 분석 완료 tone=%s provider=%s confidence=%.2f",
            result.get("tone"), result.get("provider"), result.get("confidence", 0.0),
        )
    except Exception as exc:
        logger.error("FAIL: [Job2] 시장 톤 분석 실패 — reason=%s", exc)


async def job_universe_filter() -> None:
    """Job 3 (08:15 KST): 유니버스 필터 (S3 구현).

    KIS 거래량/거래대금 순위를 병렬 호출해 오늘의 유니버스를 구성하고 DB에 저장한다.
    """
    today = _today_kst()
    logger.info("START: [Job3] 유니버스 필터 (%s KST)", today)
    if _should_skip_auto_job("S3"):
        return

    try:
        from .engine.universe_filter import run_universe_filter
        result = await run_universe_filter(trigger_source="auto_scheduler")
        logger.info(
            "SUCCESS: [Job3] 유니버스 필터 완료 raw=%d filtered=%d top_n=%d",
            result.get("raw_count", 0),
            result.get("filtered_count", 0),
            result.get("result_count", 0),
        )
    except Exception as exc:
        logger.error("FAIL: [Job3] 유니버스 필터 실패 — reason=%s", exc)


async def job_hybrid_screening() -> None:
    """Job 4 (08:30 KST): 하이브리드 스크리닝 (S4 구현).

    LLM이 S3 유니버스 필터 결과를 정성 평가해 suitability_score를 부여한다.
    """
    today = _today_kst()
    logger.info("START: [Job4] 하이브리드 스크리닝 (%s KST)", today)
    if _should_skip_auto_job("S4"):
        return

    try:
        from .engine.hybrid_screening import run_hybrid_screening
        result = await run_hybrid_screening(trigger_source="auto_scheduler")
        logger.info(
            "SUCCESS: [Job4] 하이브리드 스크리닝 완료 output=%d provider=%s confidence=%.2f",
            result.get("output_count", 0),
            result.get("provider", ""),
            result.get("overall_confidence", 0.0),
        )
    except Exception as exc:
        logger.error("FAIL: [Job4] 하이브리드 스크리닝 실패 — reason=%s", exc)


async def job_daily_plan() -> None:
    """Job 5 (08:45 KST): Daily Plan 자동 생성 (S5 구현).

    S4 스크리닝 결과를 LLM에 넘겨 오늘의 Daily Trading Plan을 생성하고 저장한다.
    """
    today = _today_kst()
    logger.info("START: [Job5] Daily Plan 자동 생성 (%s KST)", today)
    if _should_skip_auto_job("S5"):
        return

    try:
        from .engine.daily_plan import run_daily_plan_generation
        result = await run_daily_plan_generation(trigger_source="auto_scheduler")
        logger.info("SUCCESS: [Scheduler] S5 Daily Plan result=%s", result)
    except Exception as exc:
        logger.error("FAIL: [Scheduler] S5 Daily Plan error=%s", exc)


async def _run_trade_prep_callable(step: str, label: str, func: Callable[[], Awaitable[Any]]) -> Any:
    """Run one trade-preparation substep and stop the pipeline on failure.

    Args:
        step: S-step label for logs.
        label: Operator-facing step name.
        func: Awaitable substep implementation.
    """
    logger.info("START: [TradePrep] %s %s", step, label)
    try:
        result = await func()
        logger.info("SUCCESS: [TradePrep] %s %s result=%s", step, label, result if result is not None else "ok")
        return result
    except Exception as exc:
        logger.error("FAIL: [TradePrep] %s %s reason=%s", step, label, exc)
        raise


async def _job_validate_daily_plan_for_pipeline() -> dict[str, Any]:
    """S5-V: validate today's Daily Plan and record an audit row without HTTP calls."""
    run_id = _audit_step_start("S5-V", {"pipeline": "trade_preparation"})
    try:
        from .engine.daily_plan import _validate_plan, get_today_daily_plan

        today = _today_kst()
        plan = get_today_daily_plan(today)
        if not plan:
            message = "No plan found for today"
            _audit_step_finish(run_id=run_id, status="failed", message=message, metadata={"pipeline": "trade_preparation"})
            raise RuntimeError(message)
        validation = _validate_plan(
            {
                "trading_intensity": plan.get("trading_intensity"),
                "new_entry_allowed": plan.get("new_entry_allowed"),
                "symbol_assignments": plan.get("symbol_assignments", []),
                "daily_overrides": plan.get("daily_overrides", {}),
            }
        )
        all_pass = all(value == "pass" for value in validation.values())
        status = "success" if all_pass else "failed"
        message = "validation_pass" if all_pass else "validation_failed"
        _audit_step_finish(
            run_id=run_id,
            status=status,
            message=message,
            result_ref_id=str(plan.get("id") or ""),
            metadata={"pipeline": "trade_preparation", "validation": validation},
        )
        if not all_pass:
            raise RuntimeError(message)
        return {"validation": validation, "all_pass": all_pass, "plan_id": str(plan.get("id") or "")}
    except Exception as exc:
        logger.error("FAIL: [TradePrep] S5-V Daily Plan validation reason=%s", exc)
        raise


async def _job_confirm_daily_plan_activation_for_pipeline() -> dict[str, Any]:
    """S5-A: confirm today's Daily Plan is active without calling activation APIs."""
    run_id = _audit_step_start("S5-A", {"pipeline": "trade_preparation"})
    try:
        from .engine.daily_plan import get_today_daily_plan

        today = _today_kst()
        plan = get_today_daily_plan(today)
        if not plan:
            message = "No plan found for today"
            _audit_step_finish(run_id=run_id, status="failed", message=message, metadata={"pipeline": "trade_preparation"})
            raise RuntimeError(message)
        plan_status = str(plan.get("status") or "")
        if plan_status != "active":
            message = f"not_active status={plan_status or '-'}"
            _audit_step_finish(
                run_id=run_id,
                status="failed",
                message=message,
                result_ref_id=str(plan.get("id") or ""),
                metadata={"pipeline": "trade_preparation", "plan_status": plan_status},
            )
            raise RuntimeError(message)
        _audit_step_finish(
            run_id=run_id,
            status="success",
            message="active_confirmed",
            result_ref_id=str(plan.get("id") or ""),
            metadata={"pipeline": "trade_preparation", "plan_status": plan_status},
        )
        return {"plan_id": str(plan.get("id") or ""), "status": plan_status}
    except Exception as exc:
        logger.error("FAIL: [TradePrep] S5-A Daily Plan activation check reason=%s", exc)
        raise


def _get_active_daily_plan_for_s6() -> dict[str, Any] | None:
    """Return today's active Daily Plan, enforcing S5-A as the S6 safety gate."""
    from .db import get_connection

    today = _today_kst()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, trade_date, status, created_at, activated_at
            FROM daily_trading_plans
            WHERE trade_date = ? AND status = 'active'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (today,),
        ).fetchone()
    return dict(row) if row else None


def _summarize_daily_plan_validation(raw_validation: str | None) -> dict[str, Any]:
    """S6 차단 로그에 사용할 Daily Plan 검증 결과 요약을 만든다."""
    try:
        validation = json.loads(raw_validation or "{}")
    except Exception:
        validation = {}
    if not isinstance(validation, dict):
        validation = {}
    failed = {key: value for key, value in validation.items() if value != "pass"}
    return {
        "passed_count": len(validation) - len(failed),
        "failed_count": len(failed),
        "failed_checks": failed,
    }


def _get_latest_daily_plan_context_for_s6() -> dict[str, Any]:
    """S6 blocked 원인 분석용 최신 Daily Plan 상태를 조회한다."""
    from .db import get_connection

    today = _today_kst()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, status, validation_result, created_at, activated_at, validated_at
            FROM daily_trading_plans
            WHERE trade_date = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (today,),
        ).fetchone()
    if row is None:
        return {"plan_present": False, "trade_date": today}
    plan = dict(row)
    return {
        "plan_present": True,
        "trade_date": today,
        "id": plan.get("id", ""),
        "status": plan.get("status", ""),
        "validation_summary": _summarize_daily_plan_validation(plan.get("validation_result")),
        "created_at": plan.get("created_at", ""),
        "activated_at": plan.get("activated_at", ""),
        "validated_at": plan.get("validated_at", ""),
    }


def _get_recent_pre_s6_audit_context() -> list[dict[str, Any]]:
    """최근 S3/S4/S5 audit 메시지를 S6 blocked metadata에 넣을 안전한 요약으로 조회한다."""
    from .db import get_connection

    today = _today_kst()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT step, status, message, result_ref_id, started_at, finished_at
            FROM pipeline_run_audit
            WHERE trade_date = ? AND step IN ('S3', 'S4', 'S5')
            ORDER BY started_at DESC
            LIMIT 9
            """,
            (today,),
        ).fetchall()
    return [dict(row) for row in rows]


async def job_trade_preparation_pipeline() -> None:
    """Run S1 through S5-A sequentially from one trade-preparation schedule key."""
    logger.info("START: [TradePrep] S1~S5-A 거래준비 프로세스")
    try:
        run_id = _audit_step_start("S1", {"pipeline": "trade_preparation"})
        s1_result = await job_refresh_kis_token()
        token_status = str(s1_result.get("token_status") or "unknown")
        raw_trading_day = s1_result.get("trading_day")
        trading_day: dict[str, Any] = raw_trading_day if isinstance(raw_trading_day, dict) else {}
        trading_day_status = str(s1_result.get("trading_day_status") or trading_day.get("status") or "unknown")
        s1_audit_status = "success"
        if token_status != "success":
            s1_audit_status = "failed"
        elif trading_day_status == "unknown":
            s1_audit_status = "partial_failed"
        _audit_step_finish(
            run_id=run_id,
            status=s1_audit_status,
            message=f"token_status={token_status}; trading_day_status={trading_day_status}",
            metadata={"pipeline": "trade_preparation", "s1": s1_result},
        )

        if token_status != "success":
            metadata = {"pipeline": "trade_preparation", "s1": s1_result}
            message = "S1 token refresh failed; trade prep stopped before downstream KIS-dependent steps"
            for step in ("S2", "S3", "S4", "S5", "S5-V", "S5-A", "S6"):
                _audit_skipped_step(step, message, metadata, status="blocked")
            logger.warning("WARN: [TradePrep] S1 token refresh failed — S2~S6 자동 단계 중단 s1=%s", s1_result)
            return

        if trading_day_status == "closed":
            metadata = {"pipeline": "trade_preparation", "s1": s1_result}
            message = "S1 confirmed closed trading day"
            for step in ("S2", "S3", "S4", "S5", "S5-V", "S5-A", "S6"):
                _audit_skipped_step(step, message, metadata)
            logger.warning("SKIP: [TradePrep] 명확한 비거래일 — S2~S6 자동 단계 스킵 trading_day=%s", trading_day)
            return
        if trading_day_status == "unknown":
            logger.warning("WARN: [TradePrep] 거래일 상태 unknown — token은 정상이나 자동 프로세스는 S2~S5-A 진행 s1=%s", s1_result)

        from .engine.daily_plan import run_daily_plan_generation
        from .engine.hybrid_screening import run_hybrid_screening
        from .engine.market_tone import run_market_tone_analysis
        from .engine.universe_filter import run_universe_filter

        await _run_trade_prep_callable(
            "S2",
            "시장 톤 분석",
            lambda: run_market_tone_analysis(trigger_source="auto_scheduler"),
        )
        await _run_trade_prep_callable(
            "S3",
            "유니버스 필터",
            lambda: run_universe_filter(trigger_source="auto_scheduler"),
        )
        await _run_trade_prep_callable(
            "S4",
            "하이브리드 스크리닝",
            lambda: run_hybrid_screening(trigger_source="auto_scheduler"),
        )
        await _run_trade_prep_callable(
            "S5",
            "Daily Plan 생성",
            lambda: run_daily_plan_generation(
                trade_date=_today_kst(),
                creation_mode="auto",
                created_by="scheduler",
                trigger_source="auto_scheduler",
            ),
        )
        await _run_trade_prep_callable("S5-V", "Daily Plan 검증", _job_validate_daily_plan_for_pipeline)
        await _run_trade_prep_callable("S5-A", "Daily Plan 활성화 확인", _job_confirm_daily_plan_activation_for_pipeline)
        logger.info("SUCCESS: [TradePrep] S1~S5-A 거래준비 프로세스 완료")
    except Exception as exc:
        logger.error("FAIL: [TradePrep] 거래준비 프로세스 중단 reason=%s", exc)


async def job_decision_engine_start() -> None:
    """Job 6 (09:00 KST): S6 Decision Engine 활성화 + WS 연결."""
    logger.info("START: [Job6] Decision Engine 활성화 (09:00 KST)")
    if _should_skip_auto_job("S6"):
        return

    try:
        active_plan = _get_active_daily_plan_for_s6()
        if not active_plan:
            latest_plan_context = _get_latest_daily_plan_context_for_s6()
            recent_audit_context = _get_recent_pre_s6_audit_context()
            metadata = {
                "pipeline": "decision_engine_start",
                "trade_date": _today_kst(),
                "required_status": "active",
                "latest_daily_plan": latest_plan_context,
                "recent_s3_s4_s5_audits": recent_audit_context,
            }
            message = "S6 activation blocked: no active Daily Plan for today"
            _audit_skipped_step("S6", message, metadata, status="blocked")
            logger.warning(
                "WARN: [Job6] %s latest_plan_id=%s latest_plan_status=%s validation_summary=%s recent_audits=%s",
                message,
                latest_plan_context.get("id", ""),
                latest_plan_context.get("status", "none"),
                latest_plan_context.get("validation_summary", {}),
                recent_audit_context,
            )
            return

        from .engine.decision_engine import decision_engine
        result = await decision_engine.activate()
        logger.info(
            "SUCCESS: [Job6] Decision Engine active=%s candidates=%s",
            result.get("ok"),
            result.get("candidates", 0),
        )
    except Exception as exc:
        logger.error("FAIL: [Job6] Decision Engine 활성화 실패 — reason=%s", exc)


async def job_decision_engine_stop() -> None:
    """Job 9 (15:20 KST): S6 비활성화 + WS 종료."""
    logger.info("START: [Job9] Decision Engine 비활성화 (15:20 KST)")
    try:
        from .engine.decision_engine import decision_engine
        await decision_engine.deactivate()
        logger.info("SUCCESS: [Job9] Decision Engine 비활성화 완료")
    except Exception as exc:
        logger.error("FAIL: [Job9] 비활성화 실패 — reason=%s", exc)


async def job_eod_liquidation() -> dict[str, Any]:
    """Job S9 (15:20 KST): 당일 포지션 전량 청산 후 Decision Engine을 종료한다."""
    logger.info("START: [Job S9] 당일 청산 (15:20 KST)")
    liquidation_result: dict[str, Any] = {}
    liquidation_error: Exception | None = None
    deactivate_error = ""
    try:
        from .engine.eod_liquidation import run_eod_liquidation

        liquidation_result = await run_eod_liquidation()
        logger.info("SUCCESS: [Job S9] 청산 완료 liquidated=%d", liquidation_result.get("liquidated", 0))
    except Exception as exc:
        liquidation_error = exc
        logger.error("FAIL: [Job S9] 청산 실패 — reason=%s", exc)

    try:
        from .engine.decision_engine import decision_engine

        await decision_engine.deactivate()
        logger.info("SUCCESS: [Job S9] Decision Engine 비활성화 완료")
    except Exception as exc:
        deactivate_error = str(exc)
        logger.error("FAIL: [Job S9] Decision Engine 비활성화 실패 — reason=%s", exc)

    if liquidation_error:
        raise RuntimeError(f"S9 liquidation failed: {liquidation_error}") from liquidation_error
    return {
        "ok": not deactivate_error,
        "liquidation_ok": True,
        "deactivate_ok": not deactivate_error,
        "deactivate_error": deactivate_error,
        "liquidation": liquidation_result,
    }


async def job_data_backup() -> None:
    """Job S10 (18:00 KST): 당일 거래 결과 집계 + DB 백업."""
    logger.info("START: [Job S10] 당일 거래 요약 + DB 백업 (18:00 KST)")
    try:
        from .engine.daily_summary import run_daily_summary
        result = await run_daily_summary()
        logger.info(
            "SUCCESS: [Job S10] 완료 orders=%d pnl=%.0f backup=%s",
            result.get("total_orders", 0),
            result.get("realized_pnl", 0),
            result.get("backup", {}).get("ok"),
        )
    except Exception as exc:
        logger.error("FAIL: [Job S10] 실패 — reason=%s", exc)


async def job_review_audit() -> None:
    """Job S10 Review & Audit (16:00 KST): 당일 매매 결과를 분석한다."""
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    logger.info("START: [Job ReviewAudit] S10 Review & Audit (%s KST)", today)
    try:
        from .engine.review_audit import run_review_audit

        result = await run_review_audit(today)
        logger.info(
            "SUCCESS: [Job ReviewAudit] 완료 trades=%d pnl=%.4f",
            result.get("total_trades", 0),
            result.get("total_pnl", 0.0),
        )
    except Exception as exc:
        logger.error("FAIL: [Job ReviewAudit] 실패 — reason=%s", exc)


async def job_postprocess_pipeline() -> None:
    """Run S9 then S10 sequentially from one postprocess schedule key."""
    logger.info("START: [PostProcess] S9~S10 후처리 프로세스")
    pipeline_run_id = _audit_step_start("POSTPROCESS", {"pipeline": "postprocess"})
    s9_failed = False
    s9_message = "success"
    try:
        s9_run_id = _audit_step_start("S9", {"pipeline": "postprocess"})
        try:
            logger.info("START: [PostProcess] S9 당일 청산")
            s9_result = await job_eod_liquidation()
            s9_status = "success" if s9_result.get("ok") else "partial_failed"
            s9_message = "liquidation_completed" if s9_result.get("ok") else "liquidation_completed_deactivate_failed"
            if s9_status != "success":
                s9_failed = True
                logger.warning("WARN: [PostProcess] S9 partial failure result=%s", s9_result)
            _audit_step_finish(
                run_id=s9_run_id,
                status=s9_status,
                message=s9_message,
                metadata={"pipeline": "postprocess", "s9": s9_result},
            )
            logger.info("SUCCESS: [PostProcess] S9 당일 청산 호출 완료")
        except Exception as exc:
            s9_failed = True
            s9_message = f"S9 failed: {exc}"
            _audit_step_finish(
                run_id=s9_run_id,
                status="failed",
                message=s9_message,
                metadata={"pipeline": "postprocess", "error": str(exc)},
            )
            logger.error("FAIL: [PostProcess] S9 당일 청산 실패 — S10 review continued reason=%s", exc)

        logger.info("START: [PostProcess] S10 Review & Audit")
        await job_review_audit()
        logger.info("SUCCESS: [PostProcess] S10 Review & Audit 호출 완료")
        if s9_failed:
            message = "S9 failed, S10 review continued"
            _audit_step_finish(
                run_id=pipeline_run_id,
                status="partial_failed",
                message=message,
                metadata={"pipeline": "postprocess", "s9_message": s9_message},
            )
            logger.warning("WARN: [PostProcess] %s", message)
            return
        _audit_step_finish(
            run_id=pipeline_run_id,
            status="success",
            message="S9~S10 completed",
            metadata={"pipeline": "postprocess"},
        )
        logger.info("SUCCESS: [PostProcess] S9~S10 후처리 프로세스 완료")
    except Exception as exc:
        _audit_step_finish(
            run_id=pipeline_run_id,
            status="failed",
            message=f"postprocess failed: {exc}",
            metadata={"pipeline": "postprocess", "error": str(exc)},
        )
        logger.error("FAIL: [PostProcess] 후처리 프로세스 중단 reason=%s", exc)


async def job_learning_memory() -> None:
    """Job S11 Learning Memory Builder (16:30 KST): 리뷰 결과를 학습 메모리로 저장한다."""
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    logger.info("START: [Job LearningMemory] S11 Learning Memory Builder (%s KST)", today)
    try:
        from .engine.learning_memory import run_learning_memory_builder

        result = await run_learning_memory_builder(today)
        logger.info(
            "SUCCESS: [Job LearningMemory] 완료 ok=%s memories=%d",
            result.get("ok"),
            result.get("memory_count", 0),
        )
    except Exception as exc:
        logger.error("FAIL: [Job LearningMemory] 실패 — reason=%s", exc)


async def job_us_market_watch() -> None:
    """Job S11 (22:00 KST): 미국 장중 지표 수집 + DB 저장."""
    logger.info("START: [Job S11] 미국장 관찰 (22:00 KST)")
    try:
        from .engine.us_market_watch import run_us_market_watch
        result = await run_us_market_watch()
        logger.info(
            "SUCCESS: [Job S11] 완료 sp500=%s nasdaq=%s usdkrw=%s",
            result.get("sp500_chg_pct"),
            result.get("nasdaq_chg_pct"),
            result.get("usdkrw_rate"),
        )
    except Exception as exc:
        logger.error("FAIL: [Job S11] 실패 — reason=%s", exc)


# ---------------------------------------------------------------------------
# 스케줄러 싱글턴
# ---------------------------------------------------------------------------


def _build_scheduler() -> AsyncIOScheduler:
    """AsyncIOScheduler를 생성하고 전체 job을 등록해 반환한다.

    timezone은 Asia/Seoul로 고정한다.
    job 실패 시 예외가 외부로 전파되지 않도록 각 job 함수에서 try/except 처리한다.
    """
    schedule_times = {
        "trade_prep": "07:45",
        "s6": "09:45",
        "postprocess": "15:20",
        "s11": "22:00",
        "backup": "18:00",
        "us_watch": "22:00",
    }
    try:
        from .settings_store import list_settings

        saved = {
            item["key"]: item["value"]
            for item in list_settings()
            if isinstance(item.get("key"), str) and item["key"].startswith("schedule_")
        }
        key_map = {
            "trade_prep": "schedule_trade_prep_time",
            "s6": "schedule_s6_time",
            "postprocess": "schedule_postprocess_time",
            "s11": "schedule_s11_time",
        }
        for key, db_key in key_map.items():
            if isinstance(saved.get(db_key), str):
                schedule_times[key] = saved[db_key]
        if not isinstance(saved.get("schedule_trade_prep_time"), str) and isinstance(saved.get("schedule_s1_time"), str):
            schedule_times["trade_prep"] = saved["schedule_s1_time"]
        if not isinstance(saved.get("schedule_postprocess_time"), str) and isinstance(saved.get("schedule_s9_time"), str):
            schedule_times["postprocess"] = saved["schedule_s9_time"]
        logger.info("INFO: Scheduler 시간 로드 times=%s", schedule_times)
    except Exception as exc:
        logger.warning("WARN: Scheduler settings 로드 실패 — 기본값 사용 reason=%s", exc)
    schedule_times = _apply_market_open_schedule_guards(schedule_times)

    def _parse_time(setting_key: str) -> tuple[int, int]:
        """Parse HH:MM scheduler settings, falling back to the built-in default on invalid values."""
        raw_time = schedule_times[setting_key]
        try:
            hour_text, minute_text = raw_time.split(":", maxsplit=1)
            hour = int(hour_text)
            minute = int(minute_text)
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError(f"out of range: {raw_time}")
            return hour, minute
        except Exception as exc:
            logger.warning("WARN: Scheduler invalid time key=%s value=%s reason=%s", setting_key, raw_time, exc)
            fallback = {
                "trade_prep": (7, 45),
                "s6": (9, 45),
                "postprocess": (15, 20),
                "s11": (22, 0),
                "backup": (18, 0),
                "us_watch": (22, 0),
            }
            return fallback[setting_key]

    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")

    hour, minute = _parse_time("trade_prep")
    scheduler.add_job(
        job_trade_preparation_pipeline,
        CronTrigger(hour=hour, minute=minute, timezone="Asia/Seoul"),
        id="job_trade_preparation_pipeline",
        name="거래준비 프로세스 S1~S5-A",
        replace_existing=True,
    )
    hour, minute = _parse_time("s6")
    scheduler.add_job(
        job_decision_engine_start,
        CronTrigger(hour=hour, minute=minute, timezone="Asia/Seoul"),
        id="job_decision_engine_start",
        name="Decision Engine 활성화",
        replace_existing=True,
    )
    hour, minute = _parse_time("postprocess")
    scheduler.add_job(
        job_postprocess_pipeline,
        CronTrigger(hour=hour, minute=minute, timezone="Asia/Seoul"),
        id="job_postprocess_pipeline",
        name="후처리 프로세스 S9~S10",
        replace_existing=True,
    )
    hour, minute = _parse_time("backup")
    scheduler.add_job(
        job_data_backup,
        CronTrigger(hour=hour, minute=minute, timezone="Asia/Seoul"),
        id="job_data_backup",
        name="데이터 백업",
        replace_existing=True,
    )
    hour, minute = _parse_time("s11")
    scheduler.add_job(
        job_learning_memory,
        CronTrigger(hour=hour, minute=minute, timezone="Asia/Seoul"),
        id="job_learning_memory",
        name="S11 Learning Memory Builder",
        replace_existing=True,
    )
    hour, minute = _parse_time("us_watch")
    scheduler.add_job(
        job_us_market_watch,
        CronTrigger(hour=hour, minute=minute, timezone="Asia/Seoul"),
        id="job_us_market_watch",
        name="야간 미국장 관찰",
        replace_existing=True,
    )

    # 배당락일 D-2 알림 — 하루 2회 (08:00, 13:00 KST)
    scheduler.add_job(
        job_dividend_ex_date_alert,
        CronTrigger(hour=8, minute=0, timezone="Asia/Seoul"),
        id="job_dividend_alert_am",
        name="배당락일 알림 (오전)",
        replace_existing=True,
    )
    scheduler.add_job(
        job_dividend_ex_date_alert,
        CronTrigger(hour=13, minute=0, timezone="Asia/Seoul"),
        id="job_dividend_alert_pm",
        name="배당락일 알림 (오후)",
        replace_existing=True,
    )

    return scheduler


async def job_dividend_ex_date_alert() -> None:
    """배당락일 D-2 ~ D-0 종목에 텔레그램 알림 발송."""
    from datetime import date
    from .alert_service import send_telegram_with_inline_button
    from .db import get_connection

    today = date.today()
    logger.info("START: job_dividend_ex_date_alert date=%s", today)
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT id, name, code, next_ex_date
                   FROM dividend_stocks
                   WHERE is_active = 1
                     AND notification_muted = 0
                     AND next_ex_date IS NOT NULL""",
            ).fetchall()

        for row in rows:
            try:
                ex_date = date.fromisoformat(row["next_ex_date"])
            except ValueError:
                continue
            delta = (ex_date - today).days
            if 0 <= delta <= 2:
                text = (
                    f"📅 <b>배당락일 알림 (D-{delta})</b>\n"
                    f"{row['name']}({row['code']}) 배당락일: {row['next_ex_date']}"
                )
                await send_telegram_with_inline_button(
                    text=text,
                    button_text="이 종목 알림 끄기",
                    callback_data=f"mute_stock_{row['id']}",
                )
                logger.info(
                    "INFO: job_dividend_ex_date_alert sent name=%s ex_date=%s d=%s",
                    row["name"], row["next_ex_date"], delta,
                )
    except Exception as exc:
        logger.error("FAIL: job_dividend_ex_date_alert reason=%s", exc)


# 전역 싱글턴 — FastAPI lifespan에서 start/stop 호출
scheduler_instance: AsyncIOScheduler = _build_scheduler()
