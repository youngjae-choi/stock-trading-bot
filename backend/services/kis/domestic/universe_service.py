"""Universe ranking service wrappers for domestic KIS APIs."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, Literal
from zoneinfo import ZoneInfo

from ..common.client import kis_client

KST = ZoneInfo("Asia/Seoul")

# 업종 코드 → 이름 (KIS FID_INPUT_ISCD)
_SECTOR_MAP: dict[str, str] = {
    "0029": "반도체/IT",   # KOSPI 전기전자
    "0027": "2차전지",     # KOSPI 비철금속(배터리 소재)
    "0041": "금융",        # KOSPI 금융업
    "0020": "바이오",      # KOSPI 의약품
}

logger = logging.getLogger("KISUniverseService")

_SYMBOL_KEYS = ("mksc_shrn_iscd", "stck_shrn_iscd", "pdno", "symbol", "code")
_NAME_KEYS = ("hts_kor_isnm", "stck_kor_isnm", "prdt_name", "name")
_PRICE_KEYS = ("stck_prpr", "stck_prc", "prpr", "now_prc", "price")
_CHANGE_RATE_KEYS = ("prdy_ctrt", "prdy_vrss_rate", "fluctuation_rate", "change_rate")
_VOLUME_KEYS = ("acml_vol", "acc_trdvol", "cntg_vol", "vol", "volume")
_TRADE_AMOUNT_KEYS = ("acml_tr_pbmn", "acc_trdval", "tr_pbmn", "trade_amount", "turnover", "stck_avls")


def _clamp_top_n(top_n: int) -> int:
    if top_n <= 0:
        return 1
    return min(top_n, 60)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        text = str(value or "").replace(",", "").strip()
        return int(float(text)) if text else default
    except Exception:
        return default


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        text = str(value or "").replace(",", "").strip()
        return float(text) if text else default
    except Exception:
        return default


def _pick(row: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in row and row.get(key) not in (None, ""):
            return row.get(key)
    return default


def _pick_int(row: Dict[str, Any], keys: tuple[str, ...]) -> int:
    """KIS ranking 응답의 유사 숫자 필드 중 첫 유효값을 정수로 변환한다."""
    return _to_int(_pick(row, *keys, default=0))


def _pick_float(row: Dict[str, Any], keys: tuple[str, ...]) -> float:
    """KIS ranking 응답의 유사 숫자 필드 중 첫 유효값을 실수로 변환한다."""
    return _to_float(_pick(row, *keys, default=0.0))


def _extract_rows(payload: Dict[str, Any]) -> list[Dict[str, Any]]:
    rows = payload.get("output") or payload.get("output1") or payload.get("items") or []
    return rows if isinstance(rows, list) else []


async def get_volume_rank(market_code: str = "J", top_n: int = 100) -> Dict[str, Any]:
    limit = _clamp_top_n(top_n)

    # KIS 1회 호출 최대 30건.
    # FID_BLNG_CLS_CODE: 0=전체, 1=코스피, 2=코스닥
    blng_map = {"J": ["0"], "STK": ["1"], "KSQ": ["2"]}
    blng_codes = blng_map.get(market_code, ["0"])
    if limit > 30 and market_code == "J":
        blng_codes = ["1", "2"]

    raw_rows: list[Dict[str, Any]] = []
    seen_symbols: set[str] = set()

    for blng in blng_codes:
        payload = await kis_client.request(
            method="GET",
            path="/uapi/domestic-stock/v1/quotations/volume-rank",
            tr_id="FHPST01710000",
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_COND_SCR_DIV_CODE": "20171",
                "FID_INPUT_ISCD": "0000",
                "FID_DIV_CLS_CODE": "0",
                "FID_BLNG_CLS_CODE": blng,
                "FID_TRGT_CLS_CODE": "111111111",
                "FID_TRGT_EXLS_CLS_CODE": "000000",
                "FID_INPUT_PRICE_1": "",
                "FID_INPUT_PRICE_2": "",
                "FID_VOL_CNT": "0",
                "FID_INPUT_DATE_1": "",
            },
        )
        for row in _extract_rows(payload):
            sym = str(_pick(row, *_SYMBOL_KEYS, default=""))
            if sym and sym not in seen_symbols:
                seen_symbols.add(sym)
                raw_rows.append(row)

    # 거래량 기준 내림차순 정렬 후 top_n 적용
    raw_rows.sort(key=lambda r: _to_int(_pick(r, "acml_vol", "volume", default=0)), reverse=True)

    items: list[Dict[str, Any]] = []
    for idx, row in enumerate(raw_rows[:limit], start=1):
        items.append(
            {
                "rank": idx,
                "symbol": str(_pick(row, *_SYMBOL_KEYS, default="")),
                "name": str(_pick(row, *_NAME_KEYS, default="")),
                "volume": _pick_int(row, _VOLUME_KEYS),
                "price": _pick_int(row, _PRICE_KEYS),
                "change_rate": _pick_float(row, _CHANGE_RATE_KEYS),
                "sector": str(_pick(row, "bstp_kor_isnm", default="")),
            }
        )

    return {"items": items, "count": len(items)}


async def get_price_rank(
    sort_by: Literal["change_rate", "trade_amount"] = "change_rate",
    market_code: str = "J",
    top_n: int = 100,
) -> Dict[str, Any]:
    limit = _clamp_top_n(top_n)
    safe_sort_by = "trade_amount" if sort_by == "trade_amount" else "change_rate"

    # 등락률: FHPST01700000 / 거래대금: FHPST01740000 (market-cap TR 재사용)
    if safe_sort_by == "change_rate":
        tr_id = "FHPST01700000"
        path = "/uapi/domestic-stock/v1/ranking/fluctuation"
        scr_div_code = "20170"
        extra_params: Dict[str, Any] = {
            "FID_RANK_SORT_CLS_CODE": "0",  # 0=상승률
            "FID_INPUT_CNT_1": "0",
            "FID_PRC_CLS_CODE": "0",        # 0=현재가 기준
            "FID_RSFL_RATE1": "",
            "FID_RSFL_RATE2": "",
        }
    else:
        tr_id = "FHPST01740000"
        path = "/uapi/domestic-stock/v1/ranking/market-cap"  # 거래대금 순위 TR
        scr_div_code = "20174"
        extra_params = {}

    base_params_template: Dict[str, Any] = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_COND_SCR_DIV_CODE": scr_div_code,
        "FID_INPUT_ISCD": "0000",
        "FID_DIV_CLS_CODE": "0",
        "FID_TRGT_CLS_CODE": "111111111",
        "FID_TRGT_EXLS_CLS_CODE": "000000",
        "FID_INPUT_PRICE_1": "",
        "FID_INPUT_PRICE_2": "",
        "FID_VOL_CNT": "0",
        "FID_INPUT_DATE_1": "",
        **extra_params,
    }

    async def _fetch_rows(mrkt_div_code: str, blng_code: str = "0") -> list[Dict[str, Any]]:
        params = dict(base_params_template)
        params["FID_COND_MRKT_DIV_CODE"] = mrkt_div_code
        params["FID_BLNG_CLS_CODE"] = blng_code
        payload = await kis_client.request(method="GET", path=path, tr_id=tr_id, params=params)
        return _extract_rows(payload)

    raw_rows: list[Dict[str, Any]] = []
    seen_symbols: set[str] = set()

    # 요구사항: top_n<=30 -> 전체(J,0) 단일 호출
    # top_n>30 and J -> STK(코스피)+KSQ(코스닥) 시장코드 분리 병렬 호출, 실패 시 전체(J,0) 폴백
    # FID_BLNG_CLS_CODE는 volume-rank에만 효과적이고 price-rank에는 FID_COND_MRKT_DIV_CODE로 분리해야 함
    if limit > 30 and market_code == "J":
        parallel_results = await asyncio.gather(
            _fetch_rows("STK", "0"), _fetch_rows("KSQ", "0"), return_exceptions=True
        )
        if any(isinstance(result, Exception) for result in parallel_results):
            for idx, result in enumerate(parallel_results, start=1):
                if isinstance(result, Exception):
                    logger.error(
                        "FAIL: price-rank segmented fetch mrkt=%s sort_by=%s top_n=%s reason=%s",
                        "STK" if idx == 1 else "KSQ",
                        safe_sort_by,
                        limit,
                        str(result),
                    )
            logger.warning(
                "RETRY: price-rank segmented fetch failed. fallback to J/0 sort_by=%s top_n=%s",
                safe_sort_by,
                limit,
            )
            segment_rows = [await _fetch_rows("J", "0")]
        else:
            segment_rows = [
                result for result in parallel_results
                if isinstance(result, list)
            ]
    else:
        mrkt_map = {"J": "J", "STK": "STK", "KSQ": "KSQ"}
        segment_rows = [await _fetch_rows(mrkt_map.get(market_code, "J"), "0")]

    if limit > 30 and market_code == "J" and sum(len(s) for s in segment_rows) == 0:
        logger.warning(
            "RETRY: price-rank segmented fetch returned 0 rows — fallback to J/0 sort_by=%s top_n=%s",
            safe_sort_by,
            limit,
        )
        segment_rows = [await _fetch_rows("J", "0")]

    for rows in segment_rows:
        for row in rows:
            sym = str(_pick(row, *_SYMBOL_KEYS, default=""))
            if sym and sym not in seen_symbols:
                seen_symbols.add(sym)
                raw_rows.append(row)

    # 병합 후 정렬
    sort_field = "prdy_ctrt" if safe_sort_by == "change_rate" else "acml_tr_pbmn"
    raw_rows.sort(key=lambda r: _to_float(_pick(r, sort_field, default=0)), reverse=True)

    items: list[Dict[str, Any]] = []
    for idx, row in enumerate(raw_rows[:limit], start=1):
        items.append(
            {
                "rank": idx,
                "symbol": str(_pick(row, *_SYMBOL_KEYS, default="")),
                "name": str(_pick(row, *_NAME_KEYS, default="")),
                "price": _pick_int(row, _PRICE_KEYS),
                "change_rate": _pick_float(row, _CHANGE_RATE_KEYS),
                "trade_amount": _pick_int(row, _TRADE_AMOUNT_KEYS),
            }
        )

    return {"sort_by": safe_sort_by, "items": items, "count": len(items)}


async def get_market_index(index_code: str) -> dict[str, Any]:
    """KOSPI(0001) / KOSDAQ(1001) 지수 현재가·등락률 조회.

    TR_ID FHPUP02100000 = 국내업종 현재지수 (v1_국내주식-063)
    """
    payload = await kis_client.request(
        method="GET",
        path="/uapi/domestic-stock/v1/quotations/inquire-index-price",
        tr_id="FHPUP02100000",
        params={
            "FID_COND_MRKT_DIV_CODE": "U",
            "FID_INPUT_ISCD": index_code,
        },
    )
    out = payload.get("output", {})
    return {
        "code": index_code,
        "price": _to_float(out.get("bstp_nmix_prpr", 0)),
        "change_rate": _to_float(out.get("bstp_nmix_prdy_ctrt", 0)),
        "change": _to_float(out.get("bstp_nmix_prdy_vrss", 0)),
    }


async def get_sector_index(sector_code: str) -> dict[str, Any]:
    """업종 지수 등락률 조회 (sector_code는 _SECTOR_MAP 키).

    TR_ID FHPUP02100000 = 국내업종 현재지수 (v1_국내주식-063)
    """
    payload = await kis_client.request(
        method="GET",
        path="/uapi/domestic-stock/v1/quotations/inquire-index-price",
        tr_id="FHPUP02100000",
        params={
            "FID_COND_MRKT_DIV_CODE": "U",
            "FID_INPUT_ISCD": sector_code,
        },
    )
    out = payload.get("output", {})
    return {
        "code": sector_code,
        "name": _SECTOR_MAP.get(sector_code, sector_code),
        "change_rate": _to_float(out.get("bstp_nmix_prdy_ctrt", 0)),
    }


async def fetch_intraday_kr_market_snapshot() -> dict[str, Any]:
    """장중 한국 시장 종합 스냅샷.

    병렬로 4종 데이터를 수집한다. 일부 호출이 실패해도 나머지는 살린다.

    Returns:
        {
            "ok": bool,
            "fetched_at": str,          # ISO8601 KST
            "kospi": {"change_rate": float, ...},
            "kosdaq": {"change_rate": float, ...},
            "top10": [{"symbol", "name", "change_rate"}, ...],   # 거래대금 상위 10
            "vol30_avg_change": float,  # 거래량 상위 30종목 평균 등락률
            "sectors": [{"name", "change_rate"}, ...],
            "avg_change": float,        # 기존 호환 — vol30_avg_change 동일값
        }
    """
    tasks = [
        get_market_index("0001"),                                    # KOSPI
        get_market_index("1001"),                                    # KOSDAQ
        get_price_rank(sort_by="trade_amount", market_code="J", top_n=10),  # 거래대금 상위
        get_volume_rank(market_code="J", top_n=30),                  # 거래량 상위
        *[get_sector_index(code) for code in _SECTOR_MAP],          # 업종 지수
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    kospi_raw, kosdaq_raw, top10_raw, vol30_raw, *sector_raws = results
    now = datetime.now(KST).isoformat()

    def _safe(r: Any, fallback: Any) -> Any:
        return fallback if isinstance(r, Exception) else r

    kospi = _safe(kospi_raw, {"code": "0001", "change_rate": None, "price": None})
    kosdaq = _safe(kosdaq_raw, {"code": "1001", "change_rate": None, "price": None})

    top10_items = _safe(top10_raw, {}).get("items", [])[:10]

    vol30 = _safe(vol30_raw, {"items": []})
    vol30_items = vol30.get("items", [])
    rates = [float(it.get("change_rate") or 0.0) for it in vol30_items]
    avg_change = round(sum(rates) / len(rates), 2) if rates else None

    sectors = []
    for raw in sector_raws:
        if not isinstance(raw, Exception):
            sectors.append({"name": raw["name"], "change_rate": raw["change_rate"]})

    ok = avg_change is not None  # 최소한 vol30이 있어야 useful
    return {
        "ok": ok,
        "fetched_at": now,
        "kospi": kospi,
        "kosdaq": kosdaq,
        "top10": [
            {"symbol": it["symbol"], "name": it["name"], "change_rate": it["change_rate"]}
            for it in top10_items
        ],
        "vol30_avg_change": avg_change,
        "avg_change": avg_change,       # intraday_refresh._needs_refresh 호환
        "items": vol30_items,           # sector_rotation.detect_sector_rotation 호환
        "sectors": sectors,
        "count": len(vol30_items),
    }
