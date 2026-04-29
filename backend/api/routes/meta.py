"""Metadata and field-mapping routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ...config import settings, validate_config
from ...mappings.catalog.scope_catalog import KIS_API_SCOPE_CATALOG, STOCK_FILTER_CATALOG
from ...mappings.field_mapper import (
    describe_account_field,
    describe_overseas_price_field,
    describe_stock_field,
    flatten_fields,
)
from ...services.kis.common.market_interface import get_price
from ...services.kis.domestic import service as domestic_service
from ...services.stock_master import ensure_stock_master
from ..dependencies import kis_config_error_response

logger = logging.getLogger("BackendMetaAPI")
router = APIRouter(prefix="/api/v1/kis/meta", tags=["kis-meta"])


@router.get("/capabilities")
async def get_kis_capabilities():
    mode = "demo" if "openapivts" in settings.KIS_URL.lower() else "real"
    domestic_rows = [row for row in KIS_API_SCOPE_CATALOG if row.get("market_scope") == "domestic"]
    overseas_rows = [row for row in KIS_API_SCOPE_CATALOG if row.get("market_scope") == "overseas"]
    return {
        "ok": True,
        "connection_mode": mode,
        "direct_rest": True,
        "requires_local_hts": False,
        "capabilities": [
            {"group": "조회", "feature": "계좌 잔고/보유종목 조회", "implemented_in_server": True},
            {"group": "조회", "feature": "국내 현재가/호가", "implemented_in_server": True},
            {"group": "조회", "feature": "해외 현재가/차트", "implemented_in_server": True},
            {"group": "주문", "feature": "국내/해외 매수·매도", "implemented_in_server": True},
            {"group": "주문", "feature": "국내/해외 정정·취소", "implemented_in_server": True},
            {"group": "실시간", "feature": "체결통보(WebSocket)", "implemented_in_server": False},
        ],
        "notes": [
            "현재 서버는 KIS REST API를 직접 호출하며 HTS 설치/제어를 요구하지 않습니다.",
            "선물옵션 기능은 범위에서 제외합니다.",
        ],
        "market_scope_summary": {
            "domestic_count": len(domestic_rows),
            "overseas_count": len(overseas_rows),
            "domestic_implemented": len([row for row in domestic_rows if row.get("status") == "implemented"]),
            "overseas_implemented": len([row for row in overseas_rows if row.get("status") == "implemented"]),
        },
    }


@router.get("/trading-scope")
async def get_kis_trading_scope():
    domestic_rows = [row for row in KIS_API_SCOPE_CATALOG if row.get("market_scope") == "domestic"]
    overseas_rows = [row for row in KIS_API_SCOPE_CATALOG if row.get("market_scope") == "overseas"]
    return {
        "ok": True,
        "excluded": ["futures", "options"],
        "count": len(KIS_API_SCOPE_CATALOG),
        "items": KIS_API_SCOPE_CATALOG,
        "groups": {
            "domestic": {"count": len(domestic_rows), "items": domestic_rows},
            "overseas": {"count": len(overseas_rows), "items": overseas_rows},
        },
    }


@router.get("/stock-filters")
async def get_stock_filters():
    domestic_items = [item for item in STOCK_FILTER_CATALOG if item.get("market_scope") == "domestic"]
    overseas_items = [item for item in STOCK_FILTER_CATALOG if item.get("market_scope") == "overseas"]
    return {
        "ok": True,
        "count": len(STOCK_FILTER_CATALOG),
        "items": STOCK_FILTER_CATALOG,
        "groups": {
            "domestic": {"count": len(domestic_items), "items": domestic_items},
            "overseas": {"count": len(overseas_items), "items": overseas_items},
        },
    }


@router.get("/stocks/search")
async def search_stocks(keyword: str, limit: int = 30):
    text = keyword.strip()
    if not text:
        return {"ok": True, "count": 0, "items": []}

    items = ensure_stock_master()
    lowered = text.lower()
    matched = [item for item in items if lowered in item["name"].lower() or lowered in item["symbol"].lower()]
    limited = matched[: max(1, min(limit, 200))]
    return {"ok": True, "count": len(limited), "items": limited}


@router.get("/account-fields")
async def get_account_fields():
    if not validate_config():
        return kis_config_error_response("/api/v1/kis/meta/account-fields")
    try:
        payload = await domestic_service.get_balance()
        fields = flatten_fields(payload, desc_fn=describe_account_field)
        return {"ok": True, "count": len(fields), "fields": fields, "payload": payload}
    except Exception as exc:
        logger.error("FAIL: /api/v1/kis/meta/account-fields - %s", str(exc))
        return JSONResponse(status_code=502, content={"ok": False, "error": str(exc)})


@router.get("/stock-fields/{symbol}")
async def get_stock_fields(symbol: str):
    if not validate_config():
        return kis_config_error_response(f"/api/v1/kis/meta/stock-fields/{symbol}")
    try:
        price_payload = await domestic_service.get_current_price(symbol)
        orderbook_payload = await domestic_service.get_order_book(symbol)
        price_fields = flatten_fields(price_payload, desc_fn=describe_stock_field)
        orderbook_fields = flatten_fields(orderbook_payload, desc_fn=describe_stock_field)
        return {
            "ok": True,
            "symbol": symbol,
            "price_field_count": len(price_fields),
            "orderbook_field_count": len(orderbook_fields),
            "price_fields": price_fields,
            "orderbook_fields": orderbook_fields,
            "price_payload": price_payload,
            "orderbook_payload": orderbook_payload,
        }
    except Exception as exc:
        logger.error("FAIL: /api/v1/kis/meta/stock-fields/%s - %s", symbol, str(exc))
        return JSONResponse(status_code=502, content={"ok": False, "error": str(exc)})


@router.get("/overseas-fields/{exchange}/{symbol}")
async def get_overseas_fields(exchange: str, symbol: str):
    if not validate_config():
        return kis_config_error_response(f"/api/v1/kis/meta/overseas-fields/{exchange}/{symbol}")
    try:
        payload = await get_price(market="overseas", exchange=exchange, symbol=symbol)
        fields = flatten_fields(payload, desc_fn=describe_overseas_price_field)
        return {
            "ok": True,
            "exchange": exchange.upper(),
            "symbol": symbol.upper(),
            "count": len(fields),
            "fields": fields,
            "payload": payload,
        }
    except Exception as exc:
        logger.error("FAIL: /api/v1/kis/meta/overseas-fields/%s/%s - %s", exchange, symbol, str(exc))
        return JSONResponse(status_code=502, content={"ok": False, "error": str(exc)})
