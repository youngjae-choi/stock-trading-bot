"""Account summary routes backed by KIS domestic balance API."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ...config import settings, validate_config
from ...services.kis.domestic.service import get_balance
from ..dependencies import kis_config_error_response

logger = logging.getLogger("BackendAccountAPI")
router = APIRouter(prefix="/api/v1/account", tags=["account"])


def _to_float(value: Any, default: float = 0.0) -> float:
    """Convert KIS numeric strings to float while tolerating blanks and commas.

    Args:
        value: Raw KIS value, usually a string.
        default: Value returned when conversion is not possible.
    """
    try:
        return float(str(value).replace(",", "").strip() or default)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    """Convert KIS numeric strings to int while tolerating blanks and decimals.

    Args:
        value: Raw KIS value, usually a string.
        default: Value returned when conversion is not possible.
    """
    return int(_to_float(value, float(default)))


def _as_list(value: Any) -> list[dict[str, Any]]:
    """Normalize a KIS output field into a list of dictionaries.

    Args:
        value: Raw KIS output field.
    """
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _build_balance_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Build the public account balance payload from the raw KIS response.

    Args:
        data: Raw response returned by domestic_service.get_balance().
    """
    positions = []
    for item in _as_list(data.get("output1")):
        qty = _to_int(item.get("hldg_qty"))
        positions.append(
            {
                "symbol": str(item.get("pdno") or ""),
                "name": str(item.get("prdt_name") or ""),
                "qty": qty,
                "avg_price": _to_float(item.get("pchs_avg_pric")),
                "current_price": _to_float(item.get("prpr")),
                "pnl_pct": _to_float(item.get("evlu_pfls_rt")),
            }
        )

    summary_rows = _as_list(data.get("output2"))
    summary = summary_rows[0] if summary_rows else {}
    account_no = f"{settings.KIS_CANO}{settings.KIS_ACNT_PRDT_CD}"
    return {
        "account_no": account_no,
        "deposit": _to_int(summary.get("dnca_tot_amt")),
        "total_eval": _to_int(summary.get("tot_evlu_amt")),
        "purchase_total": _to_int(summary.get("pchs_amt_smtl_amt")),
        "pnl_total": _to_int(summary.get("evlu_pfls_smtl_amt")),
        "positions": positions,
    }


@router.get("/balance")
async def get_account_balance():
    """계좌 잔고 조회 — 예수금, 보유종목, 평가손익."""
    endpoint = "/api/v1/account/balance"
    if not validate_config():
        return kis_config_error_response(endpoint)

    logger.info("START: GET %s", endpoint)
    try:
        data = await get_balance()
        payload = _build_balance_payload(data)
        logger.info("SUCCESS: GET %s positions=%d", endpoint, len(payload["positions"]))
        return {"ok": True, "payload": payload}
    except Exception as exc:
        logger.error("FAIL: GET %s — %s", endpoint, exc)
        return JSONResponse(status_code=502, content={"ok": False, "error": str(exc)})
