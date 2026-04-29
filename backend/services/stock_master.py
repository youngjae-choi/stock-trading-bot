"""Stock master download/cache for domestic keyword search."""

from __future__ import annotations

import io
import logging
import time
import zipfile
from threading import Lock
from typing import Any, Dict, List

import httpx

logger = logging.getLogger("StockMasterService")

MASTER_CACHE_TTL_SECONDS = 60 * 60 * 6
_master_cache_lock = Lock()
_stock_master_cache: Dict[str, Any] = {"updated_at": 0.0, "items": []}


def _download_master_lines(url: str) -> List[str]:
    with httpx.Client(timeout=15.0) as client:
        response = client.get(url)
        response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        first_name = archive.namelist()[0]
        raw_bytes = archive.read(first_name)
    return raw_bytes.decode("cp949", errors="ignore").splitlines()


def _parse_master(lines: List[str], market: str, tail_len: int) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for line in lines:
        row = line.rstrip("\n")
        if len(row) <= tail_len + 21:
            continue
        symbol = row[0:9].strip()
        name = row[21 : len(row) - tail_len].strip()
        if not symbol or not name:
            continue
        rows.append({"symbol": symbol, "name": name, "market": market})
    return rows


def ensure_stock_master() -> List[Dict[str, str]]:
    now = time.time()
    with _master_cache_lock:
        if _stock_master_cache["items"] and now - float(_stock_master_cache["updated_at"]) < MASTER_CACHE_TTL_SECONDS:
            return _stock_master_cache["items"]

    urls = [
        ("KOSPI", "https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip", 228),
        ("KOSDAQ", "https://new.real.download.dws.co.kr/common/master/kosdaq_code.mst.zip", 222),
        ("KONEX", "https://new.real.download.dws.co.kr/common/master/konex_code.mst.zip", 184),
    ]
    merged: List[Dict[str, str]] = []
    for market, url, tail_len in urls:
        try:
            lines = _download_master_lines(url)
            merged.extend(_parse_master(lines, market, tail_len))
        except Exception as exc:
            logger.warning("WARN: stock master download failed market=%s error=%s", market, str(exc))

    with _master_cache_lock:
        _stock_master_cache["updated_at"] = now
        _stock_master_cache["items"] = merged
    return merged
