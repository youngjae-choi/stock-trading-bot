"""손실 분석 오케스트레이션: 수집 → 전역 게이트 → 전략 제안(미리보기). 반영은 EOD에서."""
from __future__ import annotations

from typing import Any

from ..db import get_connection
from ..settings_store import upsert_setting

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
