"""RulePack 자동 생성 서비스 (S5 — 08:45 KST).

S4 하이브리드 스크리닝 결과, 시장 톤, 어제 RulePack을 조합해
LLM에 RulePack JSON 생성을 요청한다.

결과에 인라인 L1 절대한도 + PM Settings 캐스케이딩 캡을 적용하고
rulepacks 테이블에 저장한 뒤 자동 활성화한다.

RulePack 스키마: backend/prompts/0845_gpt_rulepack_generation.md 참조.
machine_rules 컬럼에 GPT 생성 전체 JSON을 저장한다.
"""

from __future__ import annotations

import copy
import json
import logging
from datetime import datetime, timezone
from typing import Any

from ..db import get_connection
from ..settings_store import list_settings
from . import llm_router
from .hybrid_screening import get_today_screening
from .prompt_loader import render_prompt
from .rulepack_store import (
    activate_rulepack,
    create_rulepack,
    get_active_rulepack_for_date,
    update_rulepack_validation,
)

logger = logging.getLogger("RulePackGenerationService")


# ---------------------------------------------------------------------------
# L1 절대 한도 (코드 변경 + 재배포 없이는 변경 불가)
# ---------------------------------------------------------------------------
_DAILY_LOSS_LIMIT_L1 = -0.10  # -10%
_MAX_POSITIONS_L1 = 30
_STOP_LOSS_L1 = -0.05  # -5%
_MAX_POS_SIZE_L1 = 0.30  # 30%
_TAKE_PROFIT_L1 = 0.30  # 30%
_MAX_HOLDING_MIN_L1 = 390  # 390분


def _cap(value: Any, limit: Any, direction: str) -> Any:
    """단일 값에 L1/PM 한도를 적용한다.

    Args:
        value: 검증 대상 값.
        limit: 적용할 한도 값.
        direction: "neg"는 하한, "pos"는 상한으로 값을 보정한다.
    """
    if direction == "neg":
        return limit if value < limit else value
    return limit if value > limit else value


def _apply_l1_caps(rulepack: dict[str, Any], pm: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """rulepack risk_limits에 PM 설정과 L1 절대한도를 순서대로 적용한다.

    Args:
        rulepack: LLM이 생성한 RulePack 원본 데이터.
        pm: system_settings에서 로드한 PM 위험 설정.

    Returns:
        캡이 적용된 RulePack과 필드별 캡 적용 로그.
    """
    result = copy.deepcopy(rulepack)
    risk_limits = result["risk_limits"]
    cap_log: list[dict[str, Any]] = []

    def _apply_one(field: str, ai_val: Any, pm_val: Any, l1_val: Any, direction: str) -> Any:
        """단일 risk limit 필드에 PM 설정과 L1 한도를 적용한다."""
        effective_pm = _cap(pm_val, l1_val, direction)
        final = _cap(ai_val, effective_pm, direction)
        capped_by = "none"
        if final != ai_val:
            capped_by = "l1_absolute" if effective_pm != pm_val else "pm_settings"
        cap_log.append({"field": field, "original": ai_val, "capped": final, "capped_by": capped_by})
        return final

    risk_limits["daily_loss_limit_rate"] = _apply_one(
        "daily_loss_limit_rate",
        risk_limits.get("daily_loss_limit_rate", _DAILY_LOSS_LIMIT_L1),
        pm.get("daily_loss_limit_rate", _DAILY_LOSS_LIMIT_L1),
        _DAILY_LOSS_LIMIT_L1,
        "neg",
    )
    risk_limits["max_positions"] = int(
        _apply_one(
            "max_positions",
            risk_limits.get("max_positions", _MAX_POSITIONS_L1),
            pm.get("max_positions", _MAX_POSITIONS_L1),
            _MAX_POSITIONS_L1,
            "pos",
        )
    )
    risk_limits["stop_loss_rate"] = _apply_one(
        "stop_loss_rate",
        risk_limits.get("stop_loss_rate", _STOP_LOSS_L1),
        pm.get("stop_loss_rate", _STOP_LOSS_L1),
        _STOP_LOSS_L1,
        "neg",
    )
    risk_limits["max_position_size_rate"] = _apply_one(
        "max_position_size_rate",
        risk_limits.get("max_position_size_rate", _MAX_POS_SIZE_L1),
        pm.get("max_position_size_rate", _MAX_POS_SIZE_L1),
        _MAX_POS_SIZE_L1,
        "pos",
    )
    risk_limits["take_profit_rate"] = _apply_one(
        "take_profit_rate",
        risk_limits.get("take_profit_rate", _TAKE_PROFIT_L1),
        pm.get("take_profit_rate", _TAKE_PROFIT_L1),
        _TAKE_PROFIT_L1,
        "pos",
    )
    risk_limits["max_holding_minutes"] = int(
        _apply_one(
            "max_holding_minutes",
            risk_limits.get("max_holding_minutes", _MAX_HOLDING_MIN_L1),
            pm.get("max_holding_minutes", _MAX_HOLDING_MIN_L1),
            _MAX_HOLDING_MIN_L1,
            "pos",
        )
    )

    return result, cap_log


def _load_pm_settings() -> dict[str, Any]:
    """system_settings에서 PM 설정값을 로드하고 누락 키는 L1 기본값으로 채운다."""
    defaults: dict[str, Any] = {
        "daily_loss_limit_rate": _DAILY_LOSS_LIMIT_L1,
        "max_positions": _MAX_POSITIONS_L1,
        "stop_loss_rate": _STOP_LOSS_L1,
        "max_position_size_rate": _MAX_POS_SIZE_L1,
        "take_profit_rate": _TAKE_PROFIT_L1,
        "max_holding_minutes": _MAX_HOLDING_MIN_L1,
    }
    try:
        settings = list_settings()
        loaded = {item["key"]: item["value"] for item in settings}
        for key in defaults:
            if key in loaded:
                defaults[key] = loaded[key]
    except Exception as exc:
        logger.warning("WARN: RulePackGen PM settings 로드 실패 — L1 기본값 사용 %s", exc)
    return defaults


def _get_market_tone(trade_date: str) -> dict[str, Any] | None:
    """market_tone_results에서 지정 거래일의 최신 시장 톤을 조회한다."""
    try:
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT tone, confidence, summary
                FROM market_tone_results
                WHERE trade_date = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (trade_date,),
            ).fetchone()
        if row is not None:
            return {"tone": row["tone"], "confidence": row["confidence"], "summary": row["summary"]}
    except Exception as exc:
        logger.warning("WARN: RulePackGen 시장 톤 조회 실패 — %s", exc)
    return None


def _get_yesterday_rulepack(today: str) -> dict[str, Any] | None:
    """오늘 기준 전일 날짜의 활성 RulePack을 조회한다."""
    from datetime import date, timedelta

    yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
    try:
        return get_active_rulepack_for_date(yesterday)
    except Exception as exc:
        logger.warning("WARN: RulePackGen 어제 RulePack 조회 실패 — %s", exc)
        return None


def _build_prompt(
    market_tone: dict[str, Any] | None,
    screening: dict[str, Any] | None,
    yesterday_rulepack: dict[str, Any] | None,
) -> str:
    """0845_gpt_rulepack_generation.md 기반으로 LLM 입력 프롬프트를 빌드한다."""
    if market_tone:
        market_tone_str = json.dumps(market_tone, ensure_ascii=False, indent=2)
    else:
        market_tone_str = '{"tone": "neutral", "confidence": 0.5, "summary": "데이터 없음"}'

    if screening and screening.get("candidates"):
        screening_str = json.dumps(screening["candidates"], ensure_ascii=False, indent=2)
    else:
        screening_str = "[]"

    if yesterday_rulepack and yesterday_rulepack.get("machine_rules"):
        machine_rules = yesterday_rulepack["machine_rules"]
        if isinstance(machine_rules, str):
            yesterday_str = machine_rules
        else:
            yesterday_str = json.dumps(machine_rules, ensure_ascii=False, indent=2)
    else:
        yesterday_str = "{}"

    return render_prompt(
        "0845_gpt_rulepack_generation.md",
        {
            "market_tone": market_tone_str,
            "screening_output": screening_str,
            "yesterday_rulepack": yesterday_str,
        },
    )


def _parse_rulepack_response(raw: str) -> dict[str, Any]:
    """LLM 응답 문자열에서 순수 JSON을 추출하고 필수 필드를 검증한다."""
    text = raw.strip()
    if "```" in text:
        lines = text.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            data = json.loads(text[start:end])
        else:
            raise

    if "risk_limits" not in data:
        raise ValueError("LLM 응답에 risk_limits 없음")

    return data


def _apply_caps_and_build_validation(
    rulepack_data: dict[str, Any], pm_settings: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """L1/PM 캐스케이딩 캡을 적용하고 저장용 validation dict를 만든다."""
    capped, cap_log = _apply_l1_caps(rulepack_data, pm_settings)
    capped_fields = [result for result in cap_log if result["capped_by"] != "none"]

    validation = {
        "schema": "pass",
        "risk_policy": "pass",
        "runtime": "pending",
        "cap_applied": capped_fields,
    }
    return capped, validation


def _clone_yesterday_rulepack(
    today: str,
    yesterday_rulepack: dict[str, Any] | None,
    fallback_reason: str,
) -> dict[str, Any] | None:
    """LLM 실패 시 전일 활성 RulePack을 오늘 날짜로 복제 저장하고 활성화한다."""
    if not yesterday_rulepack or not yesterday_rulepack.get("machine_rules"):
        logger.warning("WARN: RulePackGen fallback 불가 — 전일 RulePack 없음 reason=%s", fallback_reason)
        return None

    machine_rules = yesterday_rulepack["machine_rules"]
    if isinstance(machine_rules, str):
        machine_rules = json.loads(machine_rules)
    else:
        machine_rules = json.loads(json.dumps(machine_rules, ensure_ascii=False))

    machine_rules["valid_for_date"] = today
    machine_rules["generated_at"] = datetime.now(timezone.utc).isoformat()
    machine_rules["notes"] = "전일 RulePack 복제"
    validation = {
        "schema": "pass",
        "risk_policy": "pass",
        "runtime": "pending",
        "fallback_reason": fallback_reason,
        "cap_applied": [],
    }

    record = create_rulepack(
        trade_date=today,
        machine_rules=machine_rules,
        summary="전일 RulePack 복제",
        changes="LLM 실패로 전일 활성 RulePack 복제",
        mode="auto",
        validation=validation,
    )
    rulepack_id = record["rulepack_id"]
    update_rulepack_validation(rulepack_id, validation)
    status = "validated"
    try:
        activated = activate_rulepack(rulepack_id)
        status = "active" if activated and activated.get("status") == "active" else "validated"
    except ValueError as exc:
        logger.error("FAIL: RulePackGen fallback 활성화 실패 — %s", exc)

    logger.info("SUCCESS: RulePackGen fallback clone rulepack_id=%s status=%s", rulepack_id, status)
    return {
        "ok": True,
        "trade_date": today,
        "provider": "fallback",
        "rulepack_id": rulepack_id,
        "cap_applied_count": 0,
        "candidates_count": len(machine_rules.get("candidates", [])),
        "status": status,
        "fallback_reason": fallback_reason,
    }


async def run_rulepack_generation() -> dict[str, Any]:
    """RulePack을 자동 생성하고 DB에 저장한 뒤 활성화한다."""
    from zoneinfo import ZoneInfo

    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    logger.info("START: RulePackGenerationService.run trade_date=%s", today)

    screening = get_today_screening(today)
    if screening is None or not screening.get("candidates"):
        logger.warning("WARN: RulePackGen S4 스크리닝 결과 없음 — 생성 생략 trade_date=%s", today)
        return {"ok": True, "trade_date": today, "skipped_reason": "no_screening", "provider": "none"}

    market_tone = _get_market_tone(today)
    yesterday_rulepack = _get_yesterday_rulepack(today)
    pm_settings = _load_pm_settings()
    prompt = _build_prompt(market_tone, screening, yesterday_rulepack)

    llm_result = await llm_router.call_llm(prompt, task_name="RulePack 생성")
    provider = llm_result.get("provider", "none")
    if not llm_result.get("ok"):
        fallback = _clone_yesterday_rulepack(today, yesterday_rulepack, "llm_failed")
        if fallback is not None:
            return fallback
        return {"ok": True, "trade_date": today, "provider": provider, "fallback_reason": "llm_failed"}

    try:
        rulepack_data = _parse_rulepack_response(llm_result["raw"])
    except Exception as parse_exc:
        logger.warning(
            "WARN: RulePackGen JSON 파싱 실패 — %s | raw_preview=%s",
            parse_exc,
            llm_result.get("raw", "")[:200],
        )
        fallback = _clone_yesterday_rulepack(today, yesterday_rulepack, "parse_failed")
        if fallback is not None:
            return fallback
        return {"ok": True, "trade_date": today, "provider": provider, "fallback_reason": "parse_failed"}

    capped_rulepack, validation = _apply_caps_and_build_validation(rulepack_data, pm_settings)
    summary = str(capped_rulepack.get("notes") or "S5 RulePack 자동 생성")[:300]
    record = create_rulepack(
        trade_date=today,
        machine_rules=capped_rulepack,
        summary=summary,
        changes="S4 스크리닝 + 시장 톤 기반 자동 생성",
        mode="auto",
        validation=validation,
    )
    rulepack_id = record["rulepack_id"]
    update_rulepack_validation(rulepack_id, validation)

    status = "validated"
    try:
        activated = activate_rulepack(rulepack_id)
        status = "active" if activated and activated.get("status") == "active" else "validated"
    except ValueError as exc:
        logger.error("FAIL: RulePackGen 활성화 실패 — %s", exc)

    result = {
        "ok": True,
        "trade_date": today,
        "provider": provider,
        "rulepack_id": rulepack_id,
        "cap_applied_count": len(validation.get("cap_applied", [])),
        "candidates_count": len(rulepack_data.get("candidates", [])),
        "status": status,
    }
    logger.info(
        "SUCCESS: RulePackGenerationService rulepack_id=%s provider=%s caps=%d status=%s",
        rulepack_id,
        provider,
        result["cap_applied_count"],
        status,
    )
    return result


def get_today_rulepack(trade_date: str) -> dict[str, Any] | None:
    """지정 거래일의 활성 RulePack을 반환한다."""
    return get_active_rulepack_for_date(trade_date)
