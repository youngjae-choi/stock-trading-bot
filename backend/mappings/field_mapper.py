"""Payload field flattening and Korean mapping helpers."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from .catalog.field_mappings import (
    ACCOUNT_FIELD_DESC,
    ORDER_FIELD_DESC,
    OVERSEAS_PRICE_FIELD_DESC,
    PRICE_FIELD_DESC,
    UNMAPPED_DESC,
)


def _strip_index(path: str) -> str:
    key = path.split(".")[-1]
    return re.sub(r"\[\d+\]", "", key)


def _lookup(mapping: Dict[str, str], key: str) -> Dict[str, Any]:
    value = mapping.get(key.lower()) or mapping.get(key)
    if value:
        return {"description_ko": value, "is_mapped": True}
    return {"description_ko": f"{UNMAPPED_DESC}: {key}", "is_mapped": False}


def describe_account_field(path: str) -> Dict[str, Any]:
    return _lookup(ACCOUNT_FIELD_DESC, _strip_index(path))


def describe_order_field(path: str) -> Dict[str, Any]:
    return _lookup(ORDER_FIELD_DESC, _strip_index(path))


def describe_overseas_price_field(path: str) -> Dict[str, Any]:
    key = _strip_index(path)
    value = OVERSEAS_PRICE_FIELD_DESC.get(key.lower()) or OVERSEAS_PRICE_FIELD_DESC.get(key)
    if value:
        return {"description_ko": value, "is_mapped": True}
    return {"description_ko": f"{UNMAPPED_DESC}: {key}", "is_mapped": False}


def describe_stock_field(path: str) -> Dict[str, Any]:
    key = _strip_index(path)
    if key in PRICE_FIELD_DESC:
        return {"description_ko": PRICE_FIELD_DESC[key], "is_mapped": True}

    ask_price = re.match(r"askp(\d+)$", key)
    if ask_price:
        return {"description_ko": f"매도호가 {ask_price.group(1)}단계 가격", "is_mapped": True}
    bid_price = re.match(r"bidp(\d+)$", key)
    if bid_price:
        return {"description_ko": f"매수호가 {bid_price.group(1)}단계 가격", "is_mapped": True}
    ask_qty = re.match(r"askp_rsqn(\d+)$", key)
    if ask_qty:
        return {"description_ko": f"매도잔량 {ask_qty.group(1)}단계", "is_mapped": True}
    bid_qty = re.match(r"bidp_rsqn(\d+)$", key)
    if bid_qty:
        return {"description_ko": f"매수잔량 {bid_qty.group(1)}단계", "is_mapped": True}
    ask_delta = re.match(r"askp_rsqn_icdc(\d+)$", key)
    if ask_delta:
        return {"description_ko": f"매도잔량 증감 {ask_delta.group(1)}단계", "is_mapped": True}
    bid_delta = re.match(r"bidp_rsqn_icdc(\d+)$", key)
    if bid_delta:
        return {"description_ko": f"매수잔량 증감 {bid_delta.group(1)}단계", "is_mapped": True}

    keyword_map = {
        "total_askp_rsqn": "총 매도잔량",
        "total_bidp_rsqn": "총 매수잔량",
        "ovtm_total_askp_rsqn": "시간외 총 매도잔량",
        "ovtm_total_bidp_rsqn": "시간외 총 매수잔량",
        "antc_cnpr": "예상 체결가",
        "antc_cnqn": "예상 체결량",
        "antc_vol": "예상 거래량",
        "antc_cntg_vrss": "예상체결 전일대비",
        "antc_cntg_vrss_sign": "예상체결 대비부호",
        "antc_cntg_prdy_ctrt": "예상체결 전일대비율(%)",
    }
    if key in keyword_map:
        return {"description_ko": keyword_map[key], "is_mapped": True}
    return {"description_ko": f"{UNMAPPED_DESC}: {key}", "is_mapped": False}


def _is_number_like(text: str) -> bool:
    if not text:
        return False
    return bool(re.fullmatch(r"-?\d+(\.\d+)?", text))


def _should_accounting_format(path: str) -> bool:
    key = _strip_index(path).lower()
    if any(skip in key for skip in ["code", "iscd", "odno", "date", "time", "msg", "yn", "srno"]):
        return False
    hints = [
        "amt",
        "prc",
        "prpr",
        "oprc",
        "hgpr",
        "lwpr",
        "clpr",
        "qty",
        "vol",
        "evlu",
        "loan",
        "profit",
        "pchs",
        "asst",
        "dnca",
        "nass",
        "cntg",
        "price",
        "cash",
        "last",
        "open",
        "high",
        "low",
        "diff",
        "rate",
    ]
    return any(hint in key for hint in hints)


def _format_accounting_text(path: str, value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{value:,.2f}" if isinstance(value, float) else f"{value:,}"

    text = str(value).strip()
    if not _is_number_like(text):
        return str(value)
    if not _should_accounting_format(path):
        return text
    if "." in text:
        return f"{float(text):,.4f}".rstrip("0").rstrip(".")
    return f"{int(text):,}"


def flatten_fields(payload: Any, base_path: str = "", desc_fn=None) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            next_path = f"{base_path}.{key}" if base_path else key
            rows.extend(flatten_fields(value, next_path, desc_fn))
        return rows
    if isinstance(payload, list):
        for index, value in enumerate(payload):
            next_path = f"{base_path}[{index}]"
            rows.extend(flatten_fields(value, next_path, desc_fn))
        return rows

    description_info: Dict[str, Any] = {"description_ko": "", "is_mapped": None}
    if desc_fn:
        raw_info = desc_fn(base_path or "-")
        if isinstance(raw_info, dict):
            description_info = {
                "description_ko": str(raw_info.get("description_ko", "")),
                "is_mapped": raw_info.get("is_mapped"),
            }
        else:
            description_info = {"description_ko": str(raw_info), "is_mapped": None}

    mapped_state = description_info.get("is_mapped")
    rows.append(
        {
            "field": base_path or "-",
            "description_ko": description_info.get("description_ko", ""),
            "mapping_status": "매핑" if mapped_state else ("미매핑" if mapped_state is False else ""),
            "sample_value": _format_accounting_text(base_path or "-", payload),
        }
    )
    return rows
