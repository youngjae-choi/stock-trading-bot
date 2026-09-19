"""Rule Resolver — 종목별 최종 룰 계산 (우선순위 레이어 병합).

우선순위 (높을수록 우선):
  1. Emergency Halt / Global Risk Guard  ← 이 파일 밖에서 적용
  2. 장마감 강제청산 정책              ← 이 파일 밖에서 적용
  3. Symbol Override
  4. Risk Profile
  5. Base RulePack
  6. Daily Trading Plan overrides
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..db import get_connection

logger = logging.getLogger("RuleResolver")

_PROFILES = ("LOW_VOL", "MID_VOL", "HIGH_VOL", "THEME_SPIKE")


def _to_float_or_none(value: Any) -> float | None:
    """숫자면 float, 아니면 None (E6 하이브리드 트레일의 5장세 재분류 입력 정규화)."""
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_active_base_rulepack() -> dict[str, Any]:
    """현재 활성 Base RulePack 반환. 없으면 기본값."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM base_rulepacks WHERE is_active = 1 ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    if not row:
        logger.warning("WARN: [RuleResolver] base_rulepack 없음 — 기본값 사용")
        return {
            "id": "base-v1.0",
            "version": "1.0",
            "take_profit_enabled": False,
            "force_daily_close": True,
            "force_exit_time": "15:20:00",
            "stop_price_can_only_increase": True,
        }
    d = dict(row)
    try:
        d["order_execution"] = json.loads(d.get("order_execution") or "{}")
    except Exception:
        d["order_execution"] = {}
    d["take_profit_enabled"] = bool(d.get("take_profit_enabled", 0))
    d["force_daily_close"] = bool(d.get("force_daily_close", 1))
    d["stop_price_can_only_increase"] = bool(d.get("stop_price_can_only_increase", 1))
    return d


def get_active_profile_pack() -> dict[str, Any]:
    """현재 활성 Risk Profile Pack 반환."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM risk_profile_packs WHERE is_active = 1 ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    if not row:
        logger.warning("WARN: [RuleResolver] risk_profile_pack 없음 — 빈 profiles")
        return {"id": "profile-v1.0", "version": "1.0", "profiles": {}}
    d = dict(row)
    try:
        d["profiles"] = json.loads(d.get("profiles") or "{}")
    except Exception:
        d["profiles"] = {}
    return d


def get_active_daily_plan(trade_date: str) -> dict[str, Any] | None:
    """특정 날짜의 활성 Daily Trading Plan 반환."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM daily_trading_plans WHERE trade_date = ? AND status IN ('validated','active')"
            " ORDER BY created_at DESC LIMIT 1",
            (trade_date,),
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    for key in ("daily_overrides", "symbol_assignments", "excluded_symbols", "validation_result"):
        try:
            d[key] = json.loads(d.get(key) or "{}") if key in ("daily_overrides", "validation_result") else json.loads(d.get(key) or "[]")
        except Exception:
            d[key] = {} if key in ("daily_overrides", "validation_result") else []
    return d


def get_symbol_overrides() -> dict[str, dict[str, Any]]:
    """활성 symbol_overrides 전체 반환. {symbol_code: override_values}."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT symbol_code, override_values FROM symbol_overrides WHERE is_active = 1"
        ).fetchall()
    result = {}
    for row in rows:
        try:
            result[row["symbol_code"]] = json.loads(row["override_values"] or "{}")
        except Exception:
            result[row["symbol_code"]] = {}
    return result


def _settings_gate_rules() -> dict[str, Any]:
    """매수 게이트값(밴드·확신도·거래량)을 settings 단일출처에서 주입. **RulePack 제거(2026-08-23 PM).**

    구 daily RulePack(rulepacks 테이블·매일 생성)은 `engine.*` settings의 복사본이라 중복·드리프트만
    유발했다(예: RulePack conf 0.65 vs settings 0.60) → 매매를 RulePack에서 분리하고 여기서 직접 주입.
    decision_rules는 final_rule에서 이 값을 읽으므로 구조 불변(밴드 미주입 시 0.0/999 무효화 방지).
    손절/트레일은 이 뒤 단계(프로필/레짐SET)가 담당 — RulePack과 무관.
    """
    from ..settings_store import get_setting as _gs

    def _f(key: str, default: float) -> float:
        try:
            return float(_gs(key, default))
        except (TypeError, ValueError):
            return default

    return {
        "min_price_change_pct": _f("engine.min_price_change_pct", 1.5),
        "max_price_change_pct": _f("engine.max_price_change_pct", 4.0),
        "min_ai_confidence": _f("engine.min_ai_confidence", 0.60),
        "volume_ratio_min": _f("engine.min_volume_ratio", 1.5),
    }


def resolve_symbol_rule(
    symbol_code: str,
    base_rulepack: dict[str, Any],
    profile_pack: dict[str, Any],
    daily_plan: dict[str, Any] | None,
    symbol_overrides: dict[str, dict[str, Any]],
    global_risk: dict[str, Any],
    trade_date: str = "",
) -> dict[str, Any]:
    """종목별 최종 룰 계산.

    레이어 병합 순서 (나중에 덮음 = 높은 우선순위):
      base_rulepack → active rulepack machine_rules → profile → symbol_override
    그 후 Global Risk Guard 강제 적용.

    Args:
        symbol_code: Stock symbol to resolve.
        base_rulepack: Active base RulePack row converted to dict.
        profile_pack: Active risk profile pack with profile rules.
        daily_plan: Active daily trading plan for assignment lookup.
        symbol_overrides: Per-symbol override mapping.
        global_risk: Global Risk Guard settings from system_settings.
        trade_date: YYYY-MM-DD date used to read active generated RulePack machine rules.
    """
    # 1. Daily Plan에서 배정 프로필 조회
    assignments: dict[str, dict] = {}
    if daily_plan:
        for a in daily_plan.get("symbol_assignments", []):
            code = str(a.get("code") or "").strip()
            if code:
                assignments[code] = a
    assignment = assignments.get(symbol_code, {})
    profile_name = assignment.get("profile", "MID_VOL")
    if profile_name not in _PROFILES:
        profile_name = "MID_VOL"

    profiles = profile_pack.get("profiles", {})
    profile_rule = profiles.get(profile_name, {})
    # RulePack 제거(2026-08-23 PM): 게이트값을 rulepacks 테이블 대신 settings 단일출처에서.
    gate_rules = _settings_gate_rules()

    # 2. 레이어 병합 (base_rulepack=정적 실행설정 유지 · gate=settings · profile=손절)
    final: dict[str, Any] = {}
    final.update({k: v for k, v in base_rulepack.items() if k not in ("id", "version", "created_at", "is_active", "order_execution")})
    final.update(gate_rules)
    final.update(profile_rule)

    # Phase 3(2026-08-22, PM): engine.stop_source == "regime" 면 종목별 프로필 대신 당일 레짐SET의
    # 손절/트레일을 단일 출처로 적용한다. 기본 "profile" = 현행(라이브 무변화). 롤백 스위치.
    # 필드명 매핑: 레짐SET applied_settings.stop_loss_rate → final.initial_stop_loss(프로필 필드명).
    from ..settings_store import get_setting as _gs
    if str(_gs("engine.stop_source", "profile") or "profile").lower() == "regime" and trade_date:
        try:
            from ..regime_set_service import get_today_application
            _app = get_today_application(trade_date)
            _aps = (_app or {}).get("applied_settings") or {}
            if isinstance(_aps, str):
                _aps = json.loads(_aps)
            if _aps.get("stop_loss_rate") is not None:
                final["initial_stop_loss"] = float(_aps["stop_loss_rate"])
            if _aps.get("trailing_activate_profit") is not None:
                final["trailing_activate_profit"] = float(_aps["trailing_activate_profit"])
            if _aps.get("trailing_stop_rate") is not None:
                final["trailing_stop_rate"] = float(_aps["trailing_stop_rate"])
            final["stop_source"] = "regime"
        except Exception as _exc:
            logger.warning("WARN: [RuleResolver] regime stop_source 적용 실패(프로필 유지) — %s", _exc)

    # E6 하이브리드 트레일 오버라이드(2026-09-18 상승장 필승패턴) — 상승/폭등장 전용 청산 튜닝.
    #   상승장(up/risk_on): +2% 발동·1.5% 트레일 / 폭등장(surge): +3% 발동·2% 트레일(더 태움).
    #   보합/하락/변동성은 절대 미오버라이드(레짐SET 값 유지 = 구동작 불변). 하드손절(initial_stop_loss)은 유지.
    #   레짐SET/스냅샷의 regime_label은 SET 4종(risk_on/…)이라 surge↔up을 구분 못한다 →
    #   당일 application에 기록된 kospi_change_pct/vix로 classify_regime_5tier를 다시 돌려 5장세를 복원한다
    #   (이 코드베이스가 이미 쓰는 분류기 재사용). 이 지점이 trailing_activate_profit/trailing_stop_rate의
    #   **최종 권위**(add_position이 여기서 캐시된 final_rule을 읽음) — 다른 곳에서 중복 적용하지 않는다.
    #   롤백=engine.exit_hybrid_mode=off(오버라이드 완전 비활성). fail-open(예외 시 기존 값 유지).
    if str(_gs("engine.exit_hybrid_mode", "enforce") or "enforce").lower() == "enforce" and trade_date:
        try:
            from ..regime_set_service import get_today_application
            from .market_sensing import classify_regime_5tier
            _app_h = get_today_application(trade_date)
            if _app_h:
                _kospi_h = _to_float_or_none(_app_h.get("kospi_change_pct"))
                _vix_h = _to_float_or_none(_app_h.get("vix_value"))
                _r5 = classify_regime_5tier(_kospi_h, _vix_h)
                if _r5 == "surge":
                    final["trailing_activate_profit"] = float(_gs("engine.exit_surge_trail_activate", 0.03))
                    final["trailing_stop_rate"] = float(_gs("engine.exit_surge_trail_stop", 0.02))
                    final["exit_hybrid"] = "surge"
                elif _r5 in ("up", "risk_on"):
                    final["trailing_activate_profit"] = float(_gs("engine.exit_riskon_trail_activate", 0.02))
                    final["trailing_stop_rate"] = float(_gs("engine.exit_riskon_trail_stop", 0.015))
                    final["exit_hybrid"] = "up"
                # else(flat/down/crash/volatile): 오버라이드 없음 — 레짐SET 값 유지(불변)
        except Exception as _exc_h:
            logger.warning("WARN: [RuleResolver] E6 하이브리드 트레일 적용 실패(기존 유지) — %s", _exc_h)

    final.update(symbol_overrides.get(symbol_code, {}))

    # 3. Global Risk Guard 강제 (절대 완화 불가)
    # 가드는 Risk Profile Pack의 최대 비중(LOW_VOL 15%)을 깎지 않도록 0.15로 둔다.
    # 프로파일별 max_position_rate(15/12/8/5%)가 그대로 적용된다. (PM 결정 2026-06-02)
    guard_max_pos_rate = float(global_risk.get("max_position_rate_per_stock", 0.15))
    final["max_position_rate"] = min(
        float(final.get("max_position_rate", guard_max_pos_rate)),
        guard_max_pos_rate,
    )
    # 프로필별 종목당 최대금액(원) — 사이징 금액모델 위 프로필 캡(2026-08-29 PM). 없으면 None(캡 없음).
    try:
        _pmk = float(final.get("max_position_krw") or 0)
    except (TypeError, ValueError):
        _pmk = 0.0
    final["max_position_krw"] = _pmk if _pmk > 0 else None
    final["max_positions"] = int(global_risk.get("max_positions", final.get("max_positions", 5)) or 5)
    final["force_exit_time"] = global_risk.get("force_exit_time", "15:20:00")
    final["new_entry_cutoff_time"] = global_risk.get("new_entry_cutoff_time", "15:10:00")
    final["take_profit_enabled"] = False               # 항상 OFF
    final["stop_price_can_only_increase"] = True       # 항상 ON
    final["profile_assigned"] = profile_name
    final["assignment_reason"] = assignment.get("reason", "")

    return final
