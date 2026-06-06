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


_DIMENSIONS = ("fired_group", "selection_source", "regime")


def _load_multiday_tags(trade_date: str, lookback_days: int) -> list[dict[str, Any]]:
    """trade_date 기준 과거 lookback_days(포함) 거래일의 태그를 모두 모은다.

    Args:
        trade_date: 기준 거래일 YYYY-MM-DD.
        lookback_days: 거슬러 올라갈 일수(캘린더 기준, 단순 합집합).
    """
    base = datetime.fromisoformat(f"{trade_date}T00:00:00")
    tags: list[dict[str, Any]] = []
    for offset in range(lookback_days + 1):
        d = (base - timedelta(days=offset)).date().isoformat()
        tags.extend(load_tags(d))
    return tags


def _write_ev_memory(
    trade_date: str,
    ev_results: dict[str, dict[str, dict[str, float]]],
    recommendations: list[dict[str, Any]],
    sample_size: int,
) -> None:
    """negative-knowledge("고르지/사지 말아야 할") 요약을 learning_memories 에 1행 기록한다.

    기존 학습루프와 동일한 테이블·컬럼 사용(category="ev_pruning"). 추천이 없으면
    "현재 가지칠 대상 없음" 요약을 남겨 관측 가능성을 유지한다.

    Args:
        trade_date: 기준 거래일.
        ev_results: {dimension: compute_ev_by_dimension 결과}.
        recommendations: recommend_pruning 출력(전 차원 병합).
        sample_size: 집계에 쓰인 정산 태그 수.
    """
    now = _now_kst_iso()
    expires_at = (datetime.fromisoformat(f"{trade_date}T00:00:00") + timedelta(days=7)).date().isoformat()
    if recommendations:
        worst = recommendations[0]
        summary = (
            f"[{trade_date}] EV 가지치기 — 사지/고르지 말아야 할 {len(recommendations)}건. "
            f"최악: {worst['target']} ({worst['reason']})."
        )
    else:
        summary = f"[{trade_date}] EV 가지치기 — 표본 {sample_size}건, 현재 가지칠 음수EV 대상 없음."

    memory_id = str(uuid.uuid4())
    evidence = {"sample_size": sample_size, "ev_results": ev_results}
    recommendation = {
        "action": "prune_negative_ev_targets",
        "pruning": recommendations,
        "guidance": "EV 음수 그룹/선정소스는 다음날 매수에서 가중↓/회피한다(negative knowledge).",
        "rag_usage": "리뷰·다음날 선정/매수 컨텍스트 — '사지/고르지 말아야 할' 참고 메모리",
    }
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM learning_memories WHERE trade_date = ? AND category = 'ev_pruning'",
            (trade_date,),
        )
        conn.execute(
            """
            INSERT INTO learning_memories
                (memory_id, trade_date, scope, category, summary, evidence,
                 recommendation, auto_apply_allowed, requires_approval, status,
                 expires_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory_id, trade_date, "S6_BUY_ENGINE", "ev_pruning", summary,
                json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
                json.dumps(recommendation, ensure_ascii=False, separators=(",", ":")),
                0, 0, "active", expires_at, now,
            ),
        )


def run_ev_pruning(
    trade_date: str,
    lookback_days: int = 10,
    min_sample: int = 30,
    apply: bool = False,
) -> dict[str, Any]:
    """EOD 결선: 멀티데이 태그 로드→3차원 EV 집계→추천→(apply 시)자동가중→메모리 기록.

    기존 EOD 학습루프에 얹는 스텝이다. 새 파이프라인이 아니다.

    Args:
        trade_date: 기준 거래일 YYYY-MM-DD.
        lookback_days: 집계 lookback 일수(기본 10).
        min_sample: 가지치기 최소 표본(기본 30).
        apply: True 면 condition_groups.weight 자동 반영, False 면 추천·메모리만.
    """
    logger.info("START: [EV] run_ev_pruning trade_date=%s lookback=%d apply=%s",
                trade_date, lookback_days, apply)
    tags = _load_multiday_tags(trade_date, lookback_days)
    settled = [t for t in tags if (t.get("outcome") or {}).get("realized_pnl") is not None]
    sample_size = len(settled)

    ev_results: dict[str, dict[str, dict[str, float]]] = {}
    recommendations: list[dict[str, Any]] = []
    for dim in _DIMENSIONS:
        dim_ev = ev_analysis.compute_ev_by_dimension(tags, dim)
        ev_results[dim] = dim_ev
        recommendations.extend(ev_analysis.recommend_pruning(dim_ev, min_sample=min_sample))
    recommendations.sort(key=lambda r: r["ev"])  # 전 차원 병합 후 negative-first 재정렬

    applied = {"adjusted": 0, "adjusted_groups": [], "skipped": []}
    if apply:
        applied = apply_auto_weight(recommendations)

    _write_ev_memory(trade_date, ev_results, recommendations, sample_size)

    logger.info("SUCCESS: [EV] run_ev_pruning trade_date=%s sample=%d recs=%d adjusted=%d",
                trade_date, sample_size, len(recommendations), applied["adjusted"])
    return {
        "ok": True,
        "trade_date": trade_date,
        "sample_size": sample_size,
        "ev_results": ev_results,
        "recommendations": recommendations,
        "applied": applied,
    }
