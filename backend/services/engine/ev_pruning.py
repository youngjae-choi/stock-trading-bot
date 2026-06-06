"""탐색엔진 Phase 3 결선층 — EV 가지치기를 condition_groups.weight 에 반영하고
기존 EOD 학습루프(learning_memories)에 negative-knowledge 요약을 1행 기록한다.

순수 집계·추천 로직은 ev_analysis.py(단위테스트). 본 모듈은 DB 부수효과만 담당한다.
새 파이프라인이 아니라 기존 학습루프(run_review_audit → learning_memory)에 디테일을 얹는다.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection
from . import ev_analysis
from .trade_tagging import load_tags

logger = logging.getLogger("EVPruning")

_WEIGHT_FLOOR = 0.1          # 하드제로 금지 — 운 좋은 전략을 죽이지 않는 최소 가중
_DOWNWEIGHT_FACTOR = 0.5     # downweight 시 가중 절반


def _now_kst_iso() -> str:
    """현재 Asia/Seoul 시각 ISO 문자열."""
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()


def apply_auto_weight(recommendations: list[dict[str, Any]]) -> dict[str, Any]:
    """가지치기 추천을 condition_groups.weight 에 반영한다(그룹명 = name 매칭).

    downweight: weight *= 0.5 (floor 0.1). disable: weight = floor + enabled=0
    (대표본 지속 음수일 때만 — 완전 0 으로 죽이지 않고 floor 까지만 내린다).
    그룹이 아닌 target(selection_source/regime)은 skipped 로 반환한다.

    Args:
        recommendations: recommend_pruning() 출력 [{target, action, ...}].
    """
    adjusted: list[str] = []
    skipped: list[str] = []
    with get_connection() as conn:
        for rec in recommendations or []:
            target = str(rec.get("target") or "")
            action = str(rec.get("action") or "")
            row = conn.execute(
                "SELECT id, weight FROM condition_groups WHERE name = ?", (target,)
            ).fetchone()
            if row is None:
                skipped.append(target)  # 그룹명이 아님(선정소스/레짐) — weight 대상 아님
                continue
            cur_weight = float(row["weight"] or 1.0)
            if action == "disable":
                new_weight = _WEIGHT_FLOOR
                conn.execute(
                    "UPDATE condition_groups SET weight = ?, enabled = 0 WHERE id = ?",
                    (new_weight, row["id"]),
                )
            else:  # downweight (기본)
                new_weight = max(cur_weight * _DOWNWEIGHT_FACTOR, _WEIGHT_FLOOR)
                conn.execute(
                    "UPDATE condition_groups SET weight = ? WHERE id = ?",
                    (new_weight, row["id"]),
                )
            adjusted.append(target)
            logger.info("INFO: [EV] weight 조정 group=%s action=%s %.3f→%.3f",
                        target, action, cur_weight, new_weight)
    return {"adjusted": len(adjusted), "adjusted_groups": adjusted, "skipped": skipped}
