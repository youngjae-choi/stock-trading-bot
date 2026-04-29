"""Overseas stock API service wrappers."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Literal

from ....config import settings
from ..common.client import kis_client
from ..common.exchanges import normalize_order_exchange, to_overseas_excd


def _order_env() -> Literal["demo", "real"]:
    return "demo" if "openapivts" in kis_client.base_url.lower() else "real"


def _resolve_overseas_order_tr_id(side: Literal["buy", "sell"], exchange: str) -> str:
    exchange_code = normalize_order_exchange(exchange)
    buy_map = {
        "NASD": "TTTT1002U",
        "NYSE": "TTTT1002U",
        "AMEX": "TTTT1002U",
        "SEHK": "TTTS1002U",
        "SHAA": "TTTS0202U",
        "SZAA": "TTTS0305U",
        "TKSE": "TTTS0308U",
        "HASE": "TTTS0311U",
        "VNSE": "TTTS0311U",
    }
    sell_map = {
        "NASD": "TTTT1006U",
        "NYSE": "TTTT1006U",
        "AMEX": "TTTT1006U",
        "SEHK": "TTTS1001U",
        "SHAA": "TTTS1005U",
        "SZAA": "TTTS0304U",
        "TKSE": "TTTS0307U",
        "HASE": "TTTS0310U",
        "VNSE": "TTTS0310U",
    }
    source = buy_map if side == "buy" else sell_map
    tr_id = source[exchange_code]
    if _order_env() == "demo":
        tr_id = "V" + tr_id[1:]
    return tr_id


async def get_current_price(*, exchange: str, symbol: str, auth: str = "") -> Dict[str, Any]:
    excd = to_overseas_excd(exchange)
    return await kis_client.request(
        method="GET",
        path="/uapi/overseas-price/v1/quotations/price",
        tr_id="HHDFS00000300",
        params={"AUTH": auth, "EXCD": excd, "SYMB": symbol.upper()},
    )


async def get_daily_chart(
    *,
    exchange: str,
    symbol: str,
    period_code: Literal["D", "W", "M"] = "D",
    adjusted_price: Literal["0", "1"] = "1",
    base_date: str | None = None,
    auth: str = "",
) -> Dict[str, Any]:
    excd = to_overseas_excd(exchange)
    gubn_map = {"D": "0", "W": "1", "M": "2"}
    bymd = base_date or datetime.now().strftime("%Y%m%d")
    return await kis_client.request(
        method="GET",
        path="/uapi/overseas-price/v1/quotations/dailyprice",
        tr_id="HHDFS76240000",
        params={
            "AUTH": auth,
            "EXCD": excd,
            "SYMB": symbol.upper(),
            "GUBN": gubn_map[period_code],
            "BYMD": bymd,
            "MODP": adjusted_price,
        },
    )


async def order_cash(
    *,
    side: Literal["buy", "sell"],
    exchange: str,
    symbol: str,
    qty: int,
    price: str,
    ord_dvsn: str = "00",
    ctac_tlno: str = "",
    mgco_aptm_odno: str = "",
    ord_svr_dvsn_cd: str = "0",
) -> Dict[str, Any]:
    side_value = side.lower()
    if side_value not in {"buy", "sell"}:
        raise ValueError("side must be 'buy' or 'sell'")

    exchange_code = normalize_order_exchange(exchange)
    tr_id = _resolve_overseas_order_tr_id(side_value, exchange_code)
    return await kis_client.request(
        method="POST",
        path="/uapi/overseas-stock/v1/trading/order",
        tr_id=tr_id,
        body={
            "CANO": settings.KIS_CANO,
            "ACNT_PRDT_CD": settings.KIS_ACNT_PRDT_CD,
            "OVRS_EXCG_CD": exchange_code,
            "PDNO": symbol.upper(),
            "ORD_QTY": str(qty),
            "OVRS_ORD_UNPR": str(price),
            "CTAC_TLNO": ctac_tlno,
            "MGCO_APTM_ODNO": mgco_aptm_odno,
            "SLL_TYPE": "" if side_value == "buy" else "00",
            "ORD_SVR_DVSN_CD": ord_svr_dvsn_cd,
            "ORD_DVSN": ord_dvsn,
        },
    )


async def order_rvsecncl(
    *,
    exchange: str,
    symbol: str,
    orgn_odno: str,
    mode: Literal["modify", "cancel"],
    qty: int,
    order_price: str,
    mgco_aptm_odno: str = "",
    ord_svr_dvsn_cd: str = "0",
) -> Dict[str, Any]:
    mode_value = mode.lower()
    if mode_value not in {"modify", "cancel"}:
        raise ValueError("mode must be 'modify' or 'cancel'")

    exchange_code = normalize_order_exchange(exchange)
    rvse_cncl_dvsn_cd = "01" if mode_value == "modify" else "02"
    tr_id = "VTTT1004U" if _order_env() == "demo" else "TTTT1004U"

    return await kis_client.request(
        method="POST",
        path="/uapi/overseas-stock/v1/trading/order-rvsecncl",
        tr_id=tr_id,
        body={
            "CANO": settings.KIS_CANO,
            "ACNT_PRDT_CD": settings.KIS_ACNT_PRDT_CD,
            "OVRS_EXCG_CD": exchange_code,
            "PDNO": symbol.upper(),
            "ORGN_ODNO": orgn_odno,
            "RVSE_CNCL_DVSN_CD": rvse_cncl_dvsn_cd,
            "ORD_QTY": str(qty),
            "OVRS_ORD_UNPR": str(order_price),
            "MGCO_APTM_ODNO": mgco_aptm_odno,
            "ORD_SVR_DVSN_CD": ord_svr_dvsn_cd,
        },
    )
