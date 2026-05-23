"""레짐별 성과 분석 API - 시장 상황, 설정값, 결과 상관관계."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Query

from ...services.db import get_connection

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])
logger = logging.getLogger("RegimeAnalyticsAPI")

REGIMES = ("risk_on", "neutral", "risk_off", "volatile")


def _get_date_range(days: int) -> tuple[str, str]:
    """조회 일수 기준 UTC 날짜 범위를 반환한다.

    Args:
        days: 오늘부터 과거로 포함할 조회 일수.
    """
    now = datetime.now(timezone.utc)
    end = now.strftime("%Y-%m-%d")
    start = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    return start, end


def _empty_regime_result(days: int = 0) -> dict[str, Any]:
    """성과 데이터가 없을 때 레짐별 기본 집계값을 만든다.

    Args:
        days: 해당 레짐 스냅샷 일수.
    """
    return {
        "days": days,
        "total_trades": 0,
        "win_count": 0,
        "loss_count": 0,
        "win_rate_pct": 0.0,
        "avg_pnl_krw": 0,
        "total_pnl_krw": 0,
        "best_day": None,
        "worst_day": None,
        "avg_stop_loss_rate": None,
        "avg_max_positions": None,
    }


def _average(values: list[float]) -> float | None:
    """숫자 목록 평균을 반환하고 빈 목록이면 None을 반환한다.

    Args:
        values: 평균 계산 대상 숫자 목록.
    """
    return sum(values) / len(values) if values else None


@router.get("/regime-performance")
async def get_regime_performance(days: int = Query(default=90, ge=7, le=365)) -> dict[str, Any]:
    """레짐별 집계 성과를 반환한다.

    Args:
        days: 조회 기간. 7일부터 365일까지 허용한다.
    """
    start, end = _get_date_range(days)
    logger.info("START: GET /api/v1/analytics/regime-performance days=%s", days)
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    s.regime,
                    s.risk_level,
                    s.stop_loss_rate,
                    s.take_profit_rate,
                    s.max_positions,
                    r.trade_date,
                    r.total_trades,
                    r.win_count,
                    r.loss_count,
                    r.total_pnl
                FROM daily_context_snapshot s
                LEFT JOIN daily_review_reports r ON s.trade_date = r.trade_date
                WHERE s.trade_date >= ? AND s.trade_date <= ?
                ORDER BY s.trade_date DESC
                """,
                (start, end),
            ).fetchall()
    except Exception as exc:
        logger.error("FAIL: GET /api/v1/analytics/regime-performance error=%s", exc)
        return {"ok": False, "error": str(exc)}

    regime_data: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        data = dict(row)
        regime = data.get("regime") if data.get("regime") in REGIMES else "neutral"
        regime_data[regime].append(data)

    result: dict[str, dict[str, Any]] = {regime: _empty_regime_result() for regime in REGIMES}
    for regime, entries in regime_data.items():
        valid = [entry for entry in entries if entry.get("total_trades") is not None]
        if not valid:
            result[regime] = _empty_regime_result(days=len(entries))
            continue

        total_trades = sum(entry.get("total_trades") or 0 for entry in valid)
        win_count = sum(entry.get("win_count") or 0 for entry in valid)
        loss_count = sum(entry.get("loss_count") or 0 for entry in valid)
        total_pnl = sum(entry.get("total_pnl") or 0 for entry in valid)
        win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0.0
        sorted_by_pnl = sorted(valid, key=lambda entry: entry.get("total_pnl") or 0)
        stop_vals = [float(entry["stop_loss_rate"]) for entry in entries if entry.get("stop_loss_rate") is not None]
        pos_vals = [float(entry["max_positions"]) for entry in entries if entry.get("max_positions") is not None]
        avg_stop = _average(stop_vals)
        avg_pos = _average(pos_vals)

        result[regime] = {
            "days": len(entries),
            "total_trades": total_trades,
            "win_count": win_count,
            "loss_count": loss_count,
            "win_rate_pct": round(win_rate, 1),
            "avg_pnl_krw": round(total_pnl / len(valid)) if valid else 0,
            "total_pnl_krw": round(total_pnl),
            "best_day": sorted_by_pnl[-1]["trade_date"] if sorted_by_pnl else None,
            "worst_day": sorted_by_pnl[0]["trade_date"] if sorted_by_pnl else None,
            "avg_stop_loss_rate": round(avg_stop, 4) if avg_stop is not None else None,
            "avg_max_positions": round(avg_pos, 1) if avg_pos is not None else None,
        }

    logger.info("SUCCESS: GET /api/v1/analytics/regime-performance rows=%d", len(rows))
    return {
        "ok": True,
        "days": days,
        "regimes": result,
        "date_range": {"start": start, "end": end},
        "data_days": len(rows),
    }


@router.get("/parameter-history")
async def get_parameter_history(days: int = Query(default=90, ge=7, le=365)) -> dict[str, Any]:
    """날짜별 레짐, 파라미터, 성과 히스토리를 반환한다.

    Args:
        days: 조회 기간. 7일부터 365일까지 허용한다.
    """
    start, end = _get_date_range(days)
    logger.info("START: GET /api/v1/analytics/parameter-history days=%s", days)
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    s.trade_date AS date,
                    s.regime,
                    s.risk_level,
                    s.stop_loss_rate,
                    s.take_profit_rate,
                    s.max_positions,
                    s.max_position_size_rate,
                    COALESCE(r.total_trades, 0) AS total_trades,
                    COALESCE(r.win_count, 0) AS win_count,
                    COALESCE(r.loss_count, 0) AS loss_count,
                    COALESCE(r.total_pnl, 0) AS total_pnl
                FROM daily_context_snapshot s
                LEFT JOIN daily_review_reports r ON s.trade_date = r.trade_date
                WHERE s.trade_date >= ? AND s.trade_date <= ?
                ORDER BY s.trade_date ASC
                """,
                (start, end),
            ).fetchall()
    except Exception as exc:
        logger.error("FAIL: GET /api/v1/analytics/parameter-history error=%s", exc)
        return {"ok": False, "error": str(exc)}

    result: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        trades = data.get("total_trades") or 0
        wins = data.get("win_count") or 0
        data["win_rate_pct"] = round(wins / trades * 100, 1) if trades > 0 else None
        result.append(data)

    logger.info("SUCCESS: GET /api/v1/analytics/parameter-history rows=%d", len(result))
    return {"ok": True, "rows": result}


@router.get("/regime-recommendation")
async def get_regime_recommendation(days: int = Query(default=90, ge=14, le=365)) -> dict[str, Any]:
    """레짐별 최적 설정값 추천을 반환한다.

    Args:
        days: 추천 계산에 사용할 조회 기간. 14일부터 365일까지 허용한다.
    """
    logger.info("START: GET /api/v1/analytics/regime-recommendation days=%s", days)
    perf_response = await get_regime_performance(days=days)
    if not perf_response.get("ok"):
        logger.error("FAIL: GET /api/v1/analytics/regime-recommendation dependency=regime-performance")
        return {"ok": False, "error": "regime-performance query failed"}

    min_days = 10
    med_days = 4
    defaults = {
        "risk_on": {"max_positions": 10, "stop_loss_rate": -0.020, "take_profit_rate": 0.050, "max_position_size_rate": 0.10},
        "neutral": {"max_positions": 7, "stop_loss_rate": -0.020, "take_profit_rate": 0.040, "max_position_size_rate": 0.10},
        "risk_off": {"max_positions": 5, "stop_loss_rate": -0.015, "take_profit_rate": 0.030, "max_position_size_rate": 0.08},
        "volatile": {"max_positions": 3, "stop_loss_rate": -0.015, "take_profit_rate": 0.040, "max_position_size_rate": 0.07},
    }

    recommendations: dict[str, dict[str, Any]] = {}
    regimes_data = perf_response.get("regimes", {})
    for regime in REGIMES:
        data = regimes_data.get(regime, {})
        data_days = data.get("days", 0)
        win_rate = data.get("win_rate_pct", 0)
        avg_stop = data.get("avg_stop_loss_rate")
        avg_pos = data.get("avg_max_positions")
        total_trades = data.get("total_trades", 0)

        if data_days >= min_days and total_trades > 0:
            confidence = "high"
            settings = {
                "max_positions": round(avg_pos) if avg_pos else defaults[regime]["max_positions"],
                "stop_loss_rate": round(avg_stop, 3) if avg_stop else defaults[regime]["stop_loss_rate"],
                "take_profit_rate": defaults[regime]["take_profit_rate"],
                "max_position_size_rate": defaults[regime]["max_position_size_rate"],
            }
            rationale = (
                f"{data_days}일 데이터 기준 승률 {win_rate}%, 평균 손절 {avg_stop:.3f}"
                if avg_stop is not None
                else f"{data_days}일 데이터 기준 승률 {win_rate}%"
            )
        elif data_days >= med_days and total_trades > 0:
            confidence = "medium"
            settings = defaults[regime].copy()
            if avg_pos:
                settings["max_positions"] = round(avg_pos)
            rationale = f"{data_days}일 데이터 (부족) - 기본값 + 부분 조정"
        elif data_days > 0:
            confidence = "low"
            settings = defaults[regime].copy()
            rationale = f"{data_days}일 데이터 (매우 부족) - 기본값 사용"
        else:
            confidence = "no_data"
            settings = defaults[regime].copy()
            rationale = "데이터 없음 - 기본값 사용"

        recommendations[regime] = {
            "confidence": confidence,
            "data_days": data_days,
            "total_trades": total_trades,
            "win_rate_pct": win_rate,
            "settings": settings,
            "rationale": rationale,
        }

    logger.info("SUCCESS: GET /api/v1/analytics/regime-recommendation")
    return {
        "ok": True,
        "recommendations": recommendations,
        "min_data_days_for_confidence": min_days,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
