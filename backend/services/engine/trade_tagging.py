"""탐색엔진 통짜 태깅 데이터 계층 (trade_entry_tags).

매수 체결 시 1행 기록(선정사유+발화그룹+조건상태+시장맥락), 청산 시 결과(outcome) 채움.
이 통짜 기록으로 Phase 3가 임의 조건/그룹/맥락별 승률·EV를 오프라인 집계해 가지치기한다.

market_context/outcome 은 호출부가 dict로 전달한다(테스트 가능성 유지):
- market_context: regime/market_tone 은 daily_plan / market_tone_results 에서 온다.
- outcome: realized_pnl/win/hold_sec/exit_reason 은 청산 후 trade_pairs(매도완료) 에서 온다.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection

logger = logging.getLogger("TradeTagging")


def _now_kst_iso() -> str:
    """현재 Asia/Seoul 시각을 ISO 문자열로 반환한다."""
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()


def _ensure_table() -> None:
    """trade_entry_tags 테이블과 인덱스를 없으면 생성한다."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trade_entry_tags (
                id                    TEXT PRIMARY KEY,
                order_id              TEXT NOT NULL DEFAULT '',
                symbol                TEXT NOT NULL DEFAULT '',
                trade_date            TEXT NOT NULL DEFAULT '',
                selection_reason_json TEXT NOT NULL DEFAULT '{}',
                fired_groups_json     TEXT NOT NULL DEFAULT '[]',
                condition_states_json TEXT NOT NULL DEFAULT '{}',
                market_context_json   TEXT NOT NULL DEFAULT '{}',
                outcome_json          TEXT NOT NULL DEFAULT '{}',
                created_at            TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_trade_entry_tags_trade_date ON trade_entry_tags(trade_date)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_trade_entry_tags_order_id ON trade_entry_tags(order_id)"
        )


def _dumps(value: Any) -> str:
    """dict/list 를 JSON 문자열로 직렬화한다(한글 보존)."""
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def record_entry_tag(
    *,
    order_id: str,
    symbol: str,
    trade_date: str,
    selection_reason: dict,
    fired_groups: list,
    condition_states: dict,
    market_context: dict,
) -> str:
    """매수 체결 시 태그 1행을 기록하고 태그 id 를 반환한다.

    Args:
        order_id: trading_orders.id (매수 주문 로컬 id).
        symbol: 종목 코드.
        trade_date: YYYY-MM-DD 거래일.
        selection_reason: {"sources": [...], "scores": {...}, "llm_note": "..."}.
        fired_groups: OR 중 발화한 그룹명 리스트.
        condition_states: 진입 순간 모든 원자조건 값 dict.
        market_context: {"regime", "market_tone", "time_bucket", "vix"} dict.
    """
    _ensure_table()
    tag_id = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO trade_entry_tags
                (id, order_id, symbol, trade_date, selection_reason_json,
                 fired_groups_json, condition_states_json, market_context_json,
                 outcome_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tag_id,
                str(order_id or ""),
                str(symbol or ""),
                str(trade_date or ""),
                _dumps(selection_reason),
                _dumps(fired_groups if fired_groups is not None else []),
                _dumps(condition_states),
                _dumps(market_context),
                "{}",
                _now_kst_iso(),
            ),
        )
    logger.info("SUCCESS: 태그 기록 tag_id=%s order_id=%s symbol=%s", tag_id, order_id, symbol)
    return tag_id


def load_tags(trade_date: str) -> list[dict]:
    """해당 거래일의 모든 태그를 JSON 필드를 파싱해 반환한다.

    Args:
        trade_date: YYYY-MM-DD 거래일.
    """
    _ensure_table()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM trade_entry_tags WHERE trade_date = ? ORDER BY created_at ASC",
            (trade_date,),
        ).fetchall()
    return [_parse_row(dict(row)) for row in rows]


def _parse_row(row: dict) -> dict:
    """DB row 의 *_json 컬럼을 파이썬 객체로 풀어 사용 친화적 dict 로 변환한다."""
    def _loads(text: Any, fallback: Any) -> Any:
        if not text:
            return fallback
        try:
            return json.loads(text)
        except (TypeError, ValueError):
            return fallback

    return {
        "id": row.get("id"),
        "order_id": row.get("order_id"),
        "symbol": row.get("symbol"),
        "trade_date": row.get("trade_date"),
        "selection_reason": _loads(row.get("selection_reason_json"), {}),
        "fired_groups": _loads(row.get("fired_groups_json"), []),
        "condition_states": _loads(row.get("condition_states_json"), {}),
        "market_context": _loads(row.get("market_context_json"), {}),
        "outcome": _loads(row.get("outcome_json"), {}),
        "created_at": row.get("created_at"),
    }


def _maybe_float(value: Any) -> float | None:
    """숫자로 변환 가능하면 float, 아니면 None 을 반환한다."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_selection_reason(candidate: dict) -> dict:
    """S4 후보 dict 에서 record_entry_tag 용 selection_reason 을 추출한다.

    선정사유 = 어떤 소스가 종목을 surfacing 했나(sources) + 점수 근거(scores) + LLM 메모(llm_note).
    빠진 필드는 안전하게 누락한다. (hybrid_screening candidates 항목 기준:
    score=유니버스 블렌드 점수, suitability_score=LLM 적합도, trade_rank>100 은 미수신 sentinel)

    Args:
        candidate: S3/S4 후보 종목 dict.
    """
    candidate = candidate or {}

    # 단타 모멘텀 선정: 거래량순위 / 등락률순위 / 거래량급증 (거래대금 소스 제거)
    sources: list[str] = []
    # 선정 출처(llm | quant_topup)를 맨 앞에 — EV(selection_source) 비교의 핵심 버킷.
    # quant_topup = LLM이 보류/탈락시켰으나 정량 블렌드로 재포함된 종목 → 추후 성과로 강화/제거 판단.
    selection_source = str(candidate.get("selection_source") or "").strip()
    if selection_source:
        sources.append(selection_source)
    volume_rank = candidate.get("volume_rank")
    if isinstance(volume_rank, (int, float)) and 0 < volume_rank <= 100:
        sources.append(f"거래량순위#{int(volume_rank)}")
    change_rate_rank = candidate.get("change_rate_rank")
    if isinstance(change_rate_rank, (int, float)) and 0 < change_rate_rank <= 100:
        sources.append(f"등락률순위#{int(change_rate_rank)}")
    # 전일대비 거래량증가율(%)이 유의미하면(>=100% = 전일 대비 이상) 거래량급증 태그
    volume_surge = candidate.get("volume_surge")
    if isinstance(volume_surge, (int, float)) and volume_surge >= 100.0:
        sources.append("거래량급증")

    scores: dict[str, float] = {}
    universe_score = _maybe_float(candidate.get("score"))
    if universe_score is not None:
        scores["universe_score"] = universe_score
    suitability = _maybe_float(candidate.get("suitability_score"))
    if suitability is not None:
        scores["llm_suitability"] = suitability
    change_rate = _maybe_float(candidate.get("change_rate"))
    if change_rate is not None:
        scores["change_rate"] = change_rate
    tsi = _maybe_float(candidate.get("tsi"))
    if tsi is not None:
        scores["일봉TSI"] = tsi

    llm_note = str(candidate.get("llm_note") or candidate.get("reason") or "").strip()

    return {"sources": sources, "scores": scores, "llm_note": llm_note}


def set_outcome(*, order_id: str, outcome: dict) -> int:
    """청산 후 order_id 로 태그의 outcome_json 을 갱신하고 갱신된 행 수를 반환한다.

    Args:
        order_id: 매수 주문의 trading_orders.id.
        outcome: {"realized_pnl", "win", "hold_sec", "exit_reason"} dict.
    """
    _ensure_table()
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE trade_entry_tags SET outcome_json = ? WHERE order_id = ?",
            (_dumps(outcome), str(order_id or "")),
        )
        updated = cursor.rowcount
    if updated == 0:
        logger.warning("WARN: set_outcome 매칭 태그 없음 order_id=%s", order_id)
    else:
        logger.info("SUCCESS: outcome 갱신 order_id=%s rows=%d", order_id, updated)
    return updated


def _delete_for_test(trade_date: str) -> None:
    """테스트 정리용: 해당 거래일 태그를 모두 삭제한다."""
    _ensure_table()
    with get_connection() as conn:
        conn.execute("DELETE FROM trade_entry_tags WHERE trade_date = ?", (trade_date,))
