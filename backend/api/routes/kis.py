"""KIS domestic/overseas trading and quotation routes."""

from __future__ import annotations

import logging
import re
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ...config import validate_config
from ...services.alert_service import send_telegram_alert
from ...services.kis.common.client import kis_client
from ...services.kis.common.market_interface import (
    get_daily_chart as get_market_daily_chart,
    get_price as get_market_price,
    order_cash as market_order_cash,
    order_rvsecncl as market_order_rvsecncl,
)
from ...services.kis.domestic import service as domestic_service
from ..dependencies import kis_config_error_response
from ..models import (
    KISCashOrderRequest,
    KISOverseasCashOrderRequest,
    KISOverseasRvseCnclRequest,
    KISReserveOrderRequest,
    KISRvseCnclRequest,
)

logger = logging.getLogger("BackendKISAPI")
router = APIRouter(prefix="/api/v1/kis", tags=["kis"])


@router.get("/token/status")
async def get_token_status():
    if not validate_config():
        return kis_config_error_response("/api/v1/kis/token/status")
    try:
        logger.info("START: /api/v1/kis/token/status")
        await kis_client.get_token()
        return {
            "ok": True,
            "is_active": True,
            "expires_at": kis_client.token_expires_at,
            "expires_in": int(kis_client.token_expires_at - time.time()),
        }
    except Exception as exc:
        logger.error("FAIL: /api/v1/kis/token/status - %s", str(exc))
        return JSONResponse(
            status_code=502,
            content={"ok": False, "is_active": False, "error": str(exc), "expires_at": 0},
        )


@router.get("/price/{symbol}")
async def get_price(symbol: str):
    if not validate_config():
        return kis_config_error_response(f"/api/v1/kis/price/{symbol}")
    try:
        logger.info("START: /api/v1/kis/price/%s", symbol)
        data = await domestic_service.get_current_price(symbol)
        logger.info("SUCCESS: /api/v1/kis/price/%s", symbol)
        return data
    except Exception as exc:
        logger.error("FAIL: /api/v1/kis/price/%s - %s", symbol, str(exc))
        return JSONResponse(status_code=502, content={"ok": False, "error": str(exc)})


@router.get("/orderbook/{symbol}")
async def get_orderbook(symbol: str):
    if not validate_config():
        return kis_config_error_response(f"/api/v1/kis/orderbook/{symbol}")
    try:
        logger.info("START: /api/v1/kis/orderbook/%s", symbol)
        data = await domestic_service.get_order_book(symbol)
        logger.info("SUCCESS: /api/v1/kis/orderbook/%s", symbol)
        return data
    except Exception as exc:
        logger.error("FAIL: /api/v1/kis/orderbook/%s - %s", symbol, str(exc))
        return JSONResponse(status_code=502, content={"ok": False, "error": str(exc)})


@router.get("/balance")
async def get_balance():
    if not validate_config():
        return kis_config_error_response("/api/v1/kis/balance")
    try:
        logger.info("START: /api/v1/kis/balance")
        data = await domestic_service.get_balance()
        logger.info("SUCCESS: /api/v1/kis/balance")
        return data
    except Exception as exc:
        logger.error("FAIL: /api/v1/kis/balance - %s", str(exc))
        await send_telegram_alert("KIS BALANCE FAIL", str(exc))
        return JSONResponse(status_code=502, content={"ok": False, "error": str(exc)})


@router.post("/order/cash")
async def order_cash(payload: KISCashOrderRequest):
    if not validate_config():
        return kis_config_error_response("/api/v1/kis/order/cash")
    try:
        logger.info("START: /api/v1/kis/order/cash side=%s symbol=%s qty=%s", payload.side, payload.symbol, payload.qty)
        data = await domestic_service.order_cash(
            side=payload.side,
            symbol=payload.symbol,
            qty=payload.qty,
            price=payload.price,
            ord_dvsn=payload.ord_dvsn,
            excg_id_dvsn_cd=payload.excg_id_dvsn_cd,
            sll_type=payload.sll_type,
            cndt_pric=payload.cndt_pric,
        )
        await send_telegram_alert(
            "KIS ORDER CASH",
            f"{payload.side.upper()} {payload.symbol} qty={payload.qty} price={payload.price}",
        )
        return {"ok": True, "mode": "kis_rest", "payload": data}
    except Exception as exc:
        logger.error("FAIL: /api/v1/kis/order/cash - %s", str(exc))
        await send_telegram_alert("KIS ORDER CASH FAIL", str(exc))
        return JSONResponse(status_code=502, content={"ok": False, "error": str(exc)})


@router.post("/order/rvsecncl")
async def order_rvsecncl(payload: KISRvseCnclRequest):
    if not validate_config():
        return kis_config_error_response("/api/v1/kis/order/rvsecncl")
    try:
        logger.info("START: /api/v1/kis/order/rvsecncl mode=%s orgn_odno=%s", payload.mode, payload.orgn_odno)
        data = await domestic_service.order_rvsecncl(
            mode=payload.mode,
            orgn_odno=payload.orgn_odno,
            qty=payload.qty,
            order_qty=payload.order_qty,
            order_price=payload.order_price,
            ord_dvsn=payload.ord_dvsn,
            q_ord_yn=payload.qty_all_ord_yn,
        )
        await send_telegram_alert("KIS ORDER RVSECNCL", f"{payload.mode.upper()} orgn_odno={payload.orgn_odno}")
        return {"ok": True, "mode": "kis_rest", "payload": data}
    except Exception as exc:
        logger.error("FAIL: /api/v1/kis/order/rvsecncl - %s", str(exc))
        await send_telegram_alert("KIS ORDER RVSECNCL FAIL", str(exc))
        return JSONResponse(status_code=502, content={"ok": False, "error": str(exc)})


@router.post("/order/reserve")
async def order_reserve(payload: KISReserveOrderRequest):
    if not validate_config():
        return kis_config_error_response("/api/v1/kis/order/reserve")
    side_code = "02" if payload.side == "buy" else "01"
    try:
        logger.info("START: /api/v1/kis/order/reserve side=%s symbol=%s qty=%s", payload.side, payload.symbol, payload.qty)
        data = await domestic_service.order_resv(
            symbol=payload.symbol,
            qty=payload.qty,
            price=payload.price,
            side_code=side_code,
            ord_dvsn_cd=payload.ord_dvsn_cd,
            ord_objt_cblc_dvsn_cd=payload.ord_objt_cblc_dvsn_cd,
            loan_dt=payload.loan_dt,
            rsvn_ord_end_dt=payload.rsvn_ord_end_dt,
            ldng_dt=payload.ldng_dt,
        )
        await send_telegram_alert(
            "KIS ORDER RESERVE",
            f"{payload.side.upper()} {payload.symbol} qty={payload.qty} price={payload.price}",
        )
        return {"ok": True, "mode": "kis_rest", "payload": data}
    except Exception as exc:
        logger.error("FAIL: /api/v1/kis/order/reserve - %s", str(exc))
        await send_telegram_alert("KIS ORDER RESERVE FAIL", str(exc))
        return JSONResponse(status_code=502, content={"ok": False, "error": str(exc)})


@router.get("/news-title/{symbol}")
async def get_news_title(symbol: str, date_yyyymmdd: str = "", time_hhmmss: str = "000000"):
    if not validate_config():
        return kis_config_error_response(f"/api/v1/kis/news-title/{symbol}")
    try:
        payload = await domestic_service.get_news_title(
            symbol=symbol,
            date_yyyymmdd=(date_yyyymmdd or None),
            time_hhmmss=time_hhmmss,
        )
        return {"ok": True, "symbol": symbol, "payload": payload}
    except Exception as exc:
        logger.error("FAIL: /api/v1/kis/news-title/%s - %s", symbol, str(exc))
        return JSONResponse(status_code=502, content={"ok": False, "error": str(exc)})


@router.get("/chart/daily/{symbol}")
async def get_daily_chart(symbol: str, period_code: str = "D", adjusted_price: str = "1"):
    if not validate_config():
        return kis_config_error_response(f"/api/v1/kis/chart/daily/{symbol}")
    safe_period = period_code.upper()
    if safe_period not in {"D", "W", "M"}:
        return JSONResponse(status_code=400, content={"ok": False, "error": "period_code must be D/W/M"})
    safe_adjusted = "1" if adjusted_price not in {"0", "1"} else adjusted_price
    try:
        payload = await domestic_service.get_daily_chart(symbol=symbol, period_code=safe_period, adjusted_price=safe_adjusted)
        return {
            "ok": True,
            "symbol": symbol,
            "period_code": safe_period,
            "adjusted_price": safe_adjusted,
            "payload": payload,
        }
    except Exception as exc:
        logger.error("FAIL: /api/v1/kis/chart/daily/%s - %s", symbol, str(exc))
        return JSONResponse(status_code=502, content={"ok": False, "error": str(exc)})


@router.get("/chart/intraday/{symbol}")
async def get_intraday_chart(symbol: str, input_hour: str = "153000", include_past: str = "Y"):
    if not validate_config():
        return kis_config_error_response(f"/api/v1/kis/chart/intraday/{symbol}")
    safe_include = "Y" if include_past not in {"Y", "N"} else include_past
    safe_hour = input_hour if re.fullmatch(r"\d{6}", input_hour or "") else "153000"
    try:
        payload = await domestic_service.get_intraday_chart(
            symbol=symbol,
            input_hour=safe_hour,
            include_past=safe_include,
            market_code="J",
        )
        return {
            "ok": True,
            "symbol": symbol,
            "input_hour": safe_hour,
            "include_past": safe_include,
            "payload": payload,
        }
    except Exception as exc:
        logger.error("FAIL: /api/v1/kis/chart/intraday/%s - %s", symbol, str(exc))
        return JSONResponse(status_code=502, content={"ok": False, "error": str(exc)})


@router.get("/overseas/price/{exchange}/{symbol}")
async def get_overseas_price(exchange: str, symbol: str):
    if not validate_config():
        return kis_config_error_response(f"/api/v1/kis/overseas/price/{exchange}/{symbol}")
    try:
        payload = await get_market_price(market="overseas", exchange=exchange, symbol=symbol)
        return {"ok": True, "exchange": exchange.upper(), "symbol": symbol.upper(), "payload": payload}
    except Exception as exc:
        logger.error("FAIL: /api/v1/kis/overseas/price/%s/%s - %s", exchange, symbol, str(exc))
        return JSONResponse(status_code=502, content={"ok": False, "error": str(exc)})


@router.get("/overseas/chart/daily/{exchange}/{symbol}")
async def get_overseas_daily_chart(
    exchange: str,
    symbol: str,
    period_code: str = "D",
    adjusted_price: str = "1",
):
    if not validate_config():
        return kis_config_error_response(f"/api/v1/kis/overseas/chart/daily/{exchange}/{symbol}")
    safe_period = period_code.upper()
    if safe_period not in {"D", "W", "M"}:
        return JSONResponse(status_code=400, content={"ok": False, "error": "period_code must be D/W/M"})
    safe_adjusted = "1" if adjusted_price not in {"0", "1"} else adjusted_price
    try:
        payload = await get_market_daily_chart(
            market="overseas",
            exchange=exchange,
            symbol=symbol,
            period_code=safe_period,
            adjusted_price=safe_adjusted,
        )
        return {
            "ok": True,
            "exchange": exchange.upper(),
            "symbol": symbol.upper(),
            "period_code": safe_period,
            "adjusted_price": safe_adjusted,
            "payload": payload,
        }
    except Exception as exc:
        logger.error("FAIL: /api/v1/kis/overseas/chart/daily/%s/%s - %s", exchange, symbol, str(exc))
        return JSONResponse(status_code=502, content={"ok": False, "error": str(exc)})


@router.post("/overseas/order/cash")
async def order_overseas_cash(payload: KISOverseasCashOrderRequest):
    if not validate_config():
        return kis_config_error_response("/api/v1/kis/overseas/order/cash")
    try:
        data = await market_order_cash(
            market="overseas",
            side=payload.side,
            symbol=payload.symbol,
            qty=payload.qty,
            price=payload.price,
            exchange=payload.exchange,
            ord_dvsn=payload.ord_dvsn,
        )
        await send_telegram_alert(
            "KIS OVERSEAS ORDER CASH",
            f"{payload.side.upper()} {payload.exchange.upper()}:{payload.symbol.upper()} qty={payload.qty} price={payload.price}",
        )
        return {"ok": True, "mode": "kis_rest", "payload": data}
    except Exception as exc:
        logger.error("FAIL: /api/v1/kis/overseas/order/cash - %s", str(exc))
        await send_telegram_alert("KIS OVERSEAS ORDER CASH FAIL", str(exc))
        return JSONResponse(status_code=502, content={"ok": False, "error": str(exc)})


@router.post("/overseas/order/rvsecncl")
async def order_overseas_rvsecncl(payload: KISOverseasRvseCnclRequest):
    if not validate_config():
        return kis_config_error_response("/api/v1/kis/overseas/order/rvsecncl")
    try:
        data = await market_order_rvsecncl(
            market="overseas",
            mode=payload.mode,
            orgn_odno=payload.orgn_odno,
            qty=payload.qty,
            order_price=payload.order_price,
            symbol=payload.symbol,
            exchange=payload.exchange,
        )
        await send_telegram_alert(
            "KIS OVERSEAS ORDER RVSECNCL",
            f"{payload.mode.upper()} {payload.exchange.upper()}:{payload.symbol.upper()} orgn_odno={payload.orgn_odno}",
        )
        return {"ok": True, "mode": "kis_rest", "payload": data}
    except Exception as exc:
        logger.error("FAIL: /api/v1/kis/overseas/order/rvsecncl - %s", str(exc))
        await send_telegram_alert("KIS OVERSEAS ORDER RVSECNCL FAIL", str(exc))
        return JSONResponse(status_code=502, content={"ok": False, "error": str(exc)})
