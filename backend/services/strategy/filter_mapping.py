"""Map strategy filter fields to KIS API parameter intent."""

from __future__ import annotations

from typing import Any, Dict, List


FILTER_TO_API_PARAM_MAP: Dict[str, List[Dict[str, str]]] = {
    "market": [{"api": "universe_selector", "param": "market"}],
    "keyword": [{"api": "/api/v1/kis/meta/stocks/search", "param": "keyword"}],
    "limit": [{"api": "/api/v1/kis/meta/stocks/search", "param": "limit"}],
    "price_min": [
        {"api": "/api/v1/kis/price/{symbol}", "param": "output.stck_prpr"},
        {"api": "/api/v1/kis/overseas/price/{exchange}/{symbol}", "param": "output.last/clos/tkpr"},
    ],
    "price_max": [
        {"api": "/api/v1/kis/price/{symbol}", "param": "output.stck_prpr"},
        {"api": "/api/v1/kis/overseas/price/{exchange}/{symbol}", "param": "output.last/clos/tkpr"},
    ],
    "min_turnover": [
        {"api": "/api/v1/kis/price/{symbol}", "param": "output.acml_tr_pbmn"},
        {"api": "/api/v1/kis/overseas/price/{exchange}/{symbol}", "param": "output.tamt/xymd_tdot"},
    ],
    "volume_min": [
        {"api": "/api/v1/kis/price/{symbol}", "param": "output.acml_vol"},
        {"api": "/api/v1/kis/overseas/price/{exchange}/{symbol}", "param": "output.tvol/evol"},
    ],
    "volume_max": [
        {"api": "/api/v1/kis/price/{symbol}", "param": "output.acml_vol"},
        {"api": "/api/v1/kis/overseas/price/{exchange}/{symbol}", "param": "output.tvol/evol"},
    ],
    "volatility_min": [
        {"api": "/api/v1/kis/price/{symbol}", "param": "(high-low)/current"},
        {"api": "/api/v1/kis/overseas/price/{exchange}/{symbol}", "param": "(high-low)/current"},
    ],
    "volatility_max": [
        {"api": "/api/v1/kis/price/{symbol}", "param": "(high-low)/current"},
        {"api": "/api/v1/kis/overseas/price/{exchange}/{symbol}", "param": "(high-low)/current"},
    ],
}


def build_filter_mapping(strategy_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return only active filter->API mappings for current strategy payload."""
    active: Dict[str, Any] = {}
    for key, value in strategy_payload.items():
        if value in (None, ""):
            continue
        if isinstance(value, (int, float)) and value == 0:
            continue
        mappings = FILTER_TO_API_PARAM_MAP.get(key)
        if mappings:
            active[key] = {"value": value, "api_bindings": mappings}
    return {
        "active_filter_count": len(active),
        "active_filters": active,
    }
