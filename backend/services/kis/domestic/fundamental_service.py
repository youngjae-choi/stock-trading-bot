"""Domestic fundamental data service wrappers."""

from __future__ import annotations

import logging
from typing import Any, Dict

from ..common.client import kis_client

logger = logging.getLogger("KISFundamentalService")


async def get_fundamental(symbol: str) -> Dict[str, Any]:
    """Fetch fundamental financial statements by symbol.

    Fallback to alternate TR ID when the primary TR is unavailable.
    If both fail, return a soft-fail payload for API compatibility.
    """
    path = "/uapi/domestic-stock/v1/finance/financial-statements"
    params = {
        "fno_bstp_cls_code": "0",
        "qry_tp": "0",
        "pdno": symbol,
    }
    tr_ids = ["FHKST66430300", "HHKDB669300C0"]

    last_error = ""
    for tr_id in tr_ids:
        try:
            payload = await kis_client.request(method="GET", path=path, tr_id=tr_id, params=params)
            return {"ok": True, "symbol": symbol, "tr_id": tr_id, "payload": payload}
        except Exception as exc:
            last_error = str(exc)
            logger.warning("RETRY: fundamental request failed tr_id=%s symbol=%s reason=%s", tr_id, symbol, last_error)

    logger.error("FAIL: fundamental unavailable symbol=%s reason=%s", symbol, last_error)
    return {"ok": False, "symbol": symbol, "error": "재무 API 미지원"}
