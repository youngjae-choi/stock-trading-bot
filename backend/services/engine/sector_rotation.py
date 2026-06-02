"""Sector rotation detection for intraday reselection."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection
from ..settings_store import get_setting

logger = logging.getLogger("SectorRotation")
KST = ZoneInfo("Asia/Seoul")


def _to_float(value: Any, default: float = 0.0) -> float:
    """Convert market payload values to float while tolerating comma strings."""
    try:
        return float(str(value).replace(",", "").strip() or default)
    except (TypeError, ValueError):
        return default


def _setting_bool(key: str, default: bool) -> bool:
    """Read a boolean system setting for kill switches on every call."""
    try:
        value = get_setting(key, default)
    except Exception as exc:
        logger.warning("WARN: SectorRotation setting read failed key=%s reason=%s", key, exc)
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def _setting_float(key: str, default: float) -> float:
    """Read a float system setting and fall back defensively on malformed data."""
    try:
        return _to_float(get_setting(key, default), default)
    except Exception as exc:
        logger.warning("WARN: SectorRotation setting read failed key=%s reason=%s", key, exc)
        return default


def _today() -> str:
    """Return today's KST trade date."""
    return datetime.now(KST).strftime("%Y-%m-%d")


def _ensure_sector_rotation_table() -> None:
    """Create the sector rotation log table for databases that skipped full initialization."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sector_rotation_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date TEXT NOT NULL,
                slot TEXT NOT NULL,
                top_sectors TEXT NOT NULL,
                bottom_sectors TEXT NOT NULL,
                gap_pct REAL NOT NULL,
                triggered INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sector_rotation_log_date ON sector_rotation_log(trade_date)")


def _symbol_sector_map(symbols: list[str]) -> dict[str, str]:
    """Load sectors for snapshot symbols from the local symbols table."""
    if not symbols:
        return {}
    placeholders = ",".join("?" for _ in symbols)
    try:
        with get_connection() as conn:
            rows = conn.execute(
                f"SELECT symbol, sector FROM symbols WHERE symbol IN ({placeholders})",
                symbols,
            ).fetchall()
        return {str(row["symbol"]): str(row["sector"] or "").strip() for row in rows}
    except Exception as exc:
        logger.warning("WARN: SectorRotation sector lookup failed reason=%s", exc)
        return {}


def detect_sector_rotation(snapshot: dict[str, Any], slot: str = "", trade_date: str | None = None) -> dict[str, Any]:
    """Detect whether top sectors significantly outperform the remaining sectors.

    Args:
        snapshot: Intraday market snapshot. Uses snapshot["sectors"] — the KIS
            sector-index change rates collected by fetch_intraday_kr_market_snapshot.
        slot: Optional scheduler slot used for audit logging.
        trade_date: Optional YYYY-MM-DD trade date. Defaults to today in KST.
    """
    trade_date = trade_date or _today()
    if not _setting_bool("intraday_refresh.master_enabled", True):
        return {"ok": True, "enabled": False, "triggered": False, "reason": "master_disabled", "gap_pct": 0.0}
    if not _setting_bool("intraday_refresh.sector_rotation_enabled", True):
        return {"ok": True, "enabled": False, "triggered": False, "reason": "sector_rotation_disabled", "gap_pct": 0.0}

    threshold = _setting_float("intraday_refresh.sector_rotation_threshold", 3.0)

    # 업종 지수 등락률을 직접 사용한다 (snapshot["sectors"] = KIS get_sector_index 결과).
    # 과거에는 volume-rank 개별종목을 sector 필드로 재그룹화했으나, 해당 응답에
    # bstp_kor_isnm(업종명)이 없고 symbols 테이블도 비어 있어 항상 sector_sample_insufficient
    # 였다. 이미 매 슬롯 수집 중인 업종 지수를 직접 쓰면 추가 API 없이 정확하다.
    sectors = snapshot.get("sectors", []) if isinstance(snapshot, dict) else []
    if not isinstance(sectors, list) or not sectors:
        result = {"ok": False, "enabled": True, "triggered": False, "reason": "snapshot_empty", "gap_pct": 0.0}
        if slot:
            save_sector_rotation_log(trade_date, slot, result)
        return result

    sector_avgs = [
        {
            "sector": str(s.get("name") or s.get("sector") or "").strip(),
            "avg_change": round(_to_float(s.get("change_rate") or s.get("avg_change")), 2),
            "count": 1,
        }
        for s in sectors
        if isinstance(s, dict)
        and str(s.get("name") or s.get("sector") or "").strip()
        and (s.get("change_rate") is not None or s.get("avg_change") is not None)
    ]
    sector_avgs.sort(key=lambda item: item["avg_change"], reverse=True)
    if len(sector_avgs) < 3:
        result = {
            "ok": True,
            "enabled": True,
            "triggered": False,
            "reason": "sector_sample_insufficient",
            "top_sectors": sector_avgs[:2],
            "bottom_sectors": sector_avgs[2:],
            "gap_pct": 0.0,
        }
        if slot:
            save_sector_rotation_log(trade_date, slot, result)
        return result

    top_sectors = sector_avgs[:2]
    bottom_sectors = sector_avgs[2:]
    top_avg = sum(item["avg_change"] for item in top_sectors) / len(top_sectors)
    bottom_avg = sum(item["avg_change"] for item in bottom_sectors) / len(bottom_sectors)
    gap_pct = round(top_avg - bottom_avg, 2)
    triggered = gap_pct >= threshold
    top_text = ", ".join(f"{item['sector']}({item['avg_change']:+.1f}%)" for item in top_sectors)
    bottom_text = ", ".join(f"{item['sector']}({item['avg_change']:+.1f}%)" for item in bottom_sectors[:2])
    reason = f"{top_text} ↔ {bottom_text} (갭 {gap_pct:.1f}%)"
    result = {
        "ok": True,
        "enabled": True,
        "triggered": triggered,
        "reason": reason,
        "top_sectors": top_sectors,
        "bottom_sectors": bottom_sectors,
        "gap_pct": gap_pct,
        "threshold": threshold,
    }
    if slot:
        save_sector_rotation_log(trade_date, slot, result)
    logger.info(
        "INFO: SectorRotation evaluated slot=%s triggered=%s gap=%.2f threshold=%.2f",
        slot or "-",
        triggered,
        gap_pct,
        threshold,
    )
    return result


def save_sector_rotation_log(trade_date: str, slot: str, result: dict[str, Any]) -> None:
    """Persist one sector analysis result regardless of trigger outcome."""
    _ensure_sector_rotation_table()
    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO sector_rotation_log
                    (trade_date, slot, top_sectors, bottom_sectors, gap_pct, triggered)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    trade_date,
                    slot,
                    json.dumps(result.get("top_sectors", []), ensure_ascii=False),
                    json.dumps(result.get("bottom_sectors", []), ensure_ascii=False),
                    _to_float(result.get("gap_pct")),
                    1 if result.get("triggered") else 0,
                ),
            )
    except Exception as exc:
        logger.warning("WARN: SectorRotation log insert failed slot=%s reason=%s", slot, exc)


def get_sector_rotation_logs(trade_date: str) -> list[dict[str, Any]]:
    """Return persisted sector rotation logs for one trade date."""
    _ensure_sector_rotation_table()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM sector_rotation_log WHERE trade_date = ? ORDER BY created_at ASC, id ASC",
            (trade_date,),
        ).fetchall()
    results: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        data["top_sectors"] = json.loads(data.get("top_sectors") or "[]")
        data["bottom_sectors"] = json.loads(data.get("bottom_sectors") or "[]")
        data["triggered"] = bool(data.get("triggered"))
        results.append(data)
    return results
