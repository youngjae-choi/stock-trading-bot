"""Domestic stock API service wrappers."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Literal

from ....config import settings
from ..common.client import kis_client

logger = logging.getLogger("KISDomesticService")
TradingDayState = Literal["trading", "closed", "unknown"]


def _order_env() -> Literal["demo", "real"]:
    return "demo" if "openapivts" in kis_client.base_url.lower() else "real"


async def get_current_price(symbol: str) -> Dict[str, Any]:
    return await kis_client.request(
        method="GET",
        path="/uapi/domestic-stock/v1/quotations/inquire-price",
        tr_id="FHKST01010100",
        params={"fid_cond_mrkt_div_code": "J", "fid_input_iscd": symbol},
    )


async def get_order_book(symbol: str) -> Dict[str, Any]:
    return await kis_client.request(
        method="GET",
        path="/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn",
        tr_id="FHKST01010200",
        params={"fid_cond_mrkt_div_code": "J", "fid_input_iscd": symbol},
    )


async def get_balance() -> Dict[str, Any]:
    return await kis_client.request(
        method="GET",
        path="/uapi/domestic-stock/v1/trading/inquire-balance",
        tr_id="VTTC8434R" if _order_env() == "demo" else "TTTC8434R",
        params={
            "CANO": settings.KIS_CANO,
            "ACNT_PRDT_CD": settings.KIS_ACNT_PRDT_CD,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "01",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        },
    )


async def get_daily_order_inquiry(date_str: str, side: str = "buy") -> Dict[str, Any]:
    """당일 주문 체결 내역을 조회한다.

    Args:
        date_str: YYYYMMDD 형식의 조회 대상 일자.
        side: buy, sell, all 중 하나. KIS 매도매수구분코드로 변환된다.
    """
    side_value = str(side or "buy").lower()
    if side_value not in {"buy", "sell", "all"}:
        raise ValueError("side must be 'buy', 'sell', or 'all'")

    sll_buy_dvsn_cd = "02" if side_value == "buy" else "01" if side_value == "sell" else "00"
    env = _order_env()
    tr_id = "VTTC8001R" if env == "demo" else "TTTC8001R"
    return await kis_client.request(
        method="GET",
        path="/uapi/domestic-stock/v1/trading/inquire-daily-ccld",
        tr_id=tr_id,
        params={
            "CANO": settings.KIS_CANO,
            "ACNT_PRDT_CD": settings.KIS_ACNT_PRDT_CD,
            "INQR_STRT_DT": date_str,
            "INQR_END_DT": date_str,
            "SLL_BUY_DVSN_CD": sll_buy_dvsn_cd,
            "INQR_DVSN": "00",
            "PDNO": "",
            "CCLD_DVSN": "01",
            "ORD_GNO_BRNO": "",
            "ODNO": "",
            "INQR_DVSN_3": "00",
            "INQR_DVSN_1": "",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        },
    )


async def order_cash(
    *,
    side: Literal["buy", "sell"],
    symbol: str,
    qty: int,
    price: str,
    ord_dvsn: str = "00",
    excg_id_dvsn_cd: str = "KRX",
    sll_type: str = "",
    cndt_pric: str = "",
) -> Dict[str, Any]:
    side_value = side.lower()
    if side_value not in {"buy", "sell"}:
        raise ValueError("side must be 'buy' or 'sell'")

    tr_id_map = {
        ("real", "sell"): "TTTC0011U",
        ("real", "buy"): "TTTC0012U",
        ("demo", "sell"): "VTTC0011U",
        ("demo", "buy"): "VTTC0012U",
    }

    return await kis_client.request(
        method="POST",
        path="/uapi/domestic-stock/v1/trading/order-cash",
        tr_id=tr_id_map[(_order_env(), side_value)],
        body={
            "CANO": settings.KIS_CANO,
            "ACNT_PRDT_CD": settings.KIS_ACNT_PRDT_CD,
            "PDNO": symbol,
            "ORD_DVSN": ord_dvsn,
            "ORD_QTY": str(qty),
            "ORD_UNPR": str(price),
            "EXCG_ID_DVSN_CD": excg_id_dvsn_cd,
            "SLL_TYPE": sll_type,
            "CNDT_PRIC": cndt_pric,
        },
    )


async def order_rvsecncl(
    *,
    orgn_odno: str,
    qty: int,
    mode: Literal["modify", "cancel"],
    order_qty: int = 0,
    order_price: str = "0",
    ord_dvsn: str = "00",
    q_ord_yn: str = "N",
) -> Dict[str, Any]:
    mode_value = mode.lower()
    if mode_value not in {"modify", "cancel"}:
        raise ValueError("mode must be 'modify' or 'cancel'")

    tr_id_map = {
        ("real", "modify"): "TTTC0013U",
        ("real", "cancel"): "TTTC0014U",
        ("demo", "modify"): "VTTC0013U",
        ("demo", "cancel"): "VTTC0014U",
    }
    rvse_cncl_dvsn_cd = "01" if mode_value == "modify" else "02"
    body = {
        "CANO": settings.KIS_CANO,
        "ACNT_PRDT_CD": settings.KIS_ACNT_PRDT_CD,
        "KRX_FWDG_ORD_ORGNO": "",
        "ORGN_ODNO": orgn_odno,
        "ORD_DVSN": ord_dvsn,
        "RVSE_CNCL_DVSN_CD": rvse_cncl_dvsn_cd,
        "ORD_QTY": str(qty),
        "ORD_UNPR": str(order_price),
        "QTY_ALL_ORD_YN": q_ord_yn,
    }
    if mode_value == "modify":
        body["MGCO_APTM_ODNO"] = ""
        body["ORD_OBJT_CBLC_DVSN_CD"] = "10"
        body["ORD_QTY"] = str(order_qty)

    return await kis_client.request(
        method="POST",
        path="/uapi/domestic-stock/v1/trading/order-rvsecncl",
        tr_id=tr_id_map[(_order_env(), mode_value)],
        body=body,
    )


async def order_resv(
    *,
    symbol: str,
    qty: int,
    price: str,
    side_code: Literal["01", "02"],
    ord_dvsn_cd: str = "00",
    ord_objt_cblc_dvsn_cd: str = "10",
    loan_dt: str = "",
    rsvn_ord_end_dt: str = "",
    ldng_dt: str = "",
) -> Dict[str, Any]:
    settings = __import__("backend.config", fromlist=["settings"]).settings
    return await kis_client.request(
        method="POST",
        path="/uapi/domestic-stock/v1/trading/order-resv",
        tr_id="CTSC0008U",
        body={
            "CANO": settings.KIS_CANO,
            "ACNT_PRDT_CD": settings.KIS_ACNT_PRDT_CD,
            "PDNO": symbol,
            "ORD_QTY": str(qty),
            "ORD_UNPR": str(price),
            "SLL_BUY_DVSN_CD": side_code,
            "ORD_DVSN_CD": ord_dvsn_cd,
            "ORD_OBJT_CBLC_DVSN_CD": ord_objt_cblc_dvsn_cd,
            "LOAN_DT": loan_dt,
            "RSVN_ORD_END_DT": rsvn_ord_end_dt,
            "LDNG_DT": ldng_dt,
        },
    )


async def get_news_title(
    *,
    symbol: str,
    date_yyyymmdd: str | None = None,
    time_hhmmss: str = "000000",
) -> Dict[str, Any]:
    date_value = date_yyyymmdd or datetime.now().strftime("%Y%m%d")
    return await kis_client.request(
        method="GET",
        path="/uapi/domestic-stock/v1/quotations/news-title",
        tr_id="FHKST01011800",
        params={
            "FID_NEWS_OFER_ENTP_CODE": "2",
            "FID_COND_MRKT_CLS_CODE": "00",
            "FID_INPUT_ISCD": symbol,
            "FID_TITL_CNTT": "",
            "FID_INPUT_DATE_1": date_value,
            "FID_INPUT_HOUR_1": time_hhmmss,
            "FID_RANK_SORT_CLS_CODE": "01",
            "FID_INPUT_SRNO": "1",
        },
    )


async def get_daily_chart(
    *,
    symbol: str,
    period_code: Literal["D", "W", "M"] = "D",
    adjusted_price: Literal["0", "1"] = "1",
) -> Dict[str, Any]:
    return await kis_client.request(
        method="GET",
        path="/uapi/domestic-stock/v1/quotations/inquire-daily-price",
        tr_id="FHKST01010400",
        params={
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": symbol,
            "FID_PERIOD_DIV_CODE": period_code,
            "FID_ORG_ADJ_PRC": adjusted_price,
        },
    )


async def get_intraday_chart(
    *,
    symbol: str,
    input_hour: str = "153000",
    include_past: Literal["Y", "N"] = "Y",
    market_code: Literal["J", "NX", "UN"] = "J",
    etc_code: str = "",
) -> Dict[str, Any]:
    return await kis_client.request(
        method="GET",
        path="/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice",
        tr_id="FHKST03010200",
        params={
            "FID_COND_MRKT_DIV_CODE": market_code,
            "FID_INPUT_ISCD": symbol,
            "FID_INPUT_HOUR_1": input_hour,
            "FID_PW_DATA_INCU_YN": include_past,
            "FID_ETC_CLS_CODE": etc_code,
        },
    )


async def get_investor_profile(
    *,
    symbol: str,
    market_code: Literal["J", "NX", "UN"] = "J",
) -> Dict[str, Any]:
    """Fetch investor buy/sell flow by symbol (individual/foreign/institution)."""
    return await kis_client.request(
        method="GET",
        path="/uapi/domestic-stock/v1/quotations/inquire-investor",
        tr_id="FHKST01010900",
        params={
            "FID_COND_MRKT_DIV_CODE": market_code,
            "FID_INPUT_ISCD": symbol,
        },
    )


def _extract_trading_day_state(resp: Dict[str, Any]) -> tuple[TradingDayState, str]:
    """Convert a KIS chk-holiday response into a three-state trading-day result.

    Args:
        resp: Raw KIS chk-holiday response.
    """

    if not isinstance(resp, dict):
        return "unknown", "response_not_dict"

    rt_cd = str(resp.get("rt_cd") or "").strip()
    msg = str(resp.get("msg1") or resp.get("msg_cd") or "").strip()
    if rt_cd and rt_cd != "0":
        return "unknown", f"kis_error rt_cd={rt_cd} msg={msg or '-'}"

    output = resp.get("output")
    if isinstance(output, dict):
        output_rows = [output]
    elif isinstance(output, list):
        output_rows = output
    else:
        return "unknown", "missing_output"

    if not output_rows:
        return "unknown", "empty_output"

    first = output_rows[0]
    if not isinstance(first, dict):
        return "unknown", "output_row_not_dict"

    tr_day_yn = str(first.get("tr_day_yn") or "").strip().upper()
    if tr_day_yn == "Y":
        return "trading", "tr_day_yn=Y"
    if tr_day_yn == "N":
        return "closed", "tr_day_yn=N"
    return "unknown", f"unknown_tr_day_yn={tr_day_yn or '-'}"


_KIS_SERVICE_NOT_FOUND_MSGS = ("서비스를 찾을수 없습니다", "서비스를 찾을 수 없습니다", "service not found")


def _weekday_trading_day_fallback(date_str: str) -> dict[str, str]:
    """KIS API 미지원 환경(모의투자 등)에서 주말 + 한국 공휴일 기준으로 거래일 여부를 판단한다.

    holidays 라이브러리로 평일 공휴일(어린이날·현충일·임시공휴일 등)까지 closed로 잡는다.
    """
    try:
        from ...engine.trading_calendar import is_trading_day, non_trading_reason

        if is_trading_day(date_str):
            return {"status": "trading", "reason": "calendar_fallback:trading", "date": date_str}
        reason = non_trading_reason(date_str) or "closed"
        return {"status": "closed", "reason": f"calendar_fallback:{reason}", "date": date_str}
    except ValueError:
        return {"status": "unknown", "reason": "calendar_fallback:invalid_date", "date": date_str}
    except Exception as exc:  # 캘린더 오류 시 거래일 차단 방지
        return {"status": "unknown", "reason": f"calendar_fallback:error:{exc}", "date": date_str}


async def get_trading_day_status(date_str: str) -> dict[str, str]:
    """KIS API로 해당 날짜의 거래일 여부를 trading/closed/unknown으로 확인한다.

    모의투자 환경에서는 chk-holiday API가 지원되지 않을 수 있으며,
    이 경우 요일 기반 폴백(주말=closed, 평일=trading)을 사용한다.

    Args:
        date_str: YYYYMMDD 형식의 확인 대상 일자.
    """

    try:
        resp = await kis_client.request(
            method="GET",
            path="/uapi/domestic-stock/v1/quotations/chk-holiday",
            tr_id="CTCA0903R",
            params={"BASS_DT": date_str},
        )

        # 모의투자 서버에서 "서비스를 찾을수 없습니다" → 요일 폴백
        rt_cd = str(resp.get("rt_cd") or "").strip()
        msg1 = str(resp.get("msg1") or "").strip()
        if rt_cd != "0" and any(s in msg1 for s in _KIS_SERVICE_NOT_FOUND_MSGS):
            result = _weekday_trading_day_fallback(date_str)
            logger.warning(
                "WARN: KIS chk-holiday 미지원(모의투자) — 요일 폴백 사용 date=%s status=%s",
                date_str,
                result["status"],
            )
            return result

        status, reason = _extract_trading_day_state(resp)
        if status == "unknown":
            logger.warning("WARN: KIS trading-day status unknown date=%s reason=%s", date_str, reason)
        else:
            logger.info("INFO: KIS trading-day status date=%s status=%s reason=%s", date_str, status, reason)
        return {"status": status, "reason": reason, "date": date_str}
    except Exception as exc:
        logger.warning("WARN: KIS trading-day request failed date=%s reason=%s", date_str, exc)
        return {"status": "unknown", "reason": f"request_failed: {exc}", "date": date_str}


async def check_trading_day(date_str: str) -> bool:
    """KIS API로 해당 날짜가 주식 거래일인지 확인한다.

    Args:
        date_str: YYYYMMDD 형식.
    Returns:
        True = 거래일, False = 명확한 휴장일 또는 unknown.
    """

    result = await get_trading_day_status(date_str)
    return result["status"] == "trading"
