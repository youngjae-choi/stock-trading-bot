"""Exchange normalization and KIS market code mapping."""

from __future__ import annotations

from typing import Dict


# 가격/차트 조회 API에서 사용하는 EXCD 코드
OVERSEAS_EXCD_MAP: Dict[str, str] = {
    "NASD": "NAS",
    "NASDAQ": "NAS",
    "NYSE": "NYS",
    "AMEX": "AMS",
    "SEHK": "HKS",
    "HKEX": "HKS",
    "TKSE": "TSE",
    "TYO": "TSE",
    "SHAA": "SHS",
    "SZAA": "SZS",
    "HASE": "HNX",
    "VNSE": "HSX",
}

# 주문 API에서 사용하는 OVRS_EXCG_CD 표준 코드
ORDER_EXCHANGE_CODES = {"NASD", "NYSE", "AMEX", "SEHK", "SHAA", "SZAA", "TKSE", "HASE", "VNSE"}


def normalize_order_exchange(exchange: str) -> str:
    normalized = exchange.strip().upper()
    aliases = {
        "NASDAQ": "NASD",
        "HKEX": "SEHK",
        "TYO": "TKSE",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in ORDER_EXCHANGE_CODES:
        raise ValueError(
            "unsupported exchange. allowed: NASD/NYSE/AMEX/SEHK/SHAA/SZAA/TKSE/HASE/VNSE"
        )
    return normalized


def to_overseas_excd(exchange: str) -> str:
    normalized = normalize_order_exchange(exchange)
    return OVERSEAS_EXCD_MAP.get(normalized, normalized)
