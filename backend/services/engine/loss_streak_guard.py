"""Loss Streak Guard — 같은 종목 3회+ 손실 시 자동 차단.

S11 학습 루프의 일부로 job_review_audit() 완료 후 호출된다.
false_positive_cases 테이블의 오늘 손실 데이터를 집계하여
3회 이상 손실 종목을 expert_knowledge(approved)에 자동 등록한다.
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from ..db import get_connection

logger = logging.getLogger("LossStreakGuard")

_LOSS_THRESHOLD = 3
_BLOCK_SCOPE = "S4_HYBRID_SCREENING"
_BLOCK_CATEGORY = "risk"
_BLOCK_DAYS = 3  # 차단 유효 기간 (영업일 기준 아닌 달력일)


def _today_kst() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


def _expires_at(days: int) -> str:
    from datetime import timedelta
    base = datetime.now(ZoneInfo("Asia/Seoul"))
    return (base + timedelta(days=days)).strftime("%Y-%m-%d")


def _get_loss_symbols(trade_date: str) -> list[tuple[str, int]]:
    """오늘 3회 이상 손실이 기록된 (symbol, loss_count) 목록을 반환한다."""
    with get_connection() as conn:
        # false_positive_cases: trade_date 기준 종목별 손실 건수 집계
        rows = conn.execute(
            """
            SELECT symbol, COUNT(*) AS loss_count
            FROM false_positive_cases
            WHERE trade_date = ?
              AND pnl_pct IS NOT NULL
              AND pnl_pct < 0
            GROUP BY symbol
            HAVING COUNT(*) >= ?
            """,
            (trade_date, _LOSS_THRESHOLD),
        ).fetchall()
    return [(str(row[0]), int(row[1])) for row in rows]


def _is_already_blocked(symbol: str, trade_date: str) -> bool:
    """오늘 이미 같은 종목의 스트릭 차단이 등록돼 있으면 True 반환."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM strategy_knowledge_items
            WHERE scope = ?
              AND category = ?
              AND title LIKE ?
              AND DATE(created_at) = ?
              AND status = 'approved'
            LIMIT 1
            """,
            (_BLOCK_SCOPE, _BLOCK_CATEGORY, f"%손실차단:{symbol}%", trade_date),
        ).fetchone()
    return row is not None


def auto_block_loss_streak_symbols(trade_date: str | None = None) -> dict:
    """3회+ 손실 종목을 expert_knowledge approved 항목으로 자동 등록한다.

    Args:
        trade_date: YYYY-MM-DD 처리 날짜. None이면 오늘 KST.
    """
    today = trade_date or _today_kst()
    logger.info("START: [LossStreakGuard] auto_block trade_date=%s threshold=%d", today, _LOSS_THRESHOLD)

    loss_symbols = _get_loss_symbols(today)
    if not loss_symbols:
        logger.info("INFO: [LossStreakGuard] 차단 대상 없음 trade_date=%s", today)
        return {"blocked": [], "skipped": []}

    blocked: list[str] = []
    skipped: list[str] = []

    for symbol, count in loss_symbols:
        if _is_already_blocked(symbol, today):
            skipped.append(symbol)
            logger.info("INFO: [LossStreakGuard] 이미 차단됨 symbol=%s", symbol)
            continue

        try:
            from .expert_knowledge import create_knowledge_item
            create_knowledge_item(
                title=f"손실차단:{symbol} ({count}회 손실 {today})",
                content=(
                    f"{symbol} 종목은 {today} 기준 {count}회 연속 손실이 발생했습니다. "
                    f"향후 {_BLOCK_DAYS}일간 신규 진입 대상에서 제외하십시오."
                ),
                scope=_BLOCK_SCOPE,
                category=_BLOCK_CATEGORY,
                priority=2,
                auto_inject=True,
                expires_at=_expires_at(_BLOCK_DAYS),
                status="approved",
            )
            blocked.append(symbol)
            logger.info(
                "SUCCESS: [LossStreakGuard] 자동 차단 등록 symbol=%s count=%d expires=%s",
                symbol,
                count,
                _expires_at(_BLOCK_DAYS),
            )
        except Exception as exc:
            logger.error("FAIL: [LossStreakGuard] 차단 등록 실패 symbol=%s reason=%s", symbol, exc)
            skipped.append(symbol)

    logger.info(
        "SUCCESS: [LossStreakGuard] 완료 blocked=%s skipped=%s",
        blocked,
        skipped,
    )
    return {"blocked": blocked, "skipped": skipped}
