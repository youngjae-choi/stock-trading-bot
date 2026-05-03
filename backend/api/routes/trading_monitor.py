"""Trading Monitor API — 매수 대기 후보 + 보유 포지션 + 매수 준비도 조회."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter

from ...services.engine.daily_plan import get_today_daily_plan
from ...services.engine.rule_cache import get_all_cached, get_rule
from ...services.engine.position_manager import position_manager
from ...services.db import get_connection

router = APIRouter(prefix="/api/v1/trading-monitor", tags=["trading-monitor"])
logger = logging.getLogger("TradingMonitorAPI")


def _today_kst() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


def _compute_buy_readiness(candidate: dict[str, Any], rule: dict[str, Any] | None) -> dict[str, Any]:
    """매수 준비도 계산.

    조건 목록과 임계치는 rule + candidate에서 동적으로 구성한다.
    각 조건은 {name, label, current_value, threshold_label, score_pct, met} 형태.
    score_pct: 0.0~100.0 (조건 근접 정도)
    """
    conditions: list[dict[str, Any]] = []

    # AI 신뢰도
    ai_conf = float(candidate.get("suitability_score") or candidate.get("confidence") or 0.0)
    ai_min = float((rule or {}).get("ai_confidence_min", 0.65))
    ai_score = min(ai_conf / ai_min, 1.0) * 100 if ai_min > 0 else 100.0
    conditions.append({
        "name": "ai_confidence",
        "label": "AI 신뢰도",
        "current_value": round(ai_conf, 3),
        "threshold_label": f">= {ai_min:.2f}",
        "score_pct": round(ai_score, 1),
        "met": ai_conf >= ai_min,
    })

    # 거래량 배수 (candidate에 volume_ratio 있으면 사용)
    vol_ratio = float(candidate.get("volume_ratio") or candidate.get("vol_ratio") or 0.0)
    vol_min = float((rule or {}).get("volume_ratio_min", 2.0))
    if vol_ratio > 0:
        vol_score = min(vol_ratio / vol_min, 1.0) * 100 if vol_min > 0 else 100.0
        conditions.append({
            "name": "volume_ratio",
            "label": "거래량 배수",
            "current_value": round(vol_ratio, 2),
            "threshold_label": f">= {vol_min:.1f}x",
            "score_pct": round(vol_score, 1),
            "met": vol_ratio >= vol_min,
        })

    # 등락률 (과도한 급등은 제외)
    change_rate = float(candidate.get("change_rate") or candidate.get("chg_rate") or 0.0)
    if change_rate != 0:
        # 양수 등락이 좋지만 너무 높으면 리스크 (>15% 이상이면 위험)
        rate_score = max(0.0, min(change_rate / 10.0, 1.0)) * 100 if change_rate > 0 else 0.0
        conditions.append({
            "name": "change_rate",
            "label": "등락률",
            "current_value": round(change_rate, 2),
            "threshold_label": "0% ~ 15%",
            "score_pct": round(rate_score, 1),
            "met": 0 < change_rate < 15,
        })

    # VWAP (candidate에 vwap_position 있으면 표시)
    vwap_pos = candidate.get("vwap_position")
    if vwap_pos is not None:
        vwap_met = str(vwap_pos).lower() in ("above", "상단", "위")
        conditions.append({
            "name": "vwap_position",
            "label": "VWAP 상단",
            "current_value": str(vwap_pos),
            "threshold_label": "상단",
            "score_pct": 100.0 if vwap_met else 0.0,
            "met": vwap_met,
        })

    # 종합 점수 계산 (단순 평균)
    if conditions:
        overall = sum(c["score_pct"] for c in conditions) / len(conditions)
    else:
        overall = 0.0

    return {
        "overall_pct": round(overall, 1),
        "met_count": sum(1 for c in conditions if c["met"]),
        "total_count": len(conditions),
        "conditions": conditions,
    }


@router.get("/candidates")
def get_candidates():
    """매수 대기 후보 종목 목록 + Profile + 매수 준비도."""
    today = _today_kst()
    plan = get_today_daily_plan(today)
    if not plan:
        return {"ok": True, "payload": {"candidates": [], "plan_id": None}}

    all_rules = get_all_cached()
    assignments = {a["code"]: a for a in plan.get("symbol_assignments", [])}
    excluded = {e["code"] for e in plan.get("excluded_symbols", [])}

    # hybrid_screening_results에서 오늘 후보 조회
    with get_connection() as conn:
        row = conn.execute(
            "SELECT candidates FROM hybrid_screening_results WHERE trade_date = ? ORDER BY created_at DESC LIMIT 1",
            (today,),
        ).fetchone()

    import json as _json
    raw_candidates: list[dict] = []
    if row:
        try:
            raw_candidates = _json.loads(row["candidates"] or "[]")
        except Exception:
            raw_candidates = []

    # daily_overrides 조건 읽기
    overrides = plan.get("daily_overrides", {})

    result = []
    for c in raw_candidates:
        code = str(c.get("symbol") or c.get("ticker") or "").strip()
        if not code or code in excluded:
            continue
        assignment = assignments.get(code, {})
        rule = all_rules.get(code) or {}

        # daily_overrides로 rule 보완
        if overrides.get("min_ai_confidence"):
            rule["ai_confidence_min"] = overrides["min_ai_confidence"]
        if overrides.get("volume_filter_multiplier"):
            rule["volume_ratio_min"] = overrides["volume_filter_multiplier"]

        readiness = _compute_buy_readiness(c, rule)
        result.append({
            "code": code,
            "name": c.get("name") or "",
            "profile": assignment.get("profile") or rule.get("profile_assigned") or "MID_VOL",
            "assignment_reason": assignment.get("reason") or "",
            "score": c.get("suitability_score") or c.get("score") or 0,
            "change_rate": c.get("change_rate") or 0,
            "ws_subscribed": code in all_rules,
            "buy_readiness": readiness,
        })

    result.sort(key=lambda x: x["buy_readiness"]["overall_pct"], reverse=True)
    return {"ok": True, "payload": {
        "candidates": result,
        "plan_id": plan.get("id"),
        "daily_overrides": overrides,
    }}


@router.get("/positions")
def get_positions():
    """보유 포지션 + 트레일링 스탑 상태."""
    positions = position_manager.get_positions()

    # position_stop_states DB에서 최신 상태 반영
    if positions:
        with get_connection() as conn:
            for pos in positions:
                row = conn.execute(
                    "SELECT * FROM position_stop_states WHERE position_id = ?",
                    (pos.get("position_id", ""),),
                ).fetchone()
                if row:
                    pos.update({
                        "highest_price_since_entry": row["highest_price_since_entry"],
                        "initial_stop_price": row["initial_stop_price"],
                        "trailing_stop_price": row["trailing_stop_price"],
                        "active_stop_price": row["active_stop_price"],
                        "trailing_active": bool(row["trailing_active"]),
                    })

    return {"ok": True, "payload": {"positions": positions}}
