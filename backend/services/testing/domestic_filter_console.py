"""Domestic stock filter console service for test-page workflows."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Literal, Set

from ..kis.domestic import service as domestic_service
from ..stock_master import ensure_stock_master

ConditionOp = Literal["eq", "ne", "gt", "gte", "lt", "lte", "contains", "in", "between"]

TEST_ITEM_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "search.keyword",
        "name": "종목 키워드 검색",
        "description": "종목 풀(검색/직접입력) 수집",
        "implemented": True,
        "default_enabled": True,
    },
    {
        "id": "price.snapshot",
        "name": "현재가 스냅샷",
        "description": "현재가/고가/저가/거래량/거래대금 수집",
        "implemented": True,
        "default_enabled": True,
    },
    {
        "id": "orderbook.snapshot",
        "name": "호가 스냅샷",
        "description": "매도1/매수1/스프레드 수집",
        "implemented": True,
        "default_enabled": False,
    },
    {
        "id": "chart.daily",
        "name": "일봉 차트",
        "description": "일봉 기준 종가/시가/고가/저가/거래량 수집",
        "implemented": True,
        "default_enabled": False,
    },
    {
        "id": "chart.intraday",
        "name": "당일 분봉 차트",
        "description": "분봉 기준 최신 체결가/체결량 수집",
        "implemented": True,
        "default_enabled": False,
    },
    {
        "id": "news.title",
        "name": "뉴스/공시 제목",
        "description": "당일 뉴스 제목 개수 수집",
        "implemented": True,
        "default_enabled": False,
    },
    {
        "id": "condition.hts_reference",
        "name": "HTS 조건검색(참고)",
        "description": "현재 서버 미구현 참고 항목",
        "implemented": False,
        "default_enabled": False,
    },
]

CONDITION_CATALOG: List[Dict[str, Any]] = [
    {
        "key": "symbol",
        "label": "종목코드",
        "type": "string",
        "default_op": "contains",
        "ops": ["contains", "eq", "in"],
        "source": "base",
        "description": "종목코드 기준 필터",
    },
    {
        "key": "name",
        "label": "종목명",
        "type": "string",
        "default_op": "contains",
        "ops": ["contains", "eq"],
        "source": "base",
        "description": "종목명 기준 필터",
    },
    {
        "key": "price",
        "label": "현재가",
        "type": "number",
        "default_op": "gte",
        "ops": ["gt", "gte", "lt", "lte", "between", "eq"],
        "source": "price.snapshot",
        "description": "현재가",
    },
    {
        "key": "change_rate",
        "label": "등락률(%)",
        "type": "number",
        "default_op": "gte",
        "ops": ["gt", "gte", "lt", "lte", "between", "eq"],
        "source": "price.snapshot",
        "description": "전일 대비 등락률",
    },
    {
        "key": "volume",
        "label": "누적거래량",
        "type": "number",
        "default_op": "gte",
        "ops": ["gt", "gte", "lt", "lte", "between", "eq"],
        "source": "price.snapshot",
        "description": "당일 누적거래량",
    },
    {
        "key": "turnover",
        "label": "누적거래대금",
        "type": "number",
        "default_op": "gte",
        "ops": ["gt", "gte", "lt", "lte", "between", "eq"],
        "source": "price.snapshot",
        "description": "당일 누적거래대금",
    },
    {
        "key": "volatility",
        "label": "변동성(%)",
        "type": "number",
        "default_op": "gte",
        "ops": ["gt", "gte", "lt", "lte", "between", "eq"],
        "source": "price.snapshot",
        "description": "(고가-저가)/현재가*100",
    },
    {
        "key": "spread",
        "label": "호가스프레드",
        "type": "number",
        "default_op": "lte",
        "ops": ["gt", "gte", "lt", "lte", "between", "eq"],
        "source": "orderbook.snapshot",
        "description": "매도1-매수1",
    },
    {
        "key": "daily_close",
        "label": "일봉 종가",
        "type": "number",
        "default_op": "gte",
        "ops": ["gt", "gte", "lt", "lte", "between", "eq"],
        "source": "chart.daily",
        "description": "일봉 최신 종가",
    },
    {
        "key": "intraday_last",
        "label": "분봉 최신가",
        "type": "number",
        "default_op": "gte",
        "ops": ["gt", "gte", "lt", "lte", "between", "eq"],
        "source": "chart.intraday",
        "description": "분봉 최신 체결가",
    },
    {
        "key": "news_count",
        "label": "뉴스건수",
        "type": "number",
        "default_op": "gte",
        "ops": ["gt", "gte", "lt", "lte", "between", "eq"],
        "source": "news.title",
        "description": "조회 구간 뉴스 제목 개수",
    },
]

KEY_TO_TEST = {
    "price": "price.snapshot",
    "high": "price.snapshot",
    "low": "price.snapshot",
    "volume": "price.snapshot",
    "turnover": "price.snapshot",
    "change_rate": "price.snapshot",
    "volatility": "price.snapshot",
    "ask_price1": "orderbook.snapshot",
    "bid_price1": "orderbook.snapshot",
    "spread": "orderbook.snapshot",
    "daily_open": "chart.daily",
    "daily_high": "chart.daily",
    "daily_low": "chart.daily",
    "daily_close": "chart.daily",
    "daily_volume": "chart.daily",
    "intraday_last": "chart.intraday",
    "intraday_volume": "chart.intraday",
    "news_count": "news.title",
}


def get_domestic_filter_console_catalog() -> Dict[str, Any]:
    """Return test item + condition catalog for domestic filter console."""
    return {
        "ok": True,
        "test_items": TEST_ITEM_CATALOG,
        "conditions": CONDITION_CATALOG,
    }


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        text = str(value).replace(",", "").strip()
        if text == "":
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _pick_number(payload: Dict[str, Any], keys: List[str]) -> float | None:
    output = payload.get("output") if isinstance(payload, dict) else None
    if isinstance(output, dict):
        for key in keys:
            number = _to_float(output.get(key))
            if number is not None:
                return number
    for key in keys:
        number = _to_float(payload.get(key)) if isinstance(payload, dict) else None
        if number is not None:
            return number
    return None


def _match_keyword(item: Dict[str, Any], keyword: str) -> bool:
    text = keyword.strip().lower()
    if not text:
        return True
    return text in str(item.get("symbol", "")).lower() or text in str(item.get("name", "")).lower()


def _collect_candidates(keyword: str, symbols: List[str], max_candidates: int) -> List[Dict[str, str]]:
    limit = max(1, min(int(max_candidates or 1), 200))
    normalized_symbols = [str(sym).strip() for sym in symbols if str(sym).strip()]
    symbol_set = set(normalized_symbols)

    base_rows = ensure_stock_master()
    mapped = {str(row.get("symbol", "")).strip(): row for row in base_rows}

    if symbol_set:
        out: List[Dict[str, str]] = []
        for symbol in normalized_symbols:
            if symbol in mapped:
                row = mapped[symbol]
                out.append({"symbol": symbol, "name": str(row.get("name", "")), "market": str(row.get("market", ""))})
            else:
                out.append({"symbol": symbol, "name": "", "market": ""})
        return out[:limit]

    matched: List[Dict[str, str]] = []
    for row in base_rows:
        if _match_keyword(row, keyword):
            matched.append(
                {
                    "symbol": str(row.get("symbol", "")).strip(),
                    "name": str(row.get("name", "")).strip(),
                    "market": str(row.get("market", "")).strip(),
                }
            )
        if len(matched) >= limit:
            break
    return matched


def _parse_list_value(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    text = _to_text(value)
    if not text:
        return []
    return [part.strip() for part in text.split(",") if part.strip()]


def _compare_value(actual: Any, op: str, value: Any, value_to: Any) -> bool:
    op_value = str(op or "eq").lower()

    if op_value in {"contains", "eq", "ne", "in"}:
        actual_text = _to_text(actual)
        if op_value == "contains":
            return _to_text(value).lower() in actual_text.lower()
        if op_value == "eq":
            return actual_text == _to_text(value)
        if op_value == "ne":
            return actual_text != _to_text(value)
        options = _parse_list_value(value)
        return actual_text in options

    actual_number = _to_float(actual)
    left = _to_float(value)
    right = _to_float(value_to)
    if actual_number is None:
        return False

    if op_value == "gt" and left is not None:
        return actual_number > left
    if op_value == "gte" and left is not None:
        return actual_number >= left
    if op_value == "lt" and left is not None:
        return actual_number < left
    if op_value == "lte" and left is not None:
        return actual_number <= left
    if op_value == "between" and left is not None and right is not None:
        min_value = min(left, right)
        max_value = max(left, right)
        return min_value <= actual_number <= max_value
    if op_value == "eq" and left is not None:
        return actual_number == left
    return True


def _normalize_price_row(payload: Dict[str, Any]) -> Dict[str, float | None]:
    price = _pick_number(payload, ["stck_prpr", "ovrs_nmix_prpr", "last", "clos", "ckpr", "xymd_clpr"])
    high = _pick_number(payload, ["stck_hgpr", "high", "higp", "xymd_hgpr"])
    low = _pick_number(payload, ["stck_lwpr", "low", "lowp", "xymd_lwpr"])
    volume = _pick_number(payload, ["acml_vol", "vol", "xymd_vol"])
    turnover = _pick_number(payload, ["acml_tr_pbmn", "trade_amt", "xymd_tdot"])
    change_rate = _pick_number(payload, ["prdy_ctrt", "change_rate", "rate", "xymd_prdy_ctrt"])

    volatility = None
    if price is not None and price > 0 and high is not None and low is not None and high >= low:
        volatility = ((high - low) / price) * 100.0

    return {
        "price": price,
        "high": high,
        "low": low,
        "volume": volume,
        "turnover": turnover,
        "change_rate": change_rate,
        "volatility": volatility,
    }


def _normalize_orderbook_row(payload: Dict[str, Any]) -> Dict[str, float | None]:
    output = payload.get("output") if isinstance(payload, dict) else {}
    output = output if isinstance(output, dict) else {}

    ask_price1 = _to_float(output.get("askp1") or output.get("askp_rsqn1") or output.get("seln1"))
    bid_price1 = _to_float(output.get("bidp1") or output.get("bidp_rsqn1") or output.get("shnu1"))
    spread = None
    if ask_price1 is not None and bid_price1 is not None:
        spread = ask_price1 - bid_price1

    return {
        "ask_price1": ask_price1,
        "bid_price1": bid_price1,
        "spread": spread,
    }


def _normalize_daily_row(payload: Dict[str, Any]) -> Dict[str, float | None]:
    rows = payload.get("output") if isinstance(payload, dict) else []
    first = rows[0] if isinstance(rows, list) and rows else {}
    first = first if isinstance(first, dict) else {}

    return {
        "daily_open": _to_float(first.get("stck_oprc")),
        "daily_high": _to_float(first.get("stck_hgpr")),
        "daily_low": _to_float(first.get("stck_lwpr")),
        "daily_close": _to_float(first.get("stck_clpr")),
        "daily_volume": _to_float(first.get("acml_vol")),
    }


def _normalize_intraday_row(payload: Dict[str, Any]) -> Dict[str, float | None]:
    rows = payload.get("output2") if isinstance(payload, dict) else []
    first = rows[0] if isinstance(rows, list) and rows else {}
    first = first if isinstance(first, dict) else {}

    return {
        "intraday_last": _to_float(first.get("stck_prpr")),
        "intraday_volume": _to_float(first.get("cntg_vol")),
    }


def _normalize_news_row(payload: Dict[str, Any]) -> Dict[str, int]:
    rows = payload.get("output") if isinstance(payload, dict) else []
    count = len(rows) if isinstance(rows, list) else 0
    return {"news_count": count}


def _resolve_tests(selected_tests: List[str], conditions: List[Dict[str, Any]]) -> List[str]:
    valid_ids = {item["id"] for item in TEST_ITEM_CATALOG if item.get("implemented")}

    if selected_tests:
        resolved = [item for item in selected_tests if item in valid_ids]
    else:
        resolved = [item["id"] for item in TEST_ITEM_CATALOG if item.get("implemented") and item.get("default_enabled")]

    needed_from_conditions: Set[str] = set()
    for condition in conditions:
        if not condition.get("enabled", True):
            continue
        key = str(condition.get("key", "")).strip()
        test_id = KEY_TO_TEST.get(key)
        if test_id:
            needed_from_conditions.add(test_id)

    for test_id in sorted(needed_from_conditions):
        if test_id in valid_ids and test_id not in resolved:
            resolved.append(test_id)

    return resolved


def _passes_all_conditions(row: Dict[str, Any], conditions: List[Dict[str, Any]]) -> bool:
    for condition in conditions:
        if not condition.get("enabled", True):
            continue
        key = str(condition.get("key", "")).strip()
        if not key:
            continue
        op = str(condition.get("op", "eq"))
        value = condition.get("value")
        value_to = condition.get("value_to")
        actual = row.get(key)
        if not _compare_value(actual, op, value, value_to):
            return False
    return True


async def _fetch_symbol_row(symbol_item: Dict[str, Any], selected_tests: List[str], include_raw: bool) -> Dict[str, Any]:
    symbol = str(symbol_item.get("symbol", "")).strip()
    row: Dict[str, Any] = {
        "symbol": symbol,
        "name": str(symbol_item.get("name", "")).strip(),
        "market": str(symbol_item.get("market", "")).strip(),
    }
    raw_payloads: Dict[str, Any] = {}

    try:
        if "price.snapshot" in selected_tests:
            payload = await domestic_service.get_current_price(symbol)
            row.update(_normalize_price_row(payload))
            if include_raw:
                raw_payloads["price.snapshot"] = payload

        if "orderbook.snapshot" in selected_tests:
            payload = await domestic_service.get_order_book(symbol)
            row.update(_normalize_orderbook_row(payload))
            if include_raw:
                raw_payloads["orderbook.snapshot"] = payload

        if "chart.daily" in selected_tests:
            payload = await domestic_service.get_daily_chart(symbol=symbol, period_code="D", adjusted_price="1")
            row.update(_normalize_daily_row(payload))
            if include_raw:
                raw_payloads["chart.daily"] = payload

        if "chart.intraday" in selected_tests:
            payload = await domestic_service.get_intraday_chart(symbol=symbol, input_hour="153000", include_past="Y")
            row.update(_normalize_intraday_row(payload))
            if include_raw:
                raw_payloads["chart.intraday"] = payload

        if "news.title" in selected_tests:
            payload = await domestic_service.get_news_title(symbol=symbol)
            row.update(_normalize_news_row(payload))
            if include_raw:
                raw_payloads["news.title"] = payload

        if include_raw:
            row["raw"] = raw_payloads
        row["_ok"] = True
        return row
    except Exception as exc:
        return {
            "symbol": symbol,
            "name": row.get("name", ""),
            "market": row.get("market", ""),
            "_ok": False,
            "error": str(exc),
            "raw": raw_payloads if include_raw else {},
        }


async def run_domestic_filter_console(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Collect conditions, call required APIs, normalize, compute and filter rows."""
    keyword = str(payload.get("keyword", "")).strip()
    symbols = [str(sym).strip() for sym in list(payload.get("symbols") or []) if str(sym).strip()]
    limit = max(1, min(int(payload.get("limit") or 30), 200))
    max_candidates = max(1, min(int(payload.get("max_candidates") or 80), 200))
    include_raw = bool(payload.get("include_raw", True))
    include_failed_rows = bool(payload.get("include_failed_rows", False))

    conditions = [dict(item) for item in list(payload.get("conditions") or [])]
    selected_tests = _resolve_tests(list(payload.get("selected_tests") or []), conditions)

    candidates = _collect_candidates(keyword=keyword, symbols=symbols, max_candidates=max_candidates)

    if not candidates:
        return {
            "ok": True,
            "keyword": keyword,
            "selected_tests": selected_tests,
            "candidate_count": 0,
            "filtered_count": 0,
            "count": 0,
            "items": [],
            "failed_rows": [],
            "applied_conditions": conditions,
            "columns": [],
        }

    semaphore = asyncio.Semaphore(4)

    async def _bounded_fetch(item: Dict[str, Any]) -> Dict[str, Any]:
        async with semaphore:
            return await _fetch_symbol_row(item, selected_tests, include_raw)

    enriched = await asyncio.gather(*[_bounded_fetch(item) for item in candidates])

    passed_rows: List[Dict[str, Any]] = []
    failed_rows: List[Dict[str, Any]] = []
    for row in enriched:
        if not row.get("_ok"):
            failed_rows.append(row)
            continue
        if _passes_all_conditions(row, conditions):
            normalized = dict(row)
            normalized.pop("_ok", None)
            passed_rows.append(normalized)

    sorted_rows = sorted(
        passed_rows,
        key=lambda row: (
            -(_to_float(row.get("turnover")) or 0.0),
            -(_to_float(row.get("volume")) or 0.0),
            str(row.get("symbol", "")),
        ),
    )
    sliced_rows = sorted_rows[:limit]

    columns: List[str] = []
    for row in sliced_rows:
        for key in row.keys():
            if key not in columns:
                columns.append(key)

    return {
        "ok": True,
        "keyword": keyword,
        "selected_tests": selected_tests,
        "candidate_count": len(candidates),
        "filtered_count": len(passed_rows),
        "count": len(sliced_rows),
        "items": sliced_rows,
        "failed_rows": failed_rows[:100] if include_failed_rows else [],
        "applied_conditions": conditions,
        "columns": columns,
    }
