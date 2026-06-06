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


def _delete_for_test(trade_date: str) -> None:
    """테스트 정리용: 해당 거래일 태그를 모두 삭제한다."""
    _ensure_table()
    with get_connection() as conn:
        conn.execute("DELETE FROM trade_entry_tags WHERE trade_date = ?", (trade_date,))
