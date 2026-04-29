"""Keyword search + strategy filter pipeline for domestic/overseas stocks."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Literal

from ..kis.common.market_interface import get_price as get_market_price
from ..stock_master import ensure_stock_master

MarketType = Literal["domestic", "overseas", "all"]

OVERSEAS_UNIVERSE = [
    {"symbol": "AAPL", "name": "Apple", "market": "NASDAQ", "exchange": "NASD"},
    {"symbol": "MSFT", "name": "Microsoft", "market": "NASDAQ", "exchange": "NASD"},
    {"symbol": "NVDA", "name": "NVIDIA", "market": "NASDAQ", "exchange": "NASD"},
    {"symbol": "AMZN", "name": "Amazon", "market": "NASDAQ", "exchange": "NASD"},
    {"symbol": "TSLA", "name": "Tesla", "market": "NASDAQ", "exchange": "NASD"},
    {"symbol": "META", "name": "Meta", "market": "NASDAQ", "exchange": "NASD"},
    {"symbol": "GOOGL", "name": "Alphabet", "market": "NASDAQ", "exchange": "NASD"},
    {"symbol": "BRK.B", "name": "Berkshire Hathaway", "market": "NYSE", "exchange": "NYSE"},
    {"symbol": "JPM", "name": "JPMorgan", "market": "NYSE", "exchange": "NYSE"},
]


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        text = str(value).replace(",", "").strip()
        if not text:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _pick_first_number(payload: Dict[str, Any], keys: List[str]) -> float | None:
    output = payload.get("output") if isinstance(payload, dict) else None
    if isinstance(output, dict):
        for key in keys:
            if key in output:
                value = _to_float(output.get(key))
                if value is not None:
                    return value
    for key in keys:
        value = _to_float(payload.get(key)) if isinstance(payload, dict) else None
        if value is not None:
            return value
    return None


def _compute_metrics(raw_payload: Dict[str, Any]) -> Dict[str, float | None]:
    price = _pick_first_number(raw_payload, ["stck_prpr", "last", "clos", "ovrs_nmix_prpr", "ckpr", "xymd_clpr"])
    high = _pick_first_number(raw_payload, ["stck_hgpr", "high", "higp", "ovrs_nmix_hgpr", "xymd_hgpr"])
    low = _pick_first_number(raw_payload, ["stck_lwpr", "low", "lowp", "ovrs_nmix_lwpr", "xymd_lwpr"])
    volume = _pick_first_number(raw_payload, ["acml_vol", "tvol", "evol", "vol", "xymd_vol"])
    turnover = _pick_first_number(raw_payload, ["acml_tr_pbmn", "tamt", "xymd_tdot", "trade_amt"])

    volatility = None
    if price and price > 0 and high is not None and low is not None and high >= low:
        volatility = ((high - low) / price) * 100.0

    return {
        "price": price,
        "high": high,
        "low": low,
        "volume": volume,
        "turnover": turnover,
        "volatility": volatility,
    }


def _match_keyword(item: Dict[str, Any], keyword: str) -> bool:
    if not keyword.strip():
        return True
    lowered = keyword.lower().strip()
    return lowered in str(item.get("name", "")).lower() or lowered in str(item.get("symbol", "")).lower()


def _build_universe(*, market: MarketType, keyword: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if market in {"domestic", "all"}:
        for item in ensure_stock_master():
            if _match_keyword(item, keyword):
                rows.append({"market_scope": "domestic", "symbol": item.get("symbol"), "name": item.get("name"), "exchange": "KRX"})
    if market in {"overseas", "all"}:
        for item in OVERSEAS_UNIVERSE:
            if _match_keyword(item, keyword):
                rows.append({"market_scope": "overseas", "symbol": item.get("symbol"), "name": item.get("name"), "exchange": item.get("exchange")})
    return rows


def _passes_filters(metrics: Dict[str, float | None], strategy: Dict[str, Any]) -> bool:
    checks = [
        ("price_min", lambda v: metrics.get("price") is not None and metrics["price"] >= float(v)),
        ("price_max", lambda v: metrics.get("price") is not None and metrics["price"] <= float(v)),
        ("volume_min", lambda v: metrics.get("volume") is not None and metrics["volume"] >= float(v)),
        ("volume_max", lambda v: metrics.get("volume") is not None and metrics["volume"] <= float(v)),
        ("min_turnover", lambda v: metrics.get("turnover") is not None and metrics["turnover"] >= float(v)),
        ("volatility_min", lambda v: metrics.get("volatility") is not None and metrics["volatility"] >= float(v)),
        ("volatility_max", lambda v: metrics.get("volatility") is not None and metrics["volatility"] <= float(v)),
    ]
    for key, fn in checks:
        value = strategy.get(key)
        if value not in (None, "", 0):
            if not fn(value):
                return False
    return True


async def _enrich_item(item: Dict[str, Any]) -> Dict[str, Any]:
    market_scope = item.get("market_scope")
    symbol = str(item.get("symbol", ""))
    exchange = str(item.get("exchange", ""))
    try:
        if market_scope == "domestic":
            payload = await get_market_price(market="domestic", symbol=symbol)
        else:
            payload = await get_market_price(market="overseas", exchange=exchange, symbol=symbol)
        metrics = _compute_metrics(payload if isinstance(payload, dict) else {})
        return {"ok": True, "item": item, "metrics": metrics, "raw": payload}
    except Exception as exc:
        return {"ok": False, "item": item, "error": str(exc)}


async def run_search_filter_pipeline(
    *,
    keyword: str,
    market: MarketType,
    strategy: Dict[str, Any],
    max_candidates: int = 30,
) -> Dict[str, Any]:
    """Search symbols by keyword and apply strategy filters using live quote enrichments."""
    limit = int(strategy.get("limit") or 20)
    universe = _build_universe(market=market, keyword=keyword)
    candidates = universe[: max(1, min(max_candidates, 100))]

    enriched = await asyncio.gather(*[_enrich_item(item) for item in candidates]) if candidates else []

    passed: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []
    for row in enriched:
        item = row.get("item", {})
        if not row.get("ok"):
            failed.append({"symbol": item.get("symbol"), "market_scope": item.get("market_scope"), "reason": row.get("error", "unknown")})
            continue
        metrics = row.get("metrics", {})
        if _passes_filters(metrics, strategy):
            passed.append(
                {
                    "symbol": item.get("symbol"),
                    "name": item.get("name"),
                    "market_scope": item.get("market_scope"),
                    "exchange": item.get("exchange"),
                    "metrics": metrics,
                }
            )

    sorted_passed = sorted(
        passed,
        key=lambda x: (
            -(x.get("metrics", {}).get("turnover") or 0.0),
            -(x.get("metrics", {}).get("volume") or 0.0),
        ),
    )

    return {
        "ok": True,
        "keyword": keyword,
        "market": market,
        "candidate_count": len(candidates),
        "enriched_fail_count": len(failed),
        "strategy_applied": strategy,
        "count": min(limit, len(sorted_passed)),
        "items": sorted_passed[:limit],
        "failed_items": failed[:50],
    }
