"""Account summary routes backed by KIS domestic balance API."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ...config import settings, validate_config
from ...services.kis.domestic.service import get_balance
from ...services.settings_store import get_setting
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


def _to_optional_int(value: Any) -> int | None:
    """Convert a KIS numeric string to int while preserving blank fields as None.

    Args:
        value: Raw KIS value, usually a string.
    """
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if text == "":
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


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

    # deposit: 예탁금 총액 (계좌 한도 표시용)
    deposit = _to_int(summary.get("dnca_tot_amt"))

    # 주문 가능 예수금 계산:
    #   실계좌: ord_psbl_cash — KIS가 직접 제공하는 주문가능현금 (정확)
    #   모의투자: ord_psbl_cash = 0 이므로 사용 불가.
    #     nxdy_excc_amt / prvs_rcdl_excc_amt 는 익일/전일 정산금으로 당일 매수를 즉시 반영하지 않아
    #     예탁금 총액(1억)과 동일하게 나타남 → "남은 현금" 과 괴리 발생.
    #   따라서: total_eval - stock_eval = 현금 잔액으로 근사 계산 (가장 실시간에 가까움)
    #     실계좌에서도 ord_psbl_cash 가 0일 경우 동일 로직 적용.
    total_eval = _to_int(summary.get("tot_evlu_amt"))
    stock_eval = _to_int(summary.get("scts_evlu_amt"))
    ord_psbl_cash = _to_int(summary.get("ord_psbl_cash"))
    if ord_psbl_cash > 0:
        buyable_cash = ord_psbl_cash
    elif total_eval > 0 and stock_eval >= 0:
        # 현금 = 총평가금액 - 주식평가금액
        buyable_cash = max(0, total_eval - stock_eval)
    else:
        # 최후 수단: nxdy_excc_amt → prvs_rcdl_excc_amt → dnca_tot_amt
        buyable_cash = 0
        for key in ("nxdy_excc_amt", "prvs_rcdl_excc_amt", "dnca_tot_amt"):
            candidate = _to_int(summary.get(key))
            if candidate > 0:
                buyable_cash = candidate
                break

    # 원금(시드) 대비 누적 수익률: KIS 자산증감수익률(0%)과 별개로 시드 대비 누적을 표기.
    try:
        principal = int(_to_float(get_setting("account.principal", 100000000), 100000000))
    except Exception:
        principal = 100000000
    if principal > 0:
        cumulative_pnl = total_eval - principal
        cumulative_return_pct = round((total_eval - principal) / principal * 100, 2)
    else:
        cumulative_pnl = 0
        cumulative_return_pct = 0.0

    # 당일 손익(통합) = 당일 실현손익(청산 완료) + 미실현 평가손익(보유종목).
    # 단타 청산 시 미실현이 0이 되며 실현분이 화면에서 누락되던 문제를 해결한다.
    # 분모는 당일 시작자본(daily_capital_baseline) — 없으면 총평가금액으로 폴백.
    pnl_total_unrealized = _to_int(summary.get("evlu_pfls_smtl_amt"))
    try:
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo as _ZI
        from ...services.engine.trade_pairs import get_today_realized_pnl
        from ...services.engine.daily_capital import get_baseline

        _today = _dt.now(_ZI("Asia/Seoul")).strftime("%Y-%m-%d")
        today_realized_pnl = int(get_today_realized_pnl(_today))
        _base = get_baseline(_today) or (total_eval or principal)
        daily_pnl_total = today_realized_pnl + pnl_total_unrealized
        daily_pnl_pct = round(daily_pnl_total / _base * 100, 2) if _base else 0.0
    except Exception as exc:
        logger.warning("WARN: account daily realized pnl 계산 실패 — %s", exc)
        today_realized_pnl = 0
        daily_pnl_total = pnl_total_unrealized
        daily_pnl_pct = 0.0

    account_no = f"{settings.KIS_CANO}{settings.KIS_ACNT_PRDT_CD}"
    return {
        "account_no": account_no,
        "principal": principal,                       # 계좌 원금(시드)
        "cumulative_pnl": cumulative_pnl,             # 시드 대비 누적 손익 (원)
        "cumulative_return_pct": cumulative_return_pct,  # 시드 대비 누적 수익률 (%)
        "today_realized_pnl": today_realized_pnl,     # 당일 청산 실현손익 (원)
        "daily_pnl_total": daily_pnl_total,           # 당일 손익 = 실현 + 미실현 (원)
        "daily_pnl_pct": daily_pnl_pct,               # 당일 손익률 = 당일손익 / 시작자본 (%)
        "deposit": deposit,                           # 예탁금 총액 (계좌 한도)
        "buyable_cash": buyable_cash,                 # 주문 가능 예수금 (현금 잔액)
        "available_cash": buyable_cash,
        # 정산예정금: 주문가능(총평가-주식평가 근사) - 예수금(dnca). 모의투자 가수도 정산분.
        # buyable_cash > deposit 으로 보이는 차이를 화면에서 따로 표기하기 위함.
        "settlement_pending": buyable_cash - deposit,
        "total_eval": total_eval,                     # 총평가금액 (현금 + 주식)
        "purchase_total": _to_int(summary.get("pchs_amt_smtl_amt")),
        "pnl_total": _to_int(summary.get("evlu_pfls_smtl_amt")),
        "stock_eval": stock_eval,                     # 주식 평가금액
        "pnl_rate": _to_float(summary.get("asst_icdc_erng_rt")),    # 자산증감수익률
        "prev_buy_amt": _to_int(summary.get("bfdy_buy_amt")),       # 전일 매수금액
        "today_buy_amt": _to_optional_int(summary.get("thdt_buy_amt")),      # 당일 매수금액
        "today_sell_amt": _to_optional_int(summary.get("thdt_sll_amt")),     # 당일 매도금액
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
