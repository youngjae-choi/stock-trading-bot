"""Strategy setting + keyword search/filter routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ...config import validate_config
from ...services.strategy.domestic_filter_console import run_domestic_filter_console
from ...services.strategy.investor_buy_leaders import get_investor_buy_leaders
from ...services.strategy.filter_mapping import build_filter_mapping
from ...services.strategy.pipeline import run_search_filter_pipeline
from ..dependencies import kis_config_error_response
from ..models import DomesticFilterConsoleRequest, StrategyParamSchema, StrategySearchFilterRequest

logger = logging.getLogger("BackendStrategyAPI")
router = APIRouter(prefix="/api/v1/kis/strategy", tags=["kis-strategy"])


@router.get("/schema")
async def get_strategy_schema():
    return {
        "ok": True,
        "schema": StrategyParamSchema.model_json_schema(),
        "example": StrategyParamSchema().model_dump(),
    }


@router.post("/mapping")
async def get_strategy_mapping(payload: StrategyParamSchema):
    strategy_data = payload.model_dump()
    return {
        "ok": True,
        "strategy": strategy_data,
        "mapping": build_filter_mapping(strategy_data),
    }


@router.post("/search-filter")
async def search_with_filters(payload: StrategySearchFilterRequest):
    try:
        strategy_data = payload.strategy.model_dump()
        strategy_data["limit"] = int(strategy_data.get("limit") or payload.strategy.limit)
        result = await run_search_filter_pipeline(
            keyword=payload.keyword,
            market=payload.market,
            strategy=strategy_data,
            max_candidates=payload.max_candidates,
        )
        result["mapping"] = build_filter_mapping({"keyword": payload.keyword, **strategy_data, "market": payload.market})
        return result
    except Exception as exc:
        logger.error("FAIL: /api/v1/kis/strategy/search-filter - %s", str(exc))
        return JSONResponse(status_code=502, content={"ok": False, "error": str(exc)})


@router.post("/domestic-filter/console")
async def domestic_filter_console(payload: DomesticFilterConsoleRequest):
    try:
        return await run_domestic_filter_console(payload)
    except Exception as exc:
        logger.error("FAIL: /api/v1/kis/strategy/domestic-filter/console - %s", str(exc))
        return JSONResponse(status_code=502, content={"ok": False, "error": str(exc)})


@router.get("/investor-buy-leaders")
async def get_investor_leaders(
    subject: str = "all",
    market: str = "all",
    sort_by: str = "net_buy_amount",
    order: str = "desc",
    limit: int = 30,
    max_candidates: int = 60,
    include_non_positive: bool = False,
):
    if not validate_config():
        return kis_config_error_response("/api/v1/kis/strategy/investor-buy-leaders")

    safe_subject = str(subject or "all").strip().lower()
    if safe_subject not in {"foreign", "institution", "individual", "all"}:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "subject must be one of foreign/institution/individual/all"},
        )

    safe_sort_by = str(sort_by or "net_buy_amount").strip().lower()
    if safe_sort_by not in {"net_buy_qty", "net_buy_amount", "buy_strength", "turnover"}:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "sort_by must be one of net_buy_qty/net_buy_amount/buy_strength/turnover"},
        )

    safe_order = str(order or "desc").strip().lower()
    if safe_order not in {"asc", "desc"}:
        return JSONResponse(status_code=400, content={"ok": False, "error": "order must be asc/desc"})

    safe_limit = max(1, min(int(limit), 100))
    safe_candidates = max(1, min(int(max_candidates), 120))
    try:
        return await get_investor_buy_leaders(
            subject=safe_subject,  # type: ignore[arg-type]
            market=market,
            sort_by=safe_sort_by,  # type: ignore[arg-type]
            order=safe_order,  # type: ignore[arg-type]
            limit=safe_limit,
            max_candidates=safe_candidates,
            include_non_positive=bool(include_non_positive),
        )
    except Exception as exc:
        logger.error("FAIL: /api/v1/kis/strategy/investor-buy-leaders - %s", str(exc))
        return JSONResponse(status_code=502, content={"ok": False, "error": str(exc)})
