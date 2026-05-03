"""S11: 22:00 KST 미국 장중 지표 수집 → overnight_market_snapshots 저장."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from ..db import get_connection
from .market_data_fetcher import fetch_overnight_market_summary

logger = logging.getLogger("USMarketWatch")


def _ensure_table() -> None:
    with get_connection() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS overnight_market_snapshots (
                id TEXT PRIMARY KEY,
                snapshot_date TEXT NOT NULL,
                snapshot_time TEXT NOT NULL,
                sp500_chg_pct REAL,
                nasdaq_chg_pct REAL,
                dow_chg_pct REAL,
                ftse100_chg_pct REAL,
                dax_chg_pct REAL,
                oil_wti_chg_pct REAL,
                usdkrw_rate REAL,
                us_10y_yield REAL,
                raw_data TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_overnight_market_snapshot_date "
            "ON overnight_market_snapshots(snapshot_date)"
        )


async def run_us_market_watch() -> dict:
    """미국 장중 주요 지표를 수집하고 overnight_market_snapshots에 저장한다."""
    _ensure_table()
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    snapshot_date = now_kst.strftime("%Y-%m-%d")
    snapshot_time = now_kst.strftime("%H:%M")
    now_iso = now_kst.isoformat()

    data = await fetch_overnight_market_summary()

    def _chg(key: str) -> float | None:
        item = data.get(key)
        if item and item.get("change_pct") is not None:
            try:
                return float(item["change_pct"])
            except (ValueError, TypeError):
                return None
        return None

    def _price(key: str) -> float | None:
        item = data.get(key)
        if item and item.get("price") is not None:
            try:
                return float(item["price"])
            except (ValueError, TypeError):
                return None
        return None

    snapshot_id = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO overnight_market_snapshots
               (id, snapshot_date, snapshot_time,
                sp500_chg_pct, nasdaq_chg_pct, dow_chg_pct,
                ftse100_chg_pct, dax_chg_pct, oil_wti_chg_pct,
                usdkrw_rate, us_10y_yield, raw_data, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                snapshot_id, snapshot_date, snapshot_time,
                _chg("sp500"), _chg("nasdaq"), _chg("dow"),
                _chg("ftse100"), _chg("dax"), _chg("oil_wti"),
                _price("usdkrw"), _price("us_10y_yield"),
                json.dumps(data, ensure_ascii=False),
                now_iso,
            ),
        )

    logger.info(
        "SUCCESS: USMarketWatch snapshot saved date=%s time=%s sp500=%s nasdaq=%s",
        snapshot_date, snapshot_time, _chg("sp500"), _chg("nasdaq"),
    )

    return {
        "snapshot_date": snapshot_date,
        "snapshot_time": snapshot_time,
        "sp500_chg_pct": _chg("sp500"),
        "nasdaq_chg_pct": _chg("nasdaq"),
        "usdkrw_rate": _price("usdkrw"),
        "errors": data.get("errors", []),
    }


def get_latest_snapshot(trade_date: str | None = None) -> dict | None:
    """가장 최근 overnight snapshot 조회 (S2에서 활용)."""
    _ensure_table()
    with get_connection() as conn:
        if trade_date:
            row = conn.execute(
                "SELECT * FROM overnight_market_snapshots "
                "WHERE snapshot_date = ? ORDER BY snapshot_time DESC LIMIT 1",
                (trade_date,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM overnight_market_snapshots "
                "ORDER BY snapshot_date DESC, snapshot_time DESC LIMIT 1"
            ).fetchone()
    if not row:
        return None
    d = dict(row)
    if isinstance(d.get("raw_data"), str):
        try:
            d["raw_data"] = json.loads(d["raw_data"])
        except Exception:
            pass
    return d
