"""Investor-subject buy-leader ranking service built from KIS raw APIs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal

from ..kis.domestic import service as domestic_service
from ..stock_master import ensure_stock_master

InvestorType = Literal["foreign", "institution", "individual", "all"]
MarketFilter = Literal["all", "KOSPI", "KOSDAQ", "KONEX"]
SortKey = Literal["net_buy_qty", "net_buy_amount", "buy_strength", "turnover"]
SortOrder = Literal["desc", "asc"]

BUY_STRENGTH_FORMULA_PRIMARY = "buy_strength = (subject_net_buy_qty / acml_vol) * 100"
BUY_STRENGTH_FORMULA_FALLBACK = "buy_strength = (subject_net_buy_qty / (subject_buy_vol + subject_sell_vol)) * 100"


@dataclass(frozen=True)
class SubjectFields:
    subject: Literal["foreign", "institution", "individual"]
    label_ko: str
    net_buy_qty: str
    net_buy_amount: str
    buy_vol: str
    sell_vol: str


SUBJECT_FIELD_MAP: Dict[str, SubjectFields] = {
    "foreign": SubjectFields(
        subject="foreign",
        label_ko="외국인",
        net_buy_qty="frgn_ntby_qty",
        net_buy_amount="frgn_ntby_tr_pbmn",
        buy_vol="frgn_shnu_vol",
        sell_vol="frgn_seln_vol",
    ),
    "institution": SubjectFields(
        subject="institution",
        label_ko="기관",
        net_buy_qty="orgn_ntby_qty",
        net_buy_amount="orgn_ntby_tr_pbmn",
        buy_vol="orgn_shnu_vol",
        sell_vol="orgn_seln_vol",
    ),
    "individual": SubjectFields(
        subject="individual",
        label_ko="개인",
        net_buy_qty="prsn_ntby_qty",
        net_buy_amount="prsn_ntby_tr_pbmn",
        buy_vol="prsn_shnu_vol",
        sell_vol="prsn_seln_vol",
    ),
}


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


def _to_int(value: Any) -> int | None:
    number = _to_float(value)
    if number is None:
        return None
    return int(number)


def _pick_first_output_row(payload: Dict[str, Any]) -> Dict[str, Any]:
    output = payload.get("output")
    if isinstance(output, list) and output:
        return output[0] if isinstance(output[0], dict) else {}
    if isinstance(output, dict):
        return output
    return {}


def _normalize_market_filter(market: str) -> MarketFilter:
    text = str(market or "all").strip().upper()
    if text in {"KOSPI", "KOSDAQ", "KONEX"}:
        return text
    return "all"


def _resolve_subjects(subject: InvestorType) -> List[SubjectFields]:
    if subject == "all":
        return [SUBJECT_FIELD_MAP["foreign"], SUBJECT_FIELD_MAP["institution"], SUBJECT_FIELD_MAP["individual"]]
    return [SUBJECT_FIELD_MAP[subject]]


def _compute_buy_strength(
    *,
    net_buy_qty: int | None,
    total_volume: int | None,
    buy_volume: int | None,
    sell_volume: int | None,
) -> Dict[str, Any]:
    if net_buy_qty is None:
        return {
            "value": None,
            "status": "unavailable",
            "reason": "net_buy_qty_missing",
            "formula": BUY_STRENGTH_FORMULA_PRIMARY,
            "formula_applied": "",
            "denominator_field": "acml_vol",
            "denominator_value": None,
        }

    if total_volume and total_volume > 0:
        value = (float(net_buy_qty) / float(total_volume)) * 100.0
        return {
            "value": round(value, 6),
            "status": "computed",
            "reason": "ok",
            "formula": BUY_STRENGTH_FORMULA_PRIMARY,
            "formula_applied": BUY_STRENGTH_FORMULA_PRIMARY,
            "denominator_field": "acml_vol",
            "denominator_value": total_volume,
        }

    if (buy_volume is not None) and (sell_volume is not None):
        synthetic = buy_volume + sell_volume
        if synthetic > 0:
            value = (float(net_buy_qty) / float(synthetic)) * 100.0
            return {
                "value": round(value, 6),
                "status": "fallback",
                "reason": "acml_vol_missing_used_subject_buy_sell_sum",
                "formula": BUY_STRENGTH_FORMULA_PRIMARY,
                "formula_applied": BUY_STRENGTH_FORMULA_FALLBACK,
                "denominator_field": "subject_buy_vol+subject_sell_vol",
                "denominator_value": synthetic,
            }

    return {
        "value": None,
        "status": "unavailable",
        "reason": "denominator_missing_or_zero",
        "formula": BUY_STRENGTH_FORMULA_PRIMARY,
        "formula_applied": "",
        "denominator_field": "acml_vol",
        "denominator_value": None,
    }


def _build_item(
    *,
    stock: Dict[str, str],
    subject_fields: SubjectFields,
    investor_row: Dict[str, Any],
    quote_row: Dict[str, Any],
) -> Dict[str, Any]:
    net_buy_qty = _to_int(investor_row.get(subject_fields.net_buy_qty))
    net_buy_amount = _to_int(investor_row.get(subject_fields.net_buy_amount))
    buy_volume = _to_int(investor_row.get(subject_fields.buy_vol))
    sell_volume = _to_int(investor_row.get(subject_fields.sell_vol))
    total_volume = _to_int(quote_row.get("acml_vol"))
    turnover = _to_int(quote_row.get("acml_tr_pbmn"))

    strength = _compute_buy_strength(
        net_buy_qty=net_buy_qty,
        total_volume=total_volume,
        buy_volume=buy_volume,
        sell_volume=sell_volume,
    )
    turnover_status = {
        "status": "provided" if turnover is not None else "unavailable",
        "source_field": "acml_tr_pbmn",
        "reason": "ok" if turnover is not None else "acml_tr_pbmn_missing_in_quote",
    }

    return {
        "symbol": stock.get("symbol"),
        "name": stock.get("name"),
        "market": stock.get("market"),
        "subject": subject_fields.subject,
        "subject_label": subject_fields.label_ko,
        "net_buy_qty": net_buy_qty,
        "net_buy_amount": net_buy_amount,
        "buy_strength": strength.get("value"),
        "buy_strength_basis": {
            "status": strength.get("status"),
            "reason": strength.get("reason"),
            "formula_defined": strength.get("formula"),
            "formula_applied": strength.get("formula_applied"),
            "numerator_field": subject_fields.net_buy_qty,
            "denominator_field": strength.get("denominator_field"),
            "denominator_value": strength.get("denominator_value"),
        },
        "turnover": turnover,
        "turnover_basis": turnover_status,
        "as_of": investor_row.get("stck_bsop_date", ""),
        "source_fields": {
            "net_buy_qty_field": subject_fields.net_buy_qty,
            "net_buy_amount_field": subject_fields.net_buy_amount,
            "buy_volume_field": subject_fields.buy_vol,
            "sell_volume_field": subject_fields.sell_vol,
            "turnover_field": "acml_tr_pbmn",
            "total_volume_field": "acml_vol",
        },
    }


def _sort_items(items: List[Dict[str, Any]], sort_by: SortKey, order: SortOrder) -> List[Dict[str, Any]]:
    reverse = order == "desc"

    def key_fn(item: Dict[str, Any]) -> tuple:
        value = item.get(sort_by)
        if value is None:
            sentinel = float("-inf") if reverse else float("inf")
            return (sentinel, item.get("symbol", ""))
        return (float(value), item.get("symbol", ""))

    return sorted(items, key=key_fn, reverse=reverse)


async def _fetch_rows(stock: Dict[str, str], semaphore: asyncio.Semaphore) -> Dict[str, Any]:
    symbol = str(stock.get("symbol", ""))
    if not symbol:
        return {"ok": False, "symbol": "", "reason": "symbol_missing"}

    async with semaphore:
        try:
            investor_payload, quote_payload = await asyncio.gather(
                domestic_service.get_investor_profile(symbol=symbol, market_code="J"),
                domestic_service.get_current_price(symbol=symbol),
            )
            return {
                "ok": True,
                "stock": stock,
                "investor_row": _pick_first_output_row(investor_payload if isinstance(investor_payload, dict) else {}),
                "quote_row": _pick_first_output_row(quote_payload if isinstance(quote_payload, dict) else {}),
            }
        except Exception as exc:
            return {"ok": False, "stock": stock, "reason": str(exc)}


async def get_investor_buy_leaders(
    *,
    subject: InvestorType,
    market: str,
    sort_by: SortKey,
    order: SortOrder,
    limit: int,
    max_candidates: int,
    include_non_positive: bool,
) -> Dict[str, Any]:
    """Build investor-subject buy leaders by aggregating per-symbol KIS payloads."""
    market_filter = _normalize_market_filter(market)
    stocks = ensure_stock_master()
    if market_filter != "all":
        stocks = [row for row in stocks if str(row.get("market", "")).upper() == market_filter]

    capped_candidates = stocks[: max(1, min(max_candidates, 120))]
    semaphore = asyncio.Semaphore(8)
    fetched = await asyncio.gather(*[_fetch_rows(stock, semaphore) for stock in capped_candidates]) if capped_candidates else []

    subjects = _resolve_subjects(subject)
    items: List[Dict[str, Any]] = []
    failed_symbols: List[Dict[str, Any]] = []

    for row in fetched:
        if not row.get("ok"):
            stock = row.get("stock", {})
            failed_symbols.append(
                {
                    "symbol": stock.get("symbol"),
                    "name": stock.get("name"),
                    "market": stock.get("market"),
                    "reason": row.get("reason", "unknown"),
                }
            )
            continue

        stock = row.get("stock", {})
        investor_row = row.get("investor_row", {})
        quote_row = row.get("quote_row", {})
        for subject_fields in subjects:
            item = _build_item(stock=stock, subject_fields=subject_fields, investor_row=investor_row, quote_row=quote_row)
            if (not include_non_positive) and isinstance(item.get("net_buy_qty"), int) and item.get("net_buy_qty", 0) <= 0:
                continue
            items.append(item)

    sorted_items = _sort_items(items, sort_by=sort_by, order=order)
    sliced = sorted_items[: max(1, min(limit, 100))]
    unavailable_turnover = len([row for row in sliced if row.get("turnover") is None])
    unavailable_strength = len([row for row in sliced if row.get("buy_strength") is None])

    return {
        "ok": True,
        "subject": subject,
        "market": market_filter,
        "sort_by": sort_by,
        "order": order,
        "limit": max(1, min(limit, 100)),
        "max_candidates": max(1, min(max_candidates, 120)),
        "candidate_count": len(capped_candidates),
        "fetched_count": len([row for row in fetched if row.get("ok")]),
        "failed_count": len(failed_symbols),
        "count": len(sliced),
        "buy_strength_definition": {
            "formula_primary": BUY_STRENGTH_FORMULA_PRIMARY,
            "formula_fallback": BUY_STRENGTH_FORMULA_FALLBACK,
            "note": "primary는 누적거래량(acml_vol) 기반, 누락 시 주체별 매수/매도 거래량 합으로 fallback 계산",
        },
        "constraints": [
            {
                "field": "turnover",
                "status": "partial_unavailable" if unavailable_turnover > 0 else "ok",
                "reason": "acml_tr_pbmn missing in some quote payloads" if unavailable_turnover > 0 else "ok",
                "affected_count": unavailable_turnover,
            },
            {
                "field": "buy_strength",
                "status": "partial_unavailable" if unavailable_strength > 0 else "ok",
                "reason": "denominator missing or zero in some symbols" if unavailable_strength > 0 else "ok",
                "affected_count": unavailable_strength,
            },
        ],
        "items": sliced,
        "failed_symbols": failed_symbols[:80],
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_api": {
            "investor_profile": {
                "path": "/uapi/domestic-stock/v1/quotations/inquire-investor",
                "tr_id": "FHKST01010900",
            },
            "price": {
                "path": "/uapi/domestic-stock/v1/quotations/inquire-price",
                "tr_id": "FHKST01010100",
            },
        },
    }
