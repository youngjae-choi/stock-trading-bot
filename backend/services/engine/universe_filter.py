"""유니버스 필터 서비스 (S3 — 08:15 KST).

KIS 거래량/거래대금 순위를 병렬로 가져와 1차 유니버스를 구성하고
정량 점수로 정렬한 뒤 DB에 저장한다.

필터 기준 (Layer 1):
- 상한가/하한가 제외: 변동률 ±29% 초과 종목
- 가격 0원 종목 제외
- 거래량 0 종목 제외

점수 계산 (가중 합산):
- 거래대금 순위 점수: 50%
- 거래량 순위 점수: 30%
- 등락률 점수 (양수 선호): 20%

결과는 universe_filter_results 테이블에 저장된다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from ..db import get_connection
from ..kis.domestic.universe_service import get_price_rank, get_volume_rank
from .expert_knowledge import get_active_knowledge
from .learning_memory import get_active_memories
from .pipeline_audit import finish_pipeline_run, normalize_trigger_source, start_pipeline_run

logger = logging.getLogger("UniverseFilterService")

_MAX_UNIVERSE = 60   # KIS에서 가져올 최대 종목 수
_TOP_N_RESULT = 30   # DB에 저장할 상위 종목 수
_CHANGE_RATE_LIMIT = 29.0  # 상한가/하한가 제외 기준


# ---------------------------------------------------------------------------
# DB 초기화
# ---------------------------------------------------------------------------

def _ensure_table() -> None:
    """universe_filter_results 테이블이 없으면 생성한다."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS universe_filter_results (
                id          TEXT PRIMARY KEY,
                trade_date  TEXT NOT NULL,
                items       TEXT NOT NULL DEFAULT '[]',
                raw_count   INTEGER NOT NULL DEFAULT 0,
                filtered_count INTEGER NOT NULL DEFAULT 0,
                created_at  TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_universe_filter_trade_date ON universe_filter_results(trade_date)"
        )


# ---------------------------------------------------------------------------
# 내부 필터/점수 로직
# ---------------------------------------------------------------------------

def _merge_and_deduplicate(
    volume_items: list[dict],
    trade_items: list[dict],
) -> list[dict]:
    """거래량 순위와 거래대금 순위를 병합하고 중복을 제거한다."""
    merged: dict[str, dict] = {}

    for idx, item in enumerate(volume_items):
        sym = item.get("symbol", "")
        if not sym:
            continue
        merged[sym] = {
            "symbol": sym,
            "name": item.get("name", ""),
            "price": item.get("price", 0),
            "change_rate": item.get("change_rate", 0.0),
            "volume": item.get("volume", 0),
            "trade_amount": 0,
            "volume_rank": idx + 1,
            "trade_rank": 9999,
        }

    for idx, item in enumerate(trade_items):
        sym = item.get("symbol", "")
        if not sym:
            continue
        if sym in merged:
            merged[sym]["trade_amount"] = item.get("trade_amount", 0)
            merged[sym]["trade_rank"] = idx + 1
        else:
            merged[sym] = {
                "symbol": sym,
                "name": item.get("name", ""),
                "price": item.get("price", 0),
                "change_rate": item.get("change_rate", 0.0),
                "volume": 0,
                "trade_amount": item.get("trade_amount", 0),
                "volume_rank": 9999,
                "trade_rank": idx + 1,
            }

    return list(merged.values())


def _apply_filters(items: list[dict]) -> list[dict]:
    """상한가/하한가, 가격/거래량 0 종목을 제거한다."""
    result = []
    for item in items:
        change = abs(item.get("change_rate", 0.0))
        if change >= _CHANGE_RATE_LIMIT:
            continue
        if item.get("price", 0) <= 0:
            continue
        if item.get("volume", 0) <= 0 and item.get("trade_amount", 0) <= 0:
            continue
        result.append(item)
    return result


_TONE_WEIGHTS: dict[str, dict[str, float]] = {
    "positive": {"trade": 0.40, "volume": 0.40, "change": 0.20},
    "neutral":  {"trade": 0.50, "volume": 0.30, "change": 0.20},
    "negative": {"trade": 0.60, "volume": 0.30, "change": 0.10},
    "mixed":    {"trade": 0.50, "volume": 0.30, "change": 0.20},
}
_DEFAULT_WEIGHTS = _TONE_WEIGHTS["neutral"]


def _get_tone_weights(trade_date: str) -> tuple[dict[str, float], str]:
    """오늘 시장 톤을 DB에서 조회해 가중치를 반환한다.

    Returns:
        (weights_dict, tone_used)
        조회 실패 시 neutral 기본값과 "fallback" 반환.
    """
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT tone FROM market_tone_results WHERE trade_date = ? ORDER BY created_at DESC LIMIT 1",
                (trade_date,),
            ).fetchone()
        if row is None:
            logger.warning("WARN: UniverseFilter 시장 톤 미조회 — neutral 기본값 사용 trade_date=%s", trade_date)
            return _DEFAULT_WEIGHTS, "fallback"
        tone = str(row["tone"]).lower()
        weights = _TONE_WEIGHTS.get(tone, _DEFAULT_WEIGHTS)
        logger.info("INFO: UniverseFilter 시장 톤=%s weights=%s", tone, weights)
        return weights, tone
    except Exception as exc:
        logger.warning("WARN: UniverseFilter 시장 톤 조회 실패 — %s neutral 기본값 사용", exc)
        return _DEFAULT_WEIGHTS, "fallback"


def _apply_memory_adjustments(weights: dict[str, float], memories: list[dict]) -> dict[str, float]:
    """S3 learning memories 기반으로 유니버스 필터 점수 가중치를 미세 조정한다.

    Args:
        weights: 시장 톤으로 산출된 trade/volume/change 가중치.
        memories: S3_UNIVERSE_FILTER 범위의 활성 Learning Memory 목록.
    """
    adjusted = dict(weights)
    for mem in memories:
        rec = mem.get("recommendation", {})
        if rec.get("type") == "weight_adjust":
            field = rec.get("field", "")
            delta = float(rec.get("delta", 0.0))
            if field in adjusted:
                adjusted[field] = max(0.0, min(1.0, adjusted[field] + delta))

    total = sum(adjusted.values())
    if total > 0:
        adjusted = {key: value / total for key, value in adjusted.items()}
    return adjusted


def _score_and_rank(items: list[dict], total: int, weights: dict[str, float]) -> list[dict]:
    """정량 점수를 계산하고 내림차순으로 정렬한다.

    점수 = 거래대금 순위 점수 * trade_w + 거래량 순위 점수 * volume_w + 등락률 점수 * change_w
    순위 점수 = (total - rank + 1) / total  (1등이 가장 높음)
    등락률 점수 = (change_rate + 30) / 60  (양수 선호, -30~+30 범위 정규화)
    """
    if total == 0:
        total = 1

    trade_w = weights.get("trade", 0.50)
    volume_w = weights.get("volume", 0.30)
    change_w = weights.get("change", 0.20)

    scored = []
    for item in items:
        trade_score = (total - item.get("trade_rank", total) + 1) / total
        volume_score = (total - item.get("volume_rank", total) + 1) / total
        change_normalized = (item.get("change_rate", 0.0) + 30.0) / 60.0
        change_normalized = max(0.0, min(1.0, change_normalized))

        total_score = (
            trade_w * trade_score +
            volume_w * volume_score +
            change_w * change_normalized
        )
        scored.append({**item, "score": round(total_score, 4)})

    scored.sort(key=lambda x: x["score"], reverse=True)
    for idx, item in enumerate(scored, start=1):
        item["rank"] = idx

    return scored


# ---------------------------------------------------------------------------
# 공개 인터페이스
# ---------------------------------------------------------------------------

async def run_universe_filter(trigger_source: str = "api_manual") -> dict[str, Any]:
    """유니버스 필터를 실행하고 결과를 DB에 저장한 뒤 반환한다."""
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    safe_source = normalize_trigger_source(trigger_source)
    run_audit_id = start_pipeline_run(
        trade_date=today,
        step="S3",
        trigger_source=safe_source,
        display_source="manual-like-console" if safe_source == "console_manual" else safe_source,
    )
    logger.info("START: UniverseFilter.run trade_date=%s source=%s", today, safe_source)

    _ensure_table()
    memories = get_active_memories(scope="S3_UNIVERSE_FILTER")
    memory_refs = [m["memory_id"] for m in memories]
    knowledge_items = get_active_knowledge(scope="S3_UNIVERSE_FILTER")
    knowledge_refs = [k["id"] for k in knowledge_items]

    # KIS 병렬 호출
    try:
        volume_result, trade_result = await asyncio.gather(
            get_volume_rank(market_code="J", top_n=_MAX_UNIVERSE),
            get_price_rank(sort_by="trade_amount", market_code="J", top_n=_MAX_UNIVERSE),
        )
        volume_items = volume_result.get("items", [])
        trade_items = trade_result.get("items", [])
    except Exception as exc:
        finish_pipeline_run(
            run_id=run_audit_id,
            status="failed",
            message=str(exc),
            metadata={"trigger_source": safe_source},
        )
        logger.error("FAIL: UniverseFilter KIS 호출 실패 — %s", exc)
        raise

    # 시장 톤 기반 동적 가중치 결정
    weights, tone_used = _get_tone_weights(today)
    weights = _apply_memory_adjustments(weights, memories)

    raw_count = len(volume_items) + len(trade_items)
    merged = _merge_and_deduplicate(volume_items, trade_items)
    filtered = _apply_filters(merged)
    ranked = _score_and_rank(filtered, total=len(merged), weights=weights)
    top_n = ranked[:_TOP_N_RESULT]

    # DB 저장
    record_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO universe_filter_results
                (id, trade_date, items, raw_count, filtered_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                record_id,
                today,
                json.dumps(top_n, ensure_ascii=False),
                raw_count,
                len(filtered),
                now,
            ),
        )

    result = {
        "ok": True,
        "trade_date": today,
        "raw_count": raw_count,
        "filtered_count": len(filtered),
        "result_count": len(top_n),
        "tone_used": tone_used,
        "weights_used": weights,
        "memory_refs": memory_refs,
        "memory_count": len(memories),
        "knowledge_refs": knowledge_refs,
        "knowledge_count": len(knowledge_items),
        "items": top_n,
        "id": record_id,
    }
    logger.info(
        "SUCCESS: UniverseFilter trade_date=%s tone=%s raw=%d filtered=%d top_n=%d memories=%d knowledge=%d",
        today, tone_used, raw_count, len(filtered), len(top_n), len(memories), len(knowledge_items),
    )
    finish_pipeline_run(
        run_id=run_audit_id,
        status="success",
        result_ref_id=record_id,
        message=f"raw={raw_count} filtered={len(filtered)} top_n={len(top_n)}",
        metadata={"tone_used": tone_used, "trigger_source": safe_source},
    )
    return result


def get_today_universe(trade_date: str) -> dict[str, Any] | None:
    """DB에서 특정 날짜의 유니버스 필터 결과를 조회한다."""
    _ensure_table()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM universe_filter_results WHERE trade_date = ? ORDER BY created_at DESC LIMIT 1",
            (trade_date,),
        ).fetchone()
    if row is None:
        return None
    d = dict(row)
    if isinstance(d.get("items"), str):
        try:
            d["items"] = json.loads(d["items"])
        except Exception:
            d["items"] = []
    return d
