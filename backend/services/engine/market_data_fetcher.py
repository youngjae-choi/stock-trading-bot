"""Overnight overseas market data fetcher for S2 market tone analysis."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger("MarketDataFetcher")

_TIMEOUT = 15.0
_SYMBOLS = {
    "sp500": "^GSPC",
    "nasdaq": "^IXIC",
    "ftse100": "^FTSE",
    "dax": "^GDAXI",
    "oil_wti": "CL=F",
    "usdkrw": "USDKRW=X",
    "us_10y_yield": "^TNX",
    "vix": "^VIX",
    # 미국상장 한국대표 ETF(MSCI Korea). 밤사이 미국장에서 거래·마감 → KR 프리마켓(08:30)
    # 시점에 신선한 '간밤 한국물 심리' = 갭 선행지표. (삼성 23%·SK하이닉스 22% 등 대형주 구성)
    # KR/JP/HK/CN 현물지수·종목은 개장 전이라 전일 종가(stale) → 프리마켓 브리핑에서 제외.
    "ewy_korea": "EWY",
    "sector_tech": "XLK",
    "sector_finance": "XLF",
    "sector_energy": "XLE",
    "sector_health": "XLV",
    "sector_industry": "XLI",
    "sox": "^SOX",
    # 장전 선행지표 확대(2026-08-06 PM) — 야간선물·안전자산·금리·환/코인.
    "nasdaq_futures": "NQ=F",     # 나스닥100 선물(야간) — 미국장 방향 선행
    "sp500_futures": "ES=F",      # S&P500 선물(야간)
    "gold": "GC=F",               # 금(안전자산 선호 지표)
    "bitcoin": "BTC-USD",         # 비트코인(위험선호/유동성)
    "dollar_index": "DX-Y.NYB",   # 달러인덱스(DXY) — 강달러=신흥국 부담
    "us_2y_yield": "2YY=F",       # 미국 2년물 국채금리(정책금리 기대)
}
_YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=2d&interval=1d"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; KairosMarketFetcher/1.0)"}


async def _fetch_symbol(client: httpx.AsyncClient, key: str, symbol: str) -> tuple[str, dict[str, Any] | None]:
    """Fetch one Yahoo Finance chart symbol and normalize price movement fields."""
    url = _YAHOO_URL.format(symbol=quote(symbol, safe=""))
    logger.info("START: MarketDataFetcher.fetch_symbol key=%s symbol=%s", key, symbol)
    try:
        resp = await client.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        result = data.get("chart", {}).get("result") or []
        if not result:
            logger.warning("WARN: MarketDataFetcher empty_result key=%s symbol=%s", key, symbol)
            return key, None

        meta = result[0].get("meta", {})
        price = meta.get("regularMarketPrice") or meta.get("previousClose")
        prev_close = meta.get("chartPreviousClose") or meta.get("previousClose") or price
        if price is None or prev_close is None:
            logger.warning("WARN: MarketDataFetcher missing_price key=%s symbol=%s", key, symbol)
            return key, None

        change_pct = round(((float(price) - float(prev_close)) / float(prev_close) * 100) if float(prev_close) else 0.0, 2)
        direction = "up" if change_pct > 0 else ("down" if change_pct < 0 else "flat")
        logger.info("SUCCESS: MarketDataFetcher.fetch_symbol key=%s change_pct=%s", key, change_pct)
        return key, {
            "symbol": symbol,
            "price": round(float(price), 4),
            "prev_close": round(float(prev_close), 4),
            "change_pct": change_pct,
            "direction": direction,
        }
    except Exception as exc:
        logger.warning("WARN: MarketDataFetcher symbol=%s failed reason=%s", symbol, exc)
        return key, None


async def fetch_overnight_market_summary() -> dict[str, Any]:
    """Fetch configured overseas market symbols sequentially and return a prompt-ready summary dict."""
    fetched_at = datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
    logger.info("START: MarketDataFetcher.fetch_overnight_market_summary")

    results: dict[str, Any] = {}
    errors: list[str] = []
    async with httpx.AsyncClient() as client:
        for key, symbol in _SYMBOLS.items():
            fetched_key, item = await _fetch_symbol(client, key, symbol)
            if item:
                results[fetched_key] = item
            else:
                results[fetched_key] = None
                errors.append(fetched_key)

    # 장단기 금리차(10Y-2Y) 파생 — 수익률 곡선 역전(음수)은 경기침체 선행 신호.
    _t10 = (results.get("us_10y_yield") or {}).get("price")
    _t2 = (results.get("us_2y_yield") or {}).get("price")
    if _t10 is not None and _t2 is not None:
        _spread = round(float(_t10) - float(_t2), 2)
        results["yield_spread_10y_2y"] = {
            "symbol": "10Y-2Y", "price": _spread, "prev_close": _spread,
            "change_pct": 0.0, "direction": "up" if _spread >= 0 else "down",
        }

    results["fetched_at"] = fetched_at
    results["errors"] = errors
    logger.info("SUCCESS: MarketDataFetcher fetched=%d errors=%d", len(_SYMBOLS) - len(errors), len(errors))
    return results


def format_for_prompt(market_data: dict[str, Any]) -> str:
    """Convert fetched market data into compact Korean text for the LLM prompt."""
    lines = ["[전날 밤 해외 시장 현황]"]
    labels = {
        "sp500": "S&P 500",
        "nasdaq": "NASDAQ",
        "ftse100": "FTSE 100",
        "dax": "DAX",
        "oil_wti": "WTI 원유",
        "usdkrw": "USD/KRW",
        "us_10y_yield": "미국 10년 국채금리(%)",
        "vix": "VIX 공포지수",
        "ewy_korea": "EWY(미국상장 한국대표 ETF·간밤 종가, KR 갭 선행지표)",
        "kospi_night_futures": "코스피200 야간선물(다음날 갭 선행지표)",
        "sector_tech": "미국 기술섹터 XLK",
        "sector_finance": "미국 금융섹터 XLF",
        "sector_energy": "미국 에너지섹터 XLE",
        "sector_health": "미국 헬스케어 XLV",
        "sector_industry": "미국 산업섹터 XLI",
        "sox": "필라델피아 반도체지수(SOX)",
    }
    arrows = {"up": "▲", "down": "▼", "flat": "━"}
    for key, label in labels.items():
        item = market_data.get(key)
        if item:
            arrow = arrows.get(item.get("direction"), "━")
            lines.append(f"  {label}: {item['price']} {arrow}{item['change_pct']:+.2f}%")
        else:
            lines.append(f"  {label}: 데이터 없음")
    if market_data.get("errors"):
        lines.append(f"  (미수집: {', '.join(market_data['errors'])})")
    lines.append(f"  수집 시각: {market_data.get('fetched_at', '알 수 없음')}")
    return "\n".join(lines)
