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
        avg_price = _to_float(item.get("pchs_avg_pric"))
        purchase_amount = _to_float(item.get("pchs_amt"))
        if purchase_amount <= 0:
            purchase_amount = _to_float(item.get("evlu_amt"))
        if purchase_amount <= 0:
            purchase_amount = avg_price * qty
        positions.append(
            {
                "symbol": str(item.get("pdno") or ""),
                "name": str(item.get("prdt_name") or ""),
                "qty": qty,
                "avg_price": avg_price,
                "current_price": _to_float(item.get("prpr")),
                "purchase_amount": purchase_amount,
                "pnl_pct": _to_float(item.get("evlu_pfls_rt")),
            }
        )

    summary_rows = _as_list(data.get("output2"))
    summary = summary_rows[0] if summary_rows else {}

    # 주문 가능 예수금 우선순위:
    #   ord_psbl_cash   — 실계좌에서 제공되는 주문가능금액 (가상계좌에는 없을 수 있음)
    #   nxdy_excc_amt   — 익일정산금 = 매수 후 차감된 실제 주문 가능 현금 (가상계좌 기준)
    #   prvs_rcdl_excc_amt — 전일정산금 (nxdy_excc_amt 없을 때 fallback)
    #   dnca_tot_amt    — 예탁금 총액 (가상계좌 한도 1억 고정 — 최후 수단)
    buyable_cash = 0
    for key in ("ord_psbl_cash", "nxdy_excc_amt", "prvs_rcdl_excc_amt", "dnca_tot_amt"):
        candidate = _to_int(summary.get(key))
        if candidate > 0:
            buyable_cash = candidate
            break

    # deposit: 예탁금 총액 (계좌 한도 표시용)
    deposit = _to_int(summary.get("dnca_tot_amt"))

    account_no = f"{settings.KIS_CANO}{settings.KIS_ACNT_PRDT_CD}"
    return {
        "account_no": account_no,
        "deposit": deposit,                           # 예탁금 총액 (한도)
        "buyable_cash": buyable_cash,                 # 주문 가능 예수금 (실시간)
        "available_cash": buyable_cash,
        "total_eval": _to_int(summary.get("tot_evlu_amt")),
        "purchase_total": _to_int(summary.get("pchs_amt_smtl_amt")),
        "pnl_total": _to_int(summary.get("evlu_pfls_smtl_amt")),
        "stock_eval": _to_int(summary.get("scts_evlu_amt")),        # 주식 평가금액
        "pnl_rate": _to_float(summary.get("asst_icdc_erng_rt")),    # 자산증감수익률
        "prev_buy_amt": _to_int(summary.get("bfdy_buy_amt")),       # 전일 매수금액
        "today_buy_amt": _to_int(summary.get("thdt_buy_amt")),      # 당일 매수금액
        "today_sell_amt": _to_int(summary.get("thdt_sll_amt")),     # 당일 매도금액
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
