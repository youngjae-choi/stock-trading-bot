"""RulePack 자동 생성 서비스 (S5 — 08:45 KST).

S4 하이브리드 스크리닝 결과, 시장 톤, 어제 RulePack을 조합해
문서화된 룩업 테이블(tone_score→max_positions/take_profit_rate,
suitability_score≥0.5 상위 10개 후보)로 RulePack JSON을 결정론적으로 구성한다.
LLM 호출은 사용하지 않는다.

결과에 인라인 L1 절대한도 + PM Settings 캐스케이딩 캡을 적용하고
rulepacks 테이블에 저장한 뒤 자동 활성화한다.
입력(시장 톤)이 없으면 전일 RulePack을 복제한다.

RulePack 스키마: backend/prompts/0845_gpt_rulepack_generation.md 참조.
machine_rules 컬럼에 결정론적 생성 전체 JSON을 저장한다.
"""

from __future__ import annotations

import copy
import json
import logging
from datetime import datetime, timezone
from typing import Any

from ..db import get_connection
from ..settings_store import list_settings
from .hybrid_screening import get_today_screening
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


def _get_morning_context(trade_date: str) -> dict[str, Any]:
    """morning_context 테이블에서 오늘 시장 컨텍스트를 로드한다. 없으면 빈 dict."""
    try:
        from .market_tone import get_today_morning_context
        ctx = get_today_morning_context(trade_date)
        return ctx if ctx else {}
    except Exception as exc:
        logger.warning("WARN: RulePackGen morning_context 로드 실패 — %s", exc)
        return {}


def _kospi_change_line(mdata: Any) -> str:
    """KOSPI 당일 등락률 라인 (P3-1 공란 주입 수정).

    morning_context.market_data.kospi → 실시간 market_snapshots 순으로 조회하고,
    끝까지 없으면 'N/A' 명시 — 빈 문자열/누락으로 시황을 추측하게 두지 않는다.
    """
    if isinstance(mdata, dict):
        kospi = mdata.get("kospi")
        if kospi and isinstance(kospi, dict) and kospi.get("change_pct") is not None:
            try:
                return f"KOSPI: {kospi.get('price')} ({float(kospi['change_pct']):+.2f}%)"
            except (TypeError, ValueError):
                pass
    try:
        from .intraday_regime_monitor import _get_current_kospi_change

        chg = _get_current_kospi_change()
        if chg is not None:
            return f"KOSPI 당일 등락률: {chg:+.2f}% (실시간 스냅샷)"
    except Exception:
        pass
    return "KOSPI 당일 등락률: N/A (데이터 미수집)"


def _format_morning_context_for_prompt(ctx: dict[str, Any]) -> str:
    """morning_context를 사람이 읽을 수 있는 시장 컨텍스트 텍스트로 변환한다."""
    if not ctx:
        return "데이터 없음"
    lines = [
        f"시장 레짐: {ctx.get('regime', 'N/A')}",
        f"리스크 레벨: {ctx.get('risk_level', 'N/A')}",
        _kospi_change_line(ctx.get("market_data", {})),
        f"주도 종목 성격: {ctx.get('stock_character', 'N/A')}",
        f"RulePack 힌트: {ctx.get('rulepack_hint', 'N/A')}",
    ]
    mdata = ctx.get("market_data", {})
    if isinstance(mdata, dict):
        for k, label in [("nasdaq", "NASDAQ"), ("sp500", "S&P500"), ("vix", "VIX"),
                         ("nikkei", "닛케이"), ("hangseng", "항셍"), ("usdkrw", "USD/KRW")]:
            item = mdata.get(k)
            if item and isinstance(item, dict):
                pct = float(item.get("change_pct") or 0.0)
                lines.append(f"  {label}: {item.get('price')} ({pct:+.2f}%)")
    key_factors = ctx.get("key_factors", [])
    if key_factors:
        lines.append(f"핵심 요인: {', '.join(str(item) for item in key_factors)}")
    risk_factors = ctx.get("risk_factors", [])
    if risk_factors:
        lines.append(f"리스크 요인: {', '.join(str(item) for item in risk_factors)}")
    return "\n".join(lines)


def _get_yesterday_rulepack(today: str) -> dict[str, Any] | None:
    """오늘 기준 전일 날짜의 활성 RulePack을 조회한다."""
    from datetime import date, timedelta

    yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
    try:
        return get_active_rulepack_for_date(yesterday)
    except Exception as exc:
        logger.warning("WARN: RulePackGen 어제 RulePack 조회 실패 — %s", exc)
        return None


def _tone_score(market_tone: dict[str, Any]) -> float:
    """시장 톤(label/regime)을 문서화된 tone_score 축으로 환산한다.

    market_tone_results 행은 숫자 tone_score가 아니라 tone 라벨
    (positive/negative/neutral) 또는 regime 문자열을 제공하므로,
    0845_gpt_rulepack_generation.md의 임계값(>=0.5 risk_on / >=0.0 neutral
    / <0 risk_off)과 맞도록 대표값으로 매핑한다.

    Args:
        market_tone: _get_market_tone가 반환한 tone/confidence/summary dict.
    """
    label = str(market_tone.get("tone") or market_tone.get("regime") or "neutral").strip().lower()
    if label in ("positive", "risk_on"):
        return 0.5
    if label in ("negative", "risk_off"):
        return -0.5
    return 0.0


def _map_max_positions(tone_score: float) -> int:
    """tone_score → max_positions 추천값 (문서화된 룩업 테이블)."""
    if tone_score >= 0.5:
        return 10
    if tone_score >= 0.0:
        return 7
    return 5


def _map_take_profit_rate(tone_score: float) -> float:
    """tone_score → take_profit_rate 추천값 (문서화된 룩업 테이블)."""
    if tone_score >= 0.5:
        return 0.05
    if tone_score >= 0.0:
        return 0.04
    return 0.03


def _select_candidates(screening: dict[str, Any] | None) -> list[dict[str, Any]]:
    """suitability_score >= 0.5 인 후보를 점수 내림차순 상위 10개로 선정한다.

    max_buy_amount_krw는 사이징 단계에서 채워지므로 0으로 둔다
    (0845_gpt_rulepack_generation.md candidates 선정 규칙).

    Args:
        screening: get_today_screening가 반환한 dict (candidates 포함).
    """
    raw_candidates = (screening or {}).get("candidates") or []
    scored: list[tuple[float, dict[str, Any]]] = []
    for item in raw_candidates:
        if not isinstance(item, dict):
            continue
        try:
            suitability = float(item.get("suitability_score") or 0.0)
        except (TypeError, ValueError):
            suitability = 0.0
        if suitability < 0.5:
            continue
        ticker = str(item.get("ticker") or item.get("symbol") or "").strip()
        if not ticker:
            continue
        scored.append((suitability, item))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    selected: list[dict[str, Any]] = []
    for rank, (suitability, item) in enumerate(scored[:10], start=1):
        selected.append(
            {
                "ticker": str(item.get("ticker") or item.get("symbol") or "").strip(),
                "name": str(item.get("name") or ""),
                "rank": rank,
                "suitability_score": round(suitability, 4),
                "max_buy_amount_krw": 0,
                "reason_short": str(item.get("reason_short") or item.get("reason") or ""),
            }
        )
    return selected


def _tone_label(tone_score: float) -> str:
    """tone_score → market_context.tone_label/regime 문자열."""
    if tone_score >= 0.5:
        return "risk_on"
    if tone_score >= 0.0:
        return "neutral"
    return "risk_off"


def _build_deterministic_rulepack(
    today: str,
    market_tone: dict[str, Any],
    screening: dict[str, Any] | None,
    yesterday_rulepack: dict[str, Any] | None,
    morning_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """문서화된 룩업 테이블만으로 RulePack JSON을 결정론적으로 구성한다.

    0845_gpt_rulepack_generation.md의 "JSON 변환기" 규칙을 코드로 옮긴 것으로,
    LLM 호출 없이 시장 톤과 스크리닝 후보에서 RulePack을 산출한다.
    risk_limits는 이후 _apply_l1_caps가 L1/PM 한도로 하드 클램프한다.

    Args:
        today: 대상 거래일(YYYY-MM-DD).
        market_tone: _get_market_tone가 반환한 시장 톤 dict.
        screening: get_today_screening가 반환한 스크리닝 결과.
        yesterday_rulepack: 전일 활성 RulePack (risk_limits 유지 참고용).
        morning_context: morning_context 테이블 로드 결과 (regime/risk_level 참고).
    """
    tone_score = _tone_score(market_tone)
    max_positions = _map_max_positions(tone_score)
    take_profit_rate = _map_take_profit_rate(tone_score)
    candidates = _select_candidates(screening)

    ctx = morning_context or {}
    regime = str(ctx.get("regime") or _tone_label(tone_score))
    risk_level = str(ctx.get("risk_level") or "normal")

    try:
        confidence = float(market_tone.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0

    yesterday_rules: dict[str, Any] = {}
    if yesterday_rulepack and yesterday_rulepack.get("machine_rules"):
        machine_rules = yesterday_rulepack["machine_rules"]
        if isinstance(machine_rules, str):
            try:
                machine_rules = json.loads(machine_rules)
            except json.JSONDecodeError:
                machine_rules = {}
        if isinstance(machine_rules, dict):
            yesterday_rules = machine_rules

    yesterday_risk = yesterday_rules.get("risk_limits") or {}
    risk_limits = {
        "daily_loss_limit_rate": yesterday_risk.get("daily_loss_limit_rate", _DAILY_LOSS_LIMIT_L1),
        "max_positions": max_positions,
        "stop_loss_rate": yesterday_risk.get("stop_loss_rate", _STOP_LOSS_L1),
        "take_profit_rate": take_profit_rate,
        "max_position_size_rate": yesterday_risk.get("max_position_size_rate", _MAX_POS_SIZE_L1),
        "max_holding_minutes": yesterday_risk.get("max_holding_minutes", _MAX_HOLDING_MIN_L1),
    }

    generated_at = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "valid_for_date": today,
        "market_context": {
            "tone_score": tone_score,
            "tone_label": _tone_label(tone_score),
            "regime": regime,
            "risk_level": risk_level,
            "confidence": confidence,
        },
        "risk_limits": risk_limits,
        "entry_rules": yesterday_rules.get("entry_rules")
        or {
            "buy_signal_priority": ["volume_surge", "price_breakout", "news_match"],
            "min_volume_multiple_5d": 1.5,
            "min_price_change_pct": 1.0,
            "max_price_change_pct": 5.0,
            "exclude_market_open_minutes": 5,
            "exclude_market_close_minutes": 30,
        },
        "exit_rules": yesterday_rules.get("exit_rules")
        or {
            "stop_loss_trigger": "rate_based",
            "take_profit_trigger": "rate_based",
            "force_close_at": "15:20",
            "max_concurrent_trades_per_ticker": 1,
        },
        "candidates": candidates,
        "fallback_policy": yesterday_rules.get("fallback_policy")
        or {
            "if_market_data_unavailable": "skip_trading_today",
            "if_loss_limit_hit": "close_all_block_new",
            "if_api_error_count_exceeds": 5,
        },
        "notes": f"S5 RulePack 결정론적 생성 (tone_score={tone_score:+.2f}, candidates={len(candidates)})",
    }


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
    morning_ctx = _get_morning_context(today)

    provider = "deterministic"
    if market_tone is None:
        fallback = _clone_yesterday_rulepack(today, yesterday_rulepack, "no_market_tone")
        if fallback is not None:
            return fallback
        return {"ok": True, "trade_date": today, "provider": provider, "fallback_reason": "no_market_tone"}

    rulepack_data = _build_deterministic_rulepack(
        today, market_tone, screening, yesterday_rulepack, morning_ctx
    )

    capped_rulepack, validation = _apply_caps_and_build_validation(rulepack_data, pm_settings)
    summary = str(capped_rulepack.get("notes") or "S5 RulePack 결정론적 생성")[:300]
    record = create_rulepack(
        trade_date=today,
        machine_rules=capped_rulepack,
        summary=summary,
        changes="S4 스크리닝 + 시장 톤 기반 결정론적 생성",
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


def get_active_rulepack(trade_date: str) -> dict[str, Any] | None:
    """특정 날짜의 active/validated RulePack을 조회해 분석 스냅샷용 dict로 반환한다.

    Args:
        trade_date: 조회할 거래일(YYYY-MM-DD).
    """
    try:
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT rulepack_id, status, machine_rules, created_at, activated_at
                FROM rulepacks
                WHERE trade_date = ? AND status IN ('active', 'validated')
                ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END, created_at DESC
                LIMIT 1
                """,
                (trade_date,),
            ).fetchone()
        if row is None:
            return None
        record = dict(row)
        machine_rules = record.get("machine_rules")
        if isinstance(machine_rules, str):
            record["machine_rules"] = json.loads(machine_rules)
        if isinstance(record.get("machine_rules"), dict):
            merged = dict(record["machine_rules"])
            merged.update(
                {
                    "rulepack_id": record.get("rulepack_id", ""),
                    "status": record.get("status", ""),
                    "created_at": record.get("created_at", ""),
                    "activated_at": record.get("activated_at"),
                    "machine_rules": record["machine_rules"],
                }
            )
            return merged
        return record
    except Exception as exc:
        logger.warning("WARN: RulePackGenerationService active rulepack 조회 실패 trade_date=%s error=%s", trade_date, exc)
        return None
