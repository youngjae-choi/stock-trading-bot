"""S9 end-of-day liquidation service."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .order_executor import order_executor
from .position_integrity import (
    create_integrity_alert_once,
    detect_legacy_residual_positions,
    find_active_sell_order,
    json_compact,
    load_db_open_positions,
)
from .position_manager import position_manager

logger = logging.getLogger("EODLiquidation")


def _today_kst() -> str:
    """Return today's Asia/Seoul date as YYYY-MM-DD."""
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


def _get_open_positions_from_db(trade_date: str) -> list[dict[str, Any]]:
    """trading_orders에서 오늘 매수 후 아직 매도 안 된 순포지션을 조회한다.

    Args:
        trade_date: YYYY-MM-DD 형식의 거래일.
    """
    try:
        positions, skipped = load_db_open_positions(trade_date)
        for item in skipped:
            logger.warning(
                "WARN: [S9] DB net position skipped symbol=%s buy_qty=%s sell_qty=%s net_qty=%s reason=%s",
                item.get("symbol"),
                item.get("buy_qty"),
                item.get("sell_qty"),
                item.get("net_qty"),
                item.get("skipped_reason"),
            )
        return positions
    except Exception as exc:
        logger.warning("WARN: [S9] DB 포지션 조회 실패 error=%s", exc)
        return []


def _empty_summary() -> dict[str, int]:
    """Return the S9 result counter shape used by API and scheduler logs."""
    return {"submitted": 0, "uncertain": 0, "skipped_duplicate": 0, "failed": 0}


def _record_legacy_residual_alert(trade_date: str) -> list[dict[str, Any]]:
    """Detect prior-day residual strategy positions and write a reviewable alert.

    Args:
        trade_date: YYYY-MM-DD trade date currently being liquidated.
    """
    residuals = detect_legacy_residual_positions(trade_date)
    if residuals:
        logger.warning(
            "WARN: [S9] legacy residual positions detected count=%d trade_date=%s",
            len(residuals),
            trade_date,
        )
        create_integrity_alert_once(
            trade_date,
            alert_type="risk_guard",
            severity="WARNING",
            title="청산 대상 외 전일 전략 잔여 포지션 있음",
            detail=json_compact(residuals),
        )
    return residuals


def _classify_sell_result(result: dict[str, Any], summary: dict[str, int]) -> None:
    """Increment S9 summary counters from one sell result.

    Args:
        result: order_executor.execute_sell response payload.
        summary: Mutable summary counter map.
    """
    status = str(result.get("status") or "")
    if status == "skipped_duplicate":
        summary["skipped_duplicate"] += 1
    elif result.get("uncertain") or status in {"submitted_without_order_no", "submit_uncertain"}:
        summary["uncertain"] += 1
    elif result.get("ok") and result.get("kis_order_no"):
        summary["submitted"] += 1
    else:
        summary["failed"] += 1


async def run_eod_liquidation() -> dict[str, Any]:
    """15:20 KST: 보유 전 포지션을 시장가로 청산한다.

    인메모리 포지션을 우선 사용하되, 이미 매도 제출된 종목은 중복 청산하지 않는다.
    서버 재시작으로 비어 있으면 DB 순포지션을 조회하고 전일 잔여 포지션은 경고로 남긴다.
    """
    today = _today_kst()
    legacy_residual_positions = _record_legacy_residual_alert(today)
    positions = position_manager.get_positions()
    skipped_duplicates: list[dict[str, Any]] = []

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
        return {
            "liquidated": 0,
            "results": [],
            "summary": _empty_summary(),
            "legacy_residual_positions": legacy_residual_positions,
            "orphan_positions": legacy_residual_positions,
        }

    results = []
    summary = _empty_summary()
    for pos in positions:
        symbol = str(pos.get("symbol") or "")
        qty = int(pos.get("qty") or 0)
        if not symbol or qty <= 0:
            logger.warning("WARN: [S9] invalid liquidation position symbol=%s qty=%s", symbol, qty)
            continue
        duplicate_sell = find_active_sell_order(today, symbol)
        if duplicate_sell:
            result = {
                "ok": False,
                "status": "skipped_duplicate",
                "symbol": symbol,
                "qty": qty,
                "reason": "sell_already_submitted",
                "existing_order_id": duplicate_sell.get("id"),
                "existing_status": duplicate_sell.get("status"),
            }
            results.append(result)
            skipped_duplicates.append(result)
            _classify_sell_result(result, summary)
            logger.warning(
                "WARN: [S9] duplicate EOD sell skipped symbol=%s qty=%d existing_order_id=%s status=%s",
                symbol,
                qty,
                duplicate_sell.get("id"),
                duplicate_sell.get("status"),
            )
            continue
        result = await order_executor.execute_sell(
            symbol=symbol,
            qty=qty,
            price=0,
            reason="eod",
        )
        results.append(result)
        _classify_sell_result(result, summary)
    logger.info(
        "SUCCESS: [S9] EOD liquidation finished submitted=%d uncertain=%d skipped_duplicate=%d failed=%d",
        summary["submitted"],
        summary["uncertain"],
        summary["skipped_duplicate"],
        summary["failed"],
    )
    return {
        "liquidated": summary["submitted"],
        "results": results,
        "summary": summary,
        "skipped_duplicates": skipped_duplicates,
        "legacy_residual_positions": legacy_residual_positions,
        "orphan_positions": legacy_residual_positions,
    }
