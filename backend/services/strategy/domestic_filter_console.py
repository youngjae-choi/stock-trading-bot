"""Domestic stock filter console service."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Tuple

from ...api.models import DomesticFilterConditionRequest, DomesticFilterConsoleRequest
from ...utils import kis_bulkhead_concurrency
from ..kis.domestic import service as domestic_service
from ..stock_master import ensure_stock_master

SUPPORTED_TESTS = {
    "price_positive": lambda row: _to_float(row.get("price")) is not None and float(row["price"]) > 0,
    "volume_positive": lambda row: _to_float(row.get("volume")) is not None and float(row["volume"]) > 0,
    "turnover_positive": lambda row: _to_float(row.get("turnover")) is not None and float(row["turnover"]) > 0,
    "change_rate_nonzero": lambda row: _to_float(row.get("change_rate")) is not None and float(row["change_rate"]) != 0,
}

_CACHE_TTL_SECONDS = 5.0
_ENRICH_CONCURRENCY_FLOOR = 2
_ENRICH_CONCURRENCY_CAP = 8
_MARKET_ALL = "ALL"
_MARKET_KOSPI = "KOSPI"
_MARKET_KOSDAQ = "KOSDAQ"
_UNIVERSE_MODE_AUTO = "auto"
_DAILY_DERIVED_KEYS = {"avg_volume_20d", "volume_ratio_20d"}
_MARKET_CAP_KEYS = ["hts_avls", "mrkt_tot_amt", "stck_avls"]
_CONDITION_KEY_ALIASES = {
    "marketcap": "market_cap",
    "market_capitalization": "market_cap",
    "market cap": "market_cap",
    "market-cap": "market_cap",
    "mkt_cap": "market_cap",
    "avg_volume20d": "avg_volume_20d",
    "avgvolume20d": "avg_volume_20d",
    "avgvolume_20d": "avg_volume_20d",
    "avg_volume_20_day": "avg_volume_20d",
    "volume_ratio20d": "volume_ratio_20d",
    "volumeratio20d": "volume_ratio_20d",
    "volumeratio_20d": "volume_ratio_20d",
    "volume_ratio_20_day": "volume_ratio_20d",
}

_PRICE_CACHE: Dict[str, Dict[str, Any]] = {}
_INFLIGHT_REQUESTS: Dict[str, asyncio.Task] = {}
_CACHE_LOCK = asyncio.Lock()


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


def _normalize_symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def _normalize_market(value: Any) -> str:
    market = str(value or _MARKET_ALL).strip().upper()
    if market in {_MARKET_KOSPI, _MARKET_KOSDAQ, _MARKET_ALL}:
        return market
    return _MARKET_ALL


def _normalize_universe_mode(value: Any) -> str:
    mode = str(value or _UNIVERSE_MODE_AUTO).strip().lower()
    if mode in {"manual", "keyword", _UNIVERSE_MODE_AUTO}:
        return mode
    if mode in {"manual_symbols", "symbols", "direct"}:
        return "manual"
    if mode in {"search", "universe", "keyword_only"}:
        return "keyword"
    return _UNIVERSE_MODE_AUTO


def _stock_master_index() -> Dict[str, Dict[str, str]]:
    return {item["symbol"]: item for item in ensure_stock_master()}


def _rows_for_symbols(symbols: List[str]) -> List[Dict[str, str]]:
    mapped = _stock_master_index()
    rows: List[Dict[str, str]] = []
    for symbol in symbols:
        safe_symbol = _normalize_symbol(symbol)
        if not safe_symbol:
            continue
        hit = mapped.get(safe_symbol)
        if hit:
            rows.append({"symbol": hit["symbol"], "name": hit["name"], "market": hit["market"]})
        else:
            rows.append({"symbol": safe_symbol, "name": safe_symbol, "market": "UNKNOWN"})
    return rows


def _rows_for_keyword(keyword: str) -> List[Dict[str, str]]:
    text = str(keyword or "").strip().lower()
    items = ensure_stock_master()
    if not text:
        return [{"symbol": item["symbol"], "name": item["name"], "market": item["market"]} for item in items]
    return [
        {"symbol": item["symbol"], "name": item["name"], "market": item["market"]}
        for item in items
        if text in item["symbol"].lower() or text in item["name"].lower()
    ]


def _filter_rows_by_market(rows: List[Dict[str, str]], market: str) -> List[Dict[str, str]]:
    safe_market = _normalize_market(market)
    if safe_market == _MARKET_ALL:
        return rows
    return [item for item in rows if str(item.get("market") or "").strip().upper() == safe_market]


def _is_domestic_equity_symbol(symbol: str) -> bool:
    # KRX common stock symbols are typically 6-digit numeric strings.
    safe = _normalize_symbol(symbol)
    return len(safe) == 6 and safe.isdigit()


def _merge_universe(
    keyword: str,
    symbols: List[str],
    max_candidates: int,
    market: str,
    universe_mode: str,
) -> List[Dict[str, str]]:
    # Keep direct symbols first, then keyword universe rows.
    direct_rows = _rows_for_symbols(symbols)
    keyword_rows = _rows_for_keyword(keyword)

    safe_mode = _normalize_universe_mode(universe_mode)
    if safe_mode == "manual":
        source_rows = direct_rows
    elif safe_mode == "keyword":
        source_rows = keyword_rows
    else:
        source_rows = [*direct_rows, *keyword_rows]

    market_filtered = _filter_rows_by_market(source_rows, market)
    if safe_mode != "manual":
        market_filtered = [item for item in market_filtered if _is_domestic_equity_symbol(item.get("symbol", ""))]

    limit = max(1, min(int(max_candidates or 1), 200))
    merged: List[Dict[str, str]] = []
    seen: set[str] = set()

    for row in market_filtered:
        symbol = _normalize_symbol(row.get("symbol"))
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        merged.append({
            "symbol": symbol,
            "name": str(row.get("name") or symbol),
            "market": str(row.get("market") or "UNKNOWN"),
        })
        if len(merged) >= limit:
            break

    return merged


def _pick_first_number(payload: Dict[str, Any], keys: List[str]) -> float | None:
    output = payload.get("output") if isinstance(payload, dict) else {}
    output = output if isinstance(output, dict) else {}
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


def _extract_daily_metrics(payload: Dict[str, Any], current_volume: float | None) -> Dict[str, float | None]:
    rows = payload.get("output") if isinstance(payload, dict) else []
    rows = rows if isinstance(rows, list) else []

    volumes: List[float] = []
    for row in rows[:20]:
        if not isinstance(row, dict):
            continue
        volume = _to_float(row.get("acml_vol"))
        if volume is not None:
            volumes.append(volume)

    avg_volume_20d = (sum(volumes) / len(volumes)) if volumes else None
    volume_ratio_20d = None
    if current_volume is not None and avg_volume_20d not in {None, 0}:
        volume_ratio_20d = (current_volume / avg_volume_20d) * 100.0

    return {
        "avg_volume_20d": avg_volume_20d,
        "volume_ratio_20d": volume_ratio_20d,
    }


def _extract_metrics(payload: Dict[str, Any]) -> Dict[str, Any]:
    output = payload.get("output") if isinstance(payload, dict) else {}
    output = output if isinstance(output, dict) else {}
    return {
        "price": _to_float(output.get("stck_prpr")),
        "volume": _to_float(output.get("acml_vol")),
        "turnover": _to_float(output.get("acml_tr_pbmn")),
        "change_rate": _to_float(output.get("prdy_ctrt")),
        "market_cap": _pick_first_number(payload, _MARKET_CAP_KEYS),
    }


def _resolve_value(row: Dict[str, Any], key: str) -> Any:
    resolved_key = _normalize_condition_key(key)
    return row.get(resolved_key)


def _normalize_text(value: Any) -> str:
    return str(value).strip().lower()


def _normalize_condition_key(value: Any) -> str:
    key = str(value or "").strip().lower()
    if not key:
        return ""
    return _CONDITION_KEY_ALIASES.get(key, key)


def _evaluate_condition(row: Dict[str, Any], condition: DomesticFilterConditionRequest) -> bool:
    if not condition.enabled:
        return True

    normalized_key = _normalize_condition_key(condition.key)
    if not normalized_key:
        return False

    left = _resolve_value(row, normalized_key)
    op = condition.op.strip().lower()
    right = condition.value
    right_to = condition.value_to

    if op == "contains":
        return _normalize_text(right) in _normalize_text(left)
    if op == "in":
        values = right if isinstance(right, list) else str(right).split(",")
        normalized = {_normalize_text(item) for item in values}
        return _normalize_text(left) in normalized
    if op == "between":
        left_num = _to_float(left)
        min_num = _to_float(right)
        max_num = _to_float(right_to)
        if left_num is None or min_num is None or max_num is None:
            return False
        lo, hi = sorted([min_num, max_num])
        return lo <= left_num <= hi

    left_num = _to_float(left)
    right_num = _to_float(right)
    if op in {"gt", "gte", "lt", "lte"}:
        if left_num is None or right_num is None:
            return False
        if op == "gt":
            return left_num > right_num
        if op == "gte":
            return left_num >= right_num
        if op == "lt":
            return left_num < right_num
        return left_num <= right_num

    if op == "eq":
        if left_num is not None and right_num is not None:
            return left_num == right_num
        return str(left) == str(right)
    if op == "ne":
        if left_num is not None and right_num is not None:
            return left_num != right_num
        return str(left) != str(right)

    return False


async def _fetch_price_cached(symbol: str) -> Tuple[Dict[str, Any], bool]:
    now = time.monotonic()
    async with _CACHE_LOCK:
        cached = _PRICE_CACHE.get(symbol)
        if cached and cached.get("expires_at", 0.0) > now:
            return cached["payload"], True

        in_flight = _INFLIGHT_REQUESTS.get(symbol)
        if in_flight is None:
            in_flight = asyncio.create_task(domestic_service.get_current_price(symbol))
            _INFLIGHT_REQUESTS[symbol] = in_flight

    try:
        payload = await in_flight
    finally:
        async with _CACHE_LOCK:
            if _INFLIGHT_REQUESTS.get(symbol) is in_flight:
                _INFLIGHT_REQUESTS.pop(symbol, None)

    async with _CACHE_LOCK:
        _PRICE_CACHE[symbol] = {
            "payload": payload,
            "expires_at": time.monotonic() + _CACHE_TTL_SECONDS,
        }

    return payload, False


async def _enrich_row(item: Dict[str, str], include_raw: bool, include_daily_metrics: bool) -> Dict[str, Any]:
    symbol = item["symbol"]
    try:
        payload, cache_hit = await _fetch_price_cached(symbol)
        metrics = _extract_metrics(payload)
        row: Dict[str, Any] = {
            "symbol": item["symbol"],
            "name": item["name"],
            "market": item["market"],
            **metrics,
            "cache_hit": cache_hit,
        }

        if include_daily_metrics:
            daily_payload = await domestic_service.get_daily_chart(symbol=symbol, period_code="D", adjusted_price="1")
            row.update(_extract_daily_metrics(daily_payload, metrics.get("volume")))

        if include_raw:
            row["raw"] = payload
        return {"ok": True, "row": row}
    except Exception as exc:
        return {"ok": False, "symbol": symbol, "reason": str(exc)}


def _collect_display_columns(
    selected_tests: List[str],
    conditions: List[DomesticFilterConditionRequest],
) -> List[str]:
    columns = ["symbol", "name"]
    for condition in conditions:
        if not condition.enabled:
            continue
        key = _normalize_condition_key(condition.key)
        if key and key not in columns:
            columns.append(key)
    for test_name in selected_tests:
        test_column = f"test_{test_name}"
        if test_column not in columns:
            columns.append(test_column)
    return columns


def _needs_daily_metrics(conditions: List[DomesticFilterConditionRequest]) -> bool:
    enabled_keys = {_normalize_condition_key(item.key) for item in conditions if item.enabled}
    return bool(enabled_keys.intersection(_DAILY_DERIVED_KEYS))


def _evaluate_row(
    row: Dict[str, Any],
    selected_tests: List[str],
    conditions: List[DomesticFilterConditionRequest],
) -> Tuple[bool, Dict[str, Any]]:
    test_result: Dict[str, bool] = {}
    for test_name in selected_tests:
        test_fn = SUPPORTED_TESTS.get(test_name)
        if test_fn:
            test_result[f"test_{test_name}"] = bool(test_fn(row))

    condition_result: Dict[str, bool] = {}
    for index, condition in enumerate(conditions):
        if not condition.enabled:
            continue
        passed = _evaluate_condition(row, condition)
        condition_result[f"condition_{index + 1}"] = passed

    # If there is no effective filter, keep the row (browse mode).
    has_effective_filter = bool(test_result) or bool(condition_result)
    if not has_effective_filter:
        overall_pass = True
    else:
        # AND engine: all selected tests and enabled conditions must pass.
        overall_pass = all(test_result.values()) and all(condition_result.values())
    merged = {**row, **test_result, **condition_result, "overall_pass": overall_pass}
    return overall_pass, merged


async def run_domestic_filter_console(payload: DomesticFilterConsoleRequest) -> Dict[str, Any]:
    """Run domestic stock filter console with universe merge, AND filters, cache, and concurrency limits."""
    direct_symbols = [*payload.manual_symbols, *payload.symbols]
    effective_market = _normalize_market(payload.market)
    requested_max_candidates = payload.top_n if payload.top_n is not None else payload.max_candidates

    layered_conditions = [*payload.universe_filters, *payload.timing_filters, *payload.change_filters]
    use_legacy_conditions = len(payload.conditions) > 0
    effective_conditions = payload.conditions if use_legacy_conditions else layered_conditions

    strategy_layers = {
        "source": "conditions" if use_legacy_conditions else "layered",
        "universe": {
            "condition_count": len(payload.universe_filters),
            "enabled_condition_count": len([item for item in payload.universe_filters if item.enabled]),
        },
        "timing": {
            "condition_count": len(payload.timing_filters),
            "enabled_condition_count": len([item for item in payload.timing_filters if item.enabled]),
        },
        "change": {
            "condition_count": len(payload.change_filters),
            "enabled_condition_count": len([item for item in payload.change_filters if item.enabled]),
        },
        "merged_count": len(effective_conditions),
        "enabled_merged_count": len([item for item in effective_conditions if item.enabled]),
    }

    include_daily_metrics = _needs_daily_metrics(effective_conditions)
    effective_max_candidates = int(requested_max_candidates or 1)
    if include_daily_metrics:
        effective_max_candidates = min(effective_max_candidates, 30)

    candidates = _merge_universe(
        keyword=payload.keyword,
        symbols=direct_symbols,
        max_candidates=effective_max_candidates,
        market=effective_market,
        universe_mode=payload.universe_mode or _UNIVERSE_MODE_AUTO,
    )
    display_columns = _collect_display_columns(payload.selected_tests, effective_conditions)

    safe_limit = max(1, min(int(payload.limit or 1), 200))
    base_concurrency = max(1, int(kis_bulkhead_concurrency() or 1))
    concurrency = min(_ENRICH_CONCURRENCY_CAP, max(_ENRICH_CONCURRENCY_FLOOR, base_concurrency))

    semaphore = asyncio.Semaphore(concurrency)

    async def _bounded_enrich(item: Dict[str, str]) -> Dict[str, Any]:
        async with semaphore:
            return await _enrich_row(item, payload.include_raw, include_daily_metrics)

    enriched: List[Dict[str, Any]] = []
    if candidates:
        enriched = await asyncio.gather(*[_bounded_enrich(item) for item in candidates])

    failed_rows = [row for row in enriched if not row.get("ok")]
    enriched_rows = [row.get("row", {}) for row in enriched if row.get("ok")]

    evaluated: List[Dict[str, Any]] = []
    passed_count = 0
    cache_hit_count = 0

    for row in enriched_rows:
        if row.get("cache_hit"):
            cache_hit_count += 1

        passed, merged = _evaluate_row(row, payload.selected_tests, effective_conditions)
        if passed:
            passed_count += 1
        if payload.include_failed_rows or passed:
            evaluated.append(merged)

    limited_rows = evaluated[:safe_limit]

    return {
        "ok": True,
        "keyword": payload.keyword,
        "symbols": payload.symbols,
        "manual_symbols": payload.manual_symbols,
        "universe_mode": _normalize_universe_mode(payload.universe_mode),
        "market": effective_market,
        "top_n": payload.top_n,
        "max_candidates": int(requested_max_candidates or 1),
        "applied_max_candidates": int(effective_max_candidates),
        "candidate_count": len(candidates),
        "enriched_success_count": len(enriched_rows),
        "enriched_fail_count": len(failed_rows),
        "selected_test_count": len(payload.selected_tests),
        "selected_condition_count": len([item for item in effective_conditions if item.enabled]),
        "strategy_layers": strategy_layers,
        "passed_count": passed_count,
        "count": len(limited_rows),
        "display_columns": display_columns,
        "items": limited_rows,
        "failed_items": failed_rows[:50],
        "cache": {
            "ttl_seconds": _CACHE_TTL_SECONDS,
            "hit_count": cache_hit_count,
            "miss_count": max(0, len(enriched_rows) - cache_hit_count),
        },
        "concurrency": {
            "requested_bulkhead": base_concurrency,
            "applied_limit": concurrency,
        },
    }
