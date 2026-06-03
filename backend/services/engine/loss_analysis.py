"""손실 분석 오케스트레이션: 수집 → 전역 게이트 → 전략 제안(미리보기). 반영은 EOD에서."""
from __future__ import annotations

from typing import Any

from ..db import get_connection
from ..settings_store import upsert_setting
from . import loss_strategy

_GLOBAL_MIN_SAMPLE = 3


def collect_unreviewed_losses(start: str, end: str) -> list[dict[str, Any]]:
    """범위 내 미분석(reviewed_at IS NULL) 손실 case 를 반환한다."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM false_positive_cases
               WHERE trade_date >= ? AND trade_date <= ? AND reviewed_at IS NULL
               ORDER BY trade_date DESC""",
            (start, end),
        ).fetchall()
    return [dict(r) for r in rows]


def is_sample_insufficient(cases: list[dict[str, Any]]) -> bool:
    """전역 표본 게이트 — 총 손실 < 3 이면 분석 거부."""
    return len(cases) < _GLOBAL_MIN_SAMPLE


def _mark_reviewed(case_ids: list[str]) -> None:
    """분석 끝난 case 를 reviewed 처리 → 목록에서 숨김."""
    if not case_ids:
        return
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
    placeholders = ",".join("?" * len(case_ids))
    with get_connection() as conn:
        conn.execute(
            f"UPDATE false_positive_cases SET reviewed_at = ? WHERE id IN ({placeholders})",
            (now, *case_ids),
        )


def apply_strategies(applied: list[dict[str, Any]], cases: list[dict[str, Any]]) -> None:
    """자동반영 전략을 settings에 upsert(가드레일 통과값) + 분석 case reviewed 처리."""
    for s in applied:
        upsert_setting(
            s["setting_key"], s["new_value"], "float",
            f"손실분석 자동반영: {s.get('reason','')}", actor="loss_analysis",
        )
    _mark_reviewed([str(c["id"]) for c in cases if c.get("id")])


# "보수적(손실 방어적)" 방향: 값이 클수록 보수적인 키 / 작을수록 보수적인 키
_HIGHER_IS_CONSERVATIVE = {"engine.min_price_change_pct", "engine.min_volume_ratio"}
_LOWER_IS_CONSERVATIVE = {"engine.max_price_change_pct", "risk.max_position_rate_per_stock",
                          "risk.max_positions", "risk.daily_loss_limit_percent"}


def _merge_proposals(false_p: list[dict[str, Any]], missed_p: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """같은 설정 키 충돌 시 더 보수적인 값을 채택해 병합한다."""
    best: dict[str, dict[str, Any]] = {}
    for p in [*false_p, *missed_p]:
        key = p["setting_key"]
        if key not in best:
            best[key] = p
            continue
        cur = best[key]["new_value"]
        new = p["new_value"]
        if key in _HIGHER_IS_CONSERVATIVE:
            best[key] = p if new > cur else best[key]
        elif key in _LOWER_IS_CONSERVATIVE:
            best[key] = p if new < cur else best[key]
    return list(best.values())


def consolidate_and_apply(trade_date: str) -> dict[str, Any]:
    """EOD: 당일 기준 미분석 손실(False) + Missed 제안을 병합해 1회 자동반영한다.

    Missed 제안 도출은 v1에서는 빈 리스트(후속). False 제안만으로도 닫힘.
    """
    from datetime import datetime, timedelta
    start = (datetime.fromisoformat(trade_date) - timedelta(days=30)).strftime("%Y-%m-%d")
    cases = collect_unreviewed_losses(start, trade_date)
    false_proposed, _ = loss_strategy.derive_strategies(cases)
    missed_proposed: list[dict[str, Any]] = []  # v1: 후속 연결 지점
    merged = _merge_proposals(false_proposed, missed_proposed)
    apply_strategies(merged, cases)
    return {"applied": merged, "case_count": len(cases)}


def analyze(start: str, end: str) -> dict[str, Any]:
    """미리보기: 수집 → 전역 게이트 → 전략 제안 도출. 반영/숨김은 하지 않는다(EOD에서 수행)."""
    cases = collect_unreviewed_losses(start, end)
    if is_sample_insufficient(cases):
        return {"refused": True, "reason": "손실 표본 부족", "have": len(cases),
                "needed": _GLOBAL_MIN_SAMPLE, "proposed": [], "observing": [],
                "analyzed_symbols": []}
    proposed, observing = loss_strategy.derive_strategies(cases)
    return {"refused": False, "proposed": proposed, "observing": observing,
            "analyzed_symbols": [c.get("symbol") for c in cases]}
