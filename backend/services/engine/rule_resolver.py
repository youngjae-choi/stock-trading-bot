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


def _get_active_rulepack_entry_rules(trade_date: str) -> dict[str, Any]:
    """활성 RulePack의 machine_rules.entry_rules 반환. 없으면 빈 dict.

    Args:
        trade_date: YYYY-MM-DD trade date used to select the active RulePack.
    """
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT machine_rules FROM rulepacks"
                " WHERE trade_date = ? AND status = 'active'"
                " ORDER BY created_at DESC LIMIT 1",
                (trade_date,),
            ).fetchone()
        if not row or not row["machine_rules"]:
            return {}
        machine_rules = json.loads(row["machine_rules"])
        return machine_rules.get("entry_rules", {}) or {}
    except Exception as exc:
        logger.warning("WARN: [RuleResolver] rulepack entry_rules 조회 실패 — %s", exc)
        return {}


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
      base_rulepack → active rulepack entry_rules → profile → symbol_override
    그 후 Global Risk Guard 강제 적용.

    Args:
        symbol_code: Stock symbol to resolve.
        base_rulepack: Active base RulePack row converted to dict.
        profile_pack: Active risk profile pack with profile rules.
        daily_plan: Active daily trading plan for assignment lookup.
        symbol_overrides: Per-symbol override mapping.
        global_risk: Global Risk Guard settings from system_settings.
        trade_date: YYYY-MM-DD date used to read active generated RulePack entry rules.
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
    rulepack_entry = _get_active_rulepack_entry_rules(trade_date) if trade_date else {}

    # 2. 레이어 병합
    final: dict[str, Any] = {}
    final.update({k: v for k, v in base_rulepack.items() if k not in ("id", "version", "created_at", "is_active", "order_execution")})
    final.update(rulepack_entry)
    final.update(profile_rule)
    final.update(symbol_overrides.get(symbol_code, {}))

    # 3. Global Risk Guard 강제 (절대 완화 불가)
    guard_max_pos_rate = float(global_risk.get("max_position_rate_per_stock", 0.10))
    final["max_position_rate"] = min(
        float(final.get("max_position_rate", guard_max_pos_rate)),
        guard_max_pos_rate,
    )
    final["force_exit_time"] = global_risk.get("force_exit_time", "15:20:00")
    final["new_entry_cutoff_time"] = global_risk.get("new_entry_cutoff_time", "15:10:00")
    final["take_profit_enabled"] = False               # 항상 OFF
    final["stop_price_can_only_increase"] = True       # 항상 ON
    final["profile_assigned"] = profile_name
    final["assignment_reason"] = assignment.get("reason", "")

    return final
