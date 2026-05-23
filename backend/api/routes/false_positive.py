"""False Positive API routes for daily judgment validation cases."""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query

from ...services.engine.false_positive import (
    generate_false_positives_for_date,
    get_false_positives,
    get_today_false_positives,
    mark_false_positive_reviewed,
)

router = APIRouter(prefix="/api/v1/false-positive", tags=["false-positive"])
logger = logging.getLogger("FalsePositiveAPI")


def _today_kst() -> str:
    """Return today's KST date as YYYY-MM-DD for route defaults."""
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


@router.get("/today")
def get_today(trade_date: str = Query(None, description="YYYY-MM-DD (기본값: 오늘)")) -> dict:
    """특정 날짜의 false positive 케이스를 반환한다."""
    if not trade_date:
        trade_date = _today_kst()
    logger.info("START: GET /api/v1/false-positive/today trade_date=%s", trade_date)
    rows = get_today_false_positives(trade_date)
    logger.info("SUCCESS: GET /api/v1/false-positive/today trade_date=%s count=%d", trade_date, len(rows))
    return {"ok": True, "payload": rows}


@router.get("/list")
def get_list(
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    include_reviewed: bool = Query(False, description="확인 완료 케이스 포함 여부"),
) -> dict:
    """날짜 범위 내 false positive 케이스 목록을 반환한다. 기본: 미확인만."""
    logger.info("START: GET /api/v1/false-positive/list start=%s end=%s include_reviewed=%s", start, end, include_reviewed)
    rows = get_false_positives(start, end, include_reviewed=include_reviewed)
    logger.info("SUCCESS: GET /api/v1/false-positive/list count=%d", len(rows))
    return {"ok": True, "payload": {"items": rows, "count": len(rows)}}


@router.patch("/{fp_id}/review")
def review_case(fp_id: str) -> dict:
    """False positive 케이스를 확인 완료 처리한다 (화면에서 숨김)."""
    logger.info("START: PATCH /api/v1/false-positive/%s/review", fp_id)
    updated = mark_false_positive_reviewed(fp_id)
    if not updated:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"ok": False, "error": "not found"})
    logger.info("SUCCESS: PATCH /api/v1/false-positive/%s/review", fp_id)
    return {"ok": True}


@router.post("/generate")
async def generate(
    trade_date: str = Query(None, description="YYYY-MM-DD (기본값: 오늘)"),
) -> dict:
    """지정 날짜의 손실 거래를 분석해 false positive 케이스를 생성한다.

    trade_pairs에서 매도완료 + pnl < 0인 페어를 탐색하고
    false_positive_cases 테이블에 신규 기록을 저장한다.
    """
    if not trade_date:
        trade_date = _today_kst()
    logger.info("START: POST /api/v1/false-positive/generate trade_date=%s", trade_date)
    result = generate_false_positives_for_date(trade_date)
    logger.info(
        "SUCCESS: POST /api/v1/false-positive/generate trade_date=%s saved=%d skipped=%d",
        trade_date,
        len(result.get("saved", [])),
        len(result.get("skipped", [])),
    )
    return {"ok": True, "payload": result}
