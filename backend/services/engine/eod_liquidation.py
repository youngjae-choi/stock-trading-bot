"""S9 end-of-day liquidation service."""

from __future__ import annotations

import logging
from typing import Any

from .order_executor import order_executor
from .position_manager import position_manager

logger = logging.getLogger("EODLiquidation")


async def run_eod_liquidation() -> dict[str, Any]:
    """15:20 KST: 보유 전 포지션을 시장가로 청산한다."""
    positions = position_manager.get_positions()
    logger.info("START: [S9] EOD liquidation positions=%d", len(positions))
    results = []
    for pos in positions:
        result = await order_executor.execute_sell(
            symbol=str(pos.get("symbol") or ""),
            qty=int(pos.get("qty") or 0),
            price=0,
            reason="eod",
        )
        results.append(result)
    logger.info("SUCCESS: [S9] EOD liquidation finished liquidated=%d", len(results))
    return {"liquidated": len(results), "results": results}
