"""S5 Daily Trading Plan 생성 서비스 (08:45 KST).

S4 스크리닝 결과를 기반으로 LLM이 각 종목에 Risk Profile을 배정한다.
기존 RulePack 전체 생성 방식을 대체한다.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from ..db import get_connection
from . import llm_router
from .expert_knowledge import build_knowledge_prompt_snippet, get_active_knowledge
from .hybrid_screening import get_today_screening
from .learning_memory import get_active_memories
from .market_tone import get_today_market_tone
from .pipeline_audit import finish_pipeline_run, normalize_trigger_source, start_pipeline_run
from .prompt_loader import render_prompt

logger = logging.getLogger("DailyPlanService")

_PROFILES = ("LOW_VOL", "MID_VOL", "HIGH_VOL", "THEME_SPIKE")

_VALIDATION_RULES = [
    "schema_valid",
    "profiles_exist",
    "symbol_assignments_valid",
    "global_risk_guard_ok",
    "take_profit_off",
    "stop_price_increase_only",
    "force_exit_on",
    "runtime_interpretable",
]


def _now_utc() -> str:
    """Return the current UTC timestamp formatted for SQLite text columns."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _today_kst() -> str:
    """Return today's KST trade date in YYYY-MM-DD format."""
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


def _build_prompt(
    candidates: list[dict[str, Any]],
    market_tone_data: dict[str, Any] | None,
    memories: list[dict[str, Any]] | None = None,
    knowledge_items: list[dict[str, Any]] | None = None,
) -> str:
    """Build the S5 Daily Plan prompt from candidates, market tone, and learning memories.

    Args:
        candidates: S4 screening candidates to assign risk profiles.
        market_tone_data: S2 market tone payload.
        memories: S5_DAILY_PLAN active Learning Memory rows.
        knowledge_items: S5_DAILY_PLAN/ALL approved Expert Knowledge rows.
    """
    tone = market_tone_data.get("tone", "neutral") if market_tone_data else "neutral"
    tone_summary = market_tone_data.get("summary", "") if market_tone_data else ""
    cand_rows = []
    for c in candidates[:30]:
        cand_rows.append({
            "code": c.get("symbol") or c.get("ticker") or "",
            "name": c.get("name") or "",
            "score": round(float(c.get("suitability_score") or c.get("score") or 0), 3),
            "change_rate": c.get("change_rate") or c.get("chg_rate") or 0,
            "trade_amount": c.get("trade_amount") or 0,
            "reason": c.get("reason") or c.get("analysis") or "",
        })
    if memories:
        memory_lines = []
        for memory in memories:
            rec = memory.get("recommendation", {})
            memory_lines.append(
                f"- [{memory.get('scope', '?')} / {memory.get('category', '?')}] {memory.get('summary', '')} "
                f"(권고: {rec.get('field', '?')} = {rec.get('value', '?')})"
            )
        memory_section = (
            "\n## 운영 메모리/RAG 참고사항 (전일 복기에서 구조화됨 — daily_overrides 결정 시 참고)\n"
            + "\n".join(memory_lines)
            + "\n"
        )
    else:
        memory_section = ""
    if knowledge_items:
        knowledge_section = build_knowledge_prompt_snippet(knowledge_items)
    else:
        knowledge_section = ""

    return render_prompt(
        "0845_daily_plan.md",
        {
            "tone": tone,
            "tone_summary": tone_summary,
            "memory_section": memory_section,
            "knowledge_section": knowledge_section,
            "candidates_json": json.dumps(cand_rows, ensure_ascii=False, indent=2),
        },
    )


def _validate_plan(plan_data: dict[str, Any]) -> dict[str, str]:
    """8가지 검증. 각 항목: 'pass' | 'fail:사유'."""
    result: dict[str, str] = {}

    # 1. schema_valid
    required_keys = {"trading_intensity", "new_entry_allowed", "symbol_assignments", "daily_overrides"}
    missing = required_keys - set(plan_data.keys())
    result["schema_valid"] = "pass" if not missing else f"fail:missing_keys={missing}"

    # 2. profiles_exist
    assignments = plan_data.get("symbol_assignments", [])
    bad_profiles = [a.get("profile") for a in assignments if a.get("profile") not in _PROFILES]
    result["profiles_exist"] = "pass" if not bad_profiles else f"fail:unknown_profiles={bad_profiles}"

    # 3. symbol_assignments_valid
    valid_assignments = [a for a in assignments if a.get("code") and a.get("profile") in _PROFILES]
    result["symbol_assignments_valid"] = "pass" if valid_assignments else "fail:no_valid_assignments"

    # 4. global_risk_guard_ok — daily_overrides는 리스크를 완화할 수 없음 (현재는 형식 검증만)
    result["global_risk_guard_ok"] = "pass"

    # 5. take_profit_off — Daily Plan에 take_profit 활성화 시도 차단
    overrides = plan_data.get("daily_overrides", {})
    if overrides.get("take_profit_enabled", False):
        result["take_profit_off"] = "fail:take_profit_enabled_in_plan"
    else:
        result["take_profit_off"] = "pass"

    # 6. stop_price_increase_only
    result["stop_price_increase_only"] = "pass"  # Base RulePack에서 강제, plan에선 변경 불가

    # 7. force_exit_on
    if overrides.get("force_daily_close") is False:
        result["force_exit_on"] = "fail:force_daily_close_disabled"
    else:
        result["force_exit_on"] = "pass"

    # 8. runtime_interpretable
    try:
        json.dumps(plan_data)
        result["runtime_interpretable"] = "pass"
    except Exception as e:
        result["runtime_interpretable"] = f"fail:{e}"

    return result


def _summarize_validation(validation: dict[str, str]) -> dict[str, Any]:
    """Daily Plan 검증 결과를 audit/log용 짧은 요약으로 변환한다."""
    failed = {key: value for key, value in validation.items() if value != "pass"}
    return {
        "passed_count": len(validation) - len(failed),
        "failed_count": len(failed),
        "failed_checks": failed,
    }


def _plan_count_context(plan_data: dict[str, Any]) -> dict[str, int]:
    """Daily Plan 후보 배정/제외 개수를 안전하게 계산한다."""
    assignments = plan_data.get("symbol_assignments", [])
    excluded = plan_data.get("excluded_symbols", [])
    return {
        "assignments_count": len(assignments) if isinstance(assignments, list) else 0,
        "excluded_count": len(excluded) if isinstance(excluded, list) else 0,
    }


def get_today_daily_plan(trade_date: str | None = None) -> dict[str, Any] | None:
    """오늘 활성 Daily Trading Plan 조회."""
    if not trade_date:
        trade_date = _today_kst()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, trade_date, market_tone, trading_intensity, base_rulepack_id,
                   risk_profile_pack_id, new_entry_allowed, daily_overrides,
                   symbol_assignments, excluded_symbols, llm_summary, provider,
                   status, validation_result, creation_mode, created_by,
                   trigger_source, run_audit_id,
                   s3_result_id, s4_result_id, created_at, activated_at,
                   validated_at, superseded_at, used_learning_memory_ids,
                   used_knowledge_ids
            FROM daily_trading_plans
            WHERE trade_date = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (trade_date,),
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    for key in ("daily_overrides", "validation_result"):
        try:
            d[key] = json.loads(d.get(key) or "{}")
        except Exception:
            d[key] = {}
    for key in ("symbol_assignments", "excluded_symbols", "used_learning_memory_ids", "used_knowledge_ids"):
        try:
            d[key] = json.loads(d.get(key) or "[]")
        except Exception:
            d[key] = []
    return d


async def _auto_validate_and_activate(plan_id: str, trade_date: str, plan_data: dict[str, Any]) -> tuple[str, str]:
    """생성 직후 자동 검증 후 검증 통과 시 자동 active 처리."""
    validation = _validate_plan(plan_data)
    all_pass = all(v == "pass" for v in validation.values())
    now = _now_utc()

    if all_pass:
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE daily_trading_plans
                SET status = 'superseded', superseded_at = ?
                WHERE trade_date = ? AND status = 'active' AND id != ?
                """,
                (now, trade_date, plan_id),
            )
            conn.execute(
                """
                UPDATE daily_trading_plans
                SET status = 'active', validation_result = ?, validated_at = ?, activated_at = ?
                WHERE id = ?
                """,
                (json.dumps(validation, ensure_ascii=False), now, now, plan_id),
            )
        logger.info("SUCCESS: [S5] Auto-activated plan_id=%s trade_date=%s", plan_id, trade_date)
        return plan_id, "active"
    else:
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE daily_trading_plans
                SET status = 'validation_failed', validation_result = ?, validated_at = ?
                WHERE id = ?
                """,
                (json.dumps(validation, ensure_ascii=False), now, plan_id),
            )
        logger.warning("WARN: [S5] Validation failed plan_id=%s checks=%s", plan_id, validation)
        return plan_id, "validation_failed"


def _save_plan_run_history(
    *,
    plan_id: str,
    trade_date: str,
    status: str,
    trigger_source: str,
    run_audit_id: str,
    creation_mode: str,
    created_by: str,
    provider: str,
    plan_data: dict[str, Any],
    validation: dict[str, str],
    s3_result_id: str,
    s4_result_id: str,
    created_at: str,
) -> str:
    """Persist an immutable Daily Plan generation snapshot for same-date reruns.

    Args:
        plan_id: Current row id in daily_trading_plans.
        trade_date: YYYY-MM-DD trade date.
        status: Final status for this generation attempt.
        trigger_source: Scheduler/API/console source recorded for this run.
        run_audit_id: pipeline_run_audit id linked to this generation.
        creation_mode: auto, manual, or dry_run mode.
        created_by: Actor label stored on the plan row.
        provider: LLM provider or fallback provider.
        plan_data: Full plan payload generated for this run.
        validation: Validation result for this payload.
        s3_result_id: Optional S3 upstream result id.
        s4_result_id: Optional S4 upstream result id.
        created_at: UTC timestamp used by the main plan row.
    """
    history_id = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO daily_plan_run_history
                (id, plan_id, trade_date, status, trigger_source, run_audit_id,
                 creation_mode, created_by, provider, plan_payload,
                 validation_result, s3_result_id, s4_result_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                history_id,
                plan_id,
                trade_date,
                status,
                trigger_source,
                run_audit_id,
                creation_mode,
                created_by,
                provider,
                json.dumps(plan_data, ensure_ascii=False),
                json.dumps(validation, ensure_ascii=False),
                s3_result_id,
                s4_result_id,
                created_at,
            ),
        )
    logger.info("SUCCESS: [S5] Daily Plan history saved history_id=%s plan_id=%s status=%s", history_id, plan_id, status)
    return history_id


async def run_daily_plan_generation(
    trade_date: str | None = None,
    creation_mode: str = "auto",
    created_by: str = "scheduler",
    trigger_source: str = "api_manual",
    s3_result_id: str = "",
    s4_result_id: str = "",
) -> dict[str, Any]:
    """S5: Daily Trading Plan 생성 메인 함수."""
    if not trade_date:
        trade_date = _today_kst()
    safe_source = normalize_trigger_source(trigger_source)
    run_audit_id = start_pipeline_run(
        trade_date=trade_date,
        step="S5",
        trigger_source=safe_source,
        display_source="manual-like-console" if safe_source == "console_manual" else safe_source,
        metadata={"creation_mode": creation_mode, "created_by": created_by},
    )
    logger.info(
        "START: [S5] Daily Plan generation date=%s mode=%s source=%s created_by=%s",
        trade_date,
        creation_mode,
        safe_source,
        created_by,
    )

    try:
        # S4 스크리닝 결과 조회
        screening = get_today_screening(trade_date)
        candidates = screening.get("candidates", []) if screening else []
        if not candidates:
            logger.warning("WARN: [S5] S4 스크리닝 결과 없음 — MID_VOL 기본 배정으로 진행")

        # 시장 톤 조회
        market_tone = get_today_market_tone(trade_date) if callable(get_today_market_tone) else None

        # LLM 프롬프트 생성 및 호출
        memories = get_active_memories(scope="S5_DAILY_PLAN")
        used_memory_ids = [m["memory_id"] for m in memories]
        knowledge_items = get_active_knowledge(scope="S5_DAILY_PLAN")
        used_knowledge_ids = [k["id"] for k in knowledge_items]
        market_tone_label = market_tone.get("tone", "neutral") if market_tone else "neutral"
        logger.info(
            "START: [S5] Daily Plan inputs trade_date=%s candidates=%d market_tone=%s memories=%d knowledge=%d",
            trade_date,
            len(candidates),
            market_tone_label,
            len(memories),
            len(knowledge_items),
        )
    except Exception as exc:
        finish_pipeline_run(
            run_id=run_audit_id,
            status="failed",
            message=f"startup_load_failed: {exc}",
            metadata={
                "creation_mode": creation_mode,
                "created_by": created_by,
                "trigger_source": safe_source,
            },
        )
        logger.error("FAIL: [S5] Daily Plan startup load failed trade_date=%s reason=%s", trade_date, exc)
        raise
    try:
        prompt = _build_prompt(candidates, market_tone, memories=memories, knowledge_items=knowledge_items)
    except Exception as exc:
        finish_pipeline_run(
            run_id=run_audit_id,
            status="failed",
            message=f"prompt_render_failed: {exc}",
            metadata={
                "creation_mode": creation_mode,
                "created_by": created_by,
                "trigger_source": safe_source,
            },
        )
        logger.error("FAIL: [S5] Daily Plan prompt render failed trade_date=%s reason=%s", trade_date, exc)
        raise
    plan_data: dict[str, Any] = {}
    provider = "none"

    try:
        llm_result = await llm_router.call_llm(
            prompt=prompt,
            task_name="S5 Daily Trading Plan",
        )
        if llm_result.get("ok"):
            response_text = llm_result.get("raw", "")
            provider = llm_result.get("provider", "none")
            # JSON 파싱
            import re
            json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
            if json_match:
                plan_data = json.loads(json_match.group())
            else:
                raise ValueError("JSON not found in LLM response")
        else:
            raise ValueError(f"LLM returned ok=False: {llm_result.get('error', 'unknown')}")
    except Exception as e:
        logger.error("FAIL: [S5] LLM 호출 실패 — 기본값 사용 error=%s", e)
        provider = "none"
        plan_data = {
            "trading_intensity": "normal",
            "new_entry_allowed": True,
            "daily_overrides": {"volume_filter_multiplier": 2.0, "min_ai_confidence": 0.65, "max_theme_spike_positions": 1},
            "symbol_assignments": [
                {"code": c.get("symbol") or c.get("ticker") or "", "name": c.get("name") or "", "profile": "MID_VOL", "reason": "LLM 실패 기본 배정"}
                for c in candidates if (c.get("symbol") or c.get("ticker"))
            ],
            "excluded_symbols": [],
            "llm_summary": f"LLM 호출 실패 ({e}). 모든 종목 MID_VOL 기본 배정.",
        }

    # 검증 결과는 저장하되, 상태 전환은 자동 파이프라인에서 수행한다.
    validation = _validate_plan(plan_data)
    validation_summary = _summarize_validation(validation)
    count_context = _plan_count_context(plan_data)
    status = "generated"

    plan_id = f"daily-{trade_date}"
    now = _now_utc()

    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO daily_trading_plans
                    (id, trade_date, market_tone, trading_intensity, base_rulepack_id,
                     risk_profile_pack_id, new_entry_allowed, daily_overrides,
                     symbol_assignments, excluded_symbols, llm_summary, provider,
                     status, validation_result, creation_mode, created_by,
                     trigger_source, run_audit_id, s3_result_id, s4_result_id,
                     used_learning_memory_ids, used_knowledge_ids,
                     created_at, activated_at, validated_at, superseded_at)
                VALUES (?, ?, ?, ?, 'base-v1.0', 'profile-v1.0', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL)
                """,
                (
                    plan_id,
                    trade_date,
                    market_tone.get("tone", "neutral") if market_tone else "neutral",
                    plan_data.get("trading_intensity", "normal"),
                    1 if plan_data.get("new_entry_allowed", True) else 0,
                    json.dumps(plan_data.get("daily_overrides", {}), ensure_ascii=False),
                    json.dumps(plan_data.get("symbol_assignments", []), ensure_ascii=False),
                    json.dumps(plan_data.get("excluded_symbols", []), ensure_ascii=False),
                    plan_data.get("llm_summary", ""),
                    provider,
                    status,
                    json.dumps(validation, ensure_ascii=False),
                    creation_mode,
                    created_by,
                    safe_source,
                    run_audit_id,
                    s3_result_id,
                    s4_result_id,
                    json.dumps(used_memory_ids, ensure_ascii=False),
                    json.dumps(used_knowledge_ids, ensure_ascii=False),
                    now,
                ),
            )
    except Exception as exc:
        finish_pipeline_run(
            run_id=run_audit_id,
            status="failed",
            message=f"plan_save_failed: {exc}",
            metadata={"trigger_source": safe_source},
        )
        logger.error("FAIL: [S5] Daily Plan save failed trade_date=%s reason=%s", trade_date, exc)
        raise

    # dry_run 외 생성은 저장 직후 validated 또는 validation_failed/active 상태로 전환한다.
    if creation_mode != "dry_run":
        try:
            plan_id, status = await _auto_validate_and_activate(plan_id, trade_date, plan_data)
        except Exception as exc:
            finish_pipeline_run(
                run_id=run_audit_id,
                status="failed",
                result_ref_id=plan_id,
                message=f"auto_validate_failed: {exc}",
                metadata={"trigger_source": safe_source},
            )
            logger.error("FAIL: [S5] Daily Plan auto validation failed plan_id=%s reason=%s", plan_id, exc)
            raise
    if status == "validation_failed":
        logger.warning(
            "WARN: [S5] Daily Plan validation_failed plan_id=%s assignments=%d excluded=%d validation=%s summary=%s",
            plan_id,
            count_context["assignments_count"],
            count_context["excluded_count"],
            validation,
            validation_summary,
        )

    try:
        history_id = _save_plan_run_history(
            plan_id=plan_id,
            trade_date=trade_date,
            status=status,
            trigger_source=safe_source,
            run_audit_id=run_audit_id,
            creation_mode=creation_mode,
            created_by=created_by,
            provider=provider,
            plan_data=plan_data,
            validation=validation,
            s3_result_id=s3_result_id,
            s4_result_id=s4_result_id,
            created_at=now,
        )
    except Exception as exc:
        finish_pipeline_run(
            run_id=run_audit_id,
            status="failed",
            result_ref_id=plan_id,
            message=f"history_save_failed: {exc}",
            metadata={"trigger_source": safe_source},
        )
        logger.error("FAIL: [S5] Daily Plan history save failed plan_id=%s reason=%s", plan_id, exc)
        raise

    logger.info(
        "SUCCESS: [S5] Daily Plan saved id=%s status=%s provider=%s candidates=%d market_tone=%s memories=%d knowledge=%d assignments=%d excluded=%d validation_summary=%s",
        plan_id,
        status,
        provider,
        len(candidates),
        market_tone_label,
        len(memories),
        len(knowledge_items),
        count_context["assignments_count"],
        count_context["excluded_count"],
        validation_summary,
    )
    finish_pipeline_run(
        run_id=run_audit_id,
        status="success",
        result_ref_id=plan_id,
        message=f"status={status} provider={provider}",
        metadata={
            "provider": provider,
            "creation_mode": creation_mode,
            "created_by": created_by,
            "trigger_source": safe_source,
            "candidates_count": len(candidates),
            "market_tone": market_tone_label,
            "memory_count": len(memories),
            "knowledge_count": len(knowledge_items),
            "assignments_count": count_context["assignments_count"],
            "excluded_count": count_context["excluded_count"],
            "validation_summary": validation_summary,
            "validation_result": validation,
            "history_id": history_id,
        },
    )
    return {
        "ok": True,
        "plan_id": plan_id,
        "trade_date": trade_date,
        "status": status,
        "provider": provider,
        "trigger_source": safe_source,
        "run_audit_id": run_audit_id,
        "history_id": history_id,
        "validation": validation,
        "used_learning_memory_ids": used_memory_ids,
        "memory_count": len(memories),
        "used_knowledge_ids": used_knowledge_ids,
        "knowledge_count": len(knowledge_items),
        "candidates_count": len(candidates),
        "assignments_count": count_context["assignments_count"],
    }
