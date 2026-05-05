"""S9 end-of-day liquidation service."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection
from .order_executor import order_executor
from .position_manager import position_manager

logger = logging.getLogger("EODLiquidation")


def _today_kst() -> str:
    """Return today's Asia/Seoul date as YYYY-MM-DD."""
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


def _get_open_positions_from_db(trade_date: str) -> list[dict[str, Any]]:
    """trading_orders에서 오늘 매수 후 아직 매도 안 된 종목을 조회한다.

    Args:
        trade_date: YYYY-MM-DD 형식의 거래일.
    """
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT symbol, SUM(qty) AS qty, AVG(price) AS avg_price
                FROM trading_orders
                WHERE trade_date = ?
                  AND side = 'buy'
                  AND status IN ('submitted', 'filled')
                  AND symbol NOT IN (
                      SELECT DISTINCT symbol
                      FROM trading_orders
                      WHERE trade_date = ?
                        AND side = 'sell'
                        AND status NOT IN ('failed', 'cancelled')
                  )
                GROUP BY symbol
                HAVING qty > 0
                """,
                (trade_date, trade_date),
            ).fetchall()
        return [dict(row) for row in rows]
    except Exception as exc:
        logger.warning("WARN: [S9] DB 포지션 조회 실패 error=%s", exc)
        return []


async def run_eod_liquidation() -> dict[str, Any]:
    """15:20 KST: 보유 전 포지션을 시장가로 청산한다.

    인메모리 포지션을 우선 사용하고, 서버 재시작으로 비어 있으면 DB에서 오늘 미청산 포지션을 조회한다.
    """
    today = _today_kst()
    positions = position_manager.get_positions()

    if not positions:
        logger.info("INFO: [S9] 인메모리 포지션 없음, DB 직접 조회 시도 trade_date=%s", today)
        db_positions = _get_open_positions_from_db(today)
        positions = [
            {"symbol": str(position.get("symbol") or ""), "qty": int(position.get("qty") or 0)}
            for position in db_positions
            if int(position.get("qty") or 0) > 0
        ]
        logger.info("INFO: [S9] DB 조회 포지션 count=%d", len(positions))

    logger.info("START: [S9] EOD liquidation positions=%d trade_date=%s", len(positions), today)
    if not positions:
        logger.info("INFO: [S9] 청산할 포지션 없음")
        return {"liquidated": 0, "results": []}

    results = []
    for pos in positions:
        symbol = str(pos.get("symbol") or "")
        qty = int(pos.get("qty") or 0)
        if not symbol or qty <= 0:
            logger.warning("WARN: [S9] invalid liquidation position symbol=%s qty=%s", symbol, qty)
            continue
        result = await order_executor.execute_sell(
            symbol=symbol,
            qty=qty,
            price=0,
            reason="eod",
        )
        results.append(result)
    logger.info("SUCCESS: [S9] EOD liquidation finished liquidated=%d", len(results))
    return {"liquidated": len(results), "results": results}
