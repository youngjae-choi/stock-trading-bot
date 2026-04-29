"""Common market interface that dispatches domestic/overseas operations."""

from __future__ import annotations

from typing import Any, Dict, Literal

from ..domestic import service as domestic
from ..overseas import service as overseas

MarketType = Literal["domestic", "overseas"]


async def get_price(*, market: MarketType, symbol: str, exchange: str = "") -> Dict[str, Any]:
    if market == "domestic":
        return await domestic.get_current_price(symbol)
    return await overseas.get_current_price(exchange=exchange, symbol=symbol)


async def get_daily_chart(
    *,
    market: MarketType,
    symbol: str,
    exchange: str = "",
    period_code: Literal["D", "W", "M"] = "D",
    adjusted_price: Literal["0", "1"] = "1",
) -> Dict[str, Any]:
    if market == "domestic":
        return await domestic.get_daily_chart(symbol=symbol, period_code=period_code, adjusted_price=adjusted_price)
    return await overseas.get_daily_chart(
        exchange=exchange,
        symbol=symbol,
        period_code=period_code,
        adjusted_price=adjusted_price,
    )


async def order_cash(
    *,
    market: MarketType,
    side: Literal["buy", "sell"],
    symbol: str,
    qty: int,
    price: str,
    exchange: str = "",
    ord_dvsn: str = "00",
) -> Dict[str, Any]:
    if market == "domestic":
        return await domestic.order_cash(side=side, symbol=symbol, qty=qty, price=price, ord_dvsn=ord_dvsn)
    return await overseas.order_cash(
        side=side,
        exchange=exchange,
        symbol=symbol,
        qty=qty,
        price=price,
        ord_dvsn=ord_dvsn,
    )


async def order_rvsecncl(
    *,
    market: MarketType,
    mode: Literal["modify", "cancel"],
    orgn_odno: str,
    qty: int,
    order_price: str,
    symbol: str = "",
    exchange: str = "",
) -> Dict[str, Any]:
    if market == "domestic":
        return await domestic.order_rvsecncl(
            mode=mode,
            orgn_odno=orgn_odno,
            qty=qty,
            order_qty=qty,
            order_price=order_price,
        )
    return await overseas.order_rvsecncl(
        exchange=exchange,
        symbol=symbol,
        orgn_odno=orgn_odno,
        mode=mode,
        qty=qty,
        order_price=order_price,
    )
