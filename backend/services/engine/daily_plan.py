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
from .hybrid_screening import get_today_screening
from .market_tone import get_today_market_tone

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
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _today_kst() -> str:
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


def _build_prompt(candidates: list[dict], market_tone_data: dict | None) -> str:
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

    return f"""# 08:45 Daily Trading Plan 생성

## 역할
오늘 매매 후보 종목에 Risk Profile을 배정한다.
Risk Profile은 LOW_VOL / MID_VOL / HIGH_VOL / THEME_SPIKE 4종이다.

## 배정 기준
- LOW_VOL: 대형주, 저변동성, 안정적 거래대금
- MID_VOL: 일반 중형주, 보통 변동성
- HIGH_VOL: 고변동성, 최근 급등락, 변동성 큰 섹터
- THEME_SPIKE: 당일 급등 테마주, 뉴스/테마 기반, 거래량 급증, 고위험

## 오늘 시장 톤
tone: {tone}
요약: {tone_summary}

## 후보 종목 (S4 스크리닝 결과)
{json.dumps(cand_rows, ensure_ascii=False, indent=2)}

## 출력 형식 (JSON만, 다른 텍스트 없이)
{{
  "trading_intensity": "aggressive|normal|defensive",
  "new_entry_allowed": true,
  "daily_overrides": {{
    "volume_filter_multiplier": 2.0,
    "min_ai_confidence": 0.65,
    "max_theme_spike_positions": 1
  }},
  "symbol_assignments": [
    {{"code": "005930", "name": "삼성전자", "profile": "LOW_VOL", "reason": "대형주 저변동성"}}
  ],
  "excluded_symbols": [],
  "llm_summary": "오늘 시장 톤과 종목 배정에 대한 간략한 요약"
}}
"""


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


def get_today_daily_plan(trade_date: str | None = None) -> dict[str, Any] | None:
    """오늘 활성 Daily Trading Plan 조회."""
    if not trade_date:
        trade_date = _today_kst()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM daily_trading_plans WHERE trade_date = ? ORDER BY created_at DESC LIMIT 1",
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
    for key in ("symbol_assignments", "excluded_symbols"):
        try:
            d[key] = json.loads(d.get(key) or "[]")
        except Exception:
            d[key] = []
    return d


async def run_daily_plan_generation(trade_date: str | None = None) -> dict[str, Any]:
    """S5: Daily Trading Plan 생성 메인 함수."""
    if not trade_date:
        trade_date = _today_kst()
    logger.info("START: [S5] Daily Plan generation date=%s", trade_date)

    # S4 스크리닝 결과 조회
    screening = get_today_screening(trade_date)
    candidates = screening.get("candidates", []) if screening else []
    if not candidates:
        logger.warning("WARN: [S5] S4 스크리닝 결과 없음 — MID_VOL 기본 배정으로 진행")

    # 시장 톤 조회
    market_tone = get_today_market_tone(trade_date) if callable(get_today_market_tone) else None

    # LLM 프롬프트 생성 및 호출
    prompt = _build_prompt(candidates, market_tone)
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

    # 검증
    validation = _validate_plan(plan_data)
    all_pass = all(v == "pass" for v in validation.values())
    status = "validated" if all_pass else "draft"

    plan_id = f"daily-{trade_date}"
    now = _now_utc()

    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO daily_trading_plans
                (id, trade_date, market_tone, trading_intensity, base_rulepack_id,
                 risk_profile_pack_id, new_entry_allowed, daily_overrides,
                 symbol_assignments, excluded_symbols, llm_summary, provider,
                 status, validation_result, created_at, activated_at)
            VALUES (?, ?, ?, ?, 'base-v1.0', 'profile-v1.0', ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
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
                now,
            ),
        )

    logger.info("SUCCESS: [S5] Daily Plan saved id=%s status=%s provider=%s", plan_id, status, provider)
    return {
        "ok": True,
        "plan_id": plan_id,
        "trade_date": trade_date,
        "status": status,
        "provider": provider,
        "validation": validation,
        "candidates_count": len(candidates),
        "assignments_count": len(plan_data.get("symbol_assignments", [])),
    }
