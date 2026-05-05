"""Funnel summary API for S3/S4/Signal/Position stage aggregation."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ...api.dependencies import require_console_user
from ...services.db import get_connection

logger = logging.getLogger("BackendFunnelAPI")
router = APIRouter(
    prefix="/api/v1/funnel",
    tags=["funnel"],
    dependencies=[Depends(require_console_user)],
)


def _today_kst() -> str:
    """Return today's trading date in KST as YYYY-MM-DD."""
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


def _table_exists(conn, table_name: str) -> bool:
    """Return whether a SQLite table exists before querying optional pipeline tables.

    Args:
        conn: Open SQLite connection.
        table_name: Table name to check in sqlite_master.
    """
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _empty_profile_counts() -> dict[str, int]:
    """Return all supported risk profile counters initialized to zero."""
    return {"LOW_VOL": 0, "MID_VOL": 0, "HIGH_VOL": 0, "THEME_SPIKE": 0}


@router.get("/summary")
async def get_funnel_summary():
    """Return today's Funnel stage counts from persisted DB data."""
    today = _today_kst()
    endpoint = "/api/v1/funnel/summary"
    logger.info("START: GET %s trade_date=%s", endpoint, today)
    try:
        with get_connection() as conn:
            # Step 1: Read the latest S3 Universe Filter result when the table exists.
            uf_row = None
            if _table_exists(conn, "universe_filter_results"):
                uf_row = conn.execute(
                    "SELECT raw_count, filtered_count FROM universe_filter_results"
                    " WHERE trade_date = ? ORDER BY created_at DESC LIMIT 1",
                    (today,),
                ).fetchone()

            # Step 2: Read the latest S4 Hybrid Screening result when the table exists.
            sc_row = None
            if _table_exists(conn, "hybrid_screening_results"):
                sc_row = conn.execute(
                    "SELECT raw_input_count, output_count FROM hybrid_screening_results"
                    " WHERE trade_date = ? ORDER BY created_at DESC LIMIT 1",
                    (today,),
                ).fetchone()

            # Step 3: Count today's BUY signals and currently tracked positions.
            sig_count = conn.execute(
                "SELECT COUNT(*) FROM trading_signals WHERE trade_date = ? AND signal_type = 'BUY'",
                (today,),
            ).fetchone()[0]
            pos_count = conn.execute(
                "SELECT COUNT(*) FROM position_stop_states WHERE date(last_updated_at) = ?",
                (today,),
            ).fetchone()[0]

            # Step 4: Read the active or validated daily plan for profile distribution.
            plan_row = conn.execute(
                "SELECT symbol_assignments FROM daily_trading_plans"
                " WHERE trade_date = ? AND status IN ('active', 'validated')"
                " ORDER BY created_at DESC LIMIT 1",
                (today,),
            ).fetchone()

        profile_counts = _empty_profile_counts()
        if plan_row:
            try:
                assignments = json.loads(plan_row["symbol_assignments"] or "[]")
                for assignment in assignments:
                    profile = assignment.get("profile", "MID_VOL")
                    if profile in profile_counts:
                        profile_counts[profile] += 1
            except (TypeError, json.JSONDecodeError) as exc:
                logger.warning("WARN: GET %s profile_counts parse failed - %s", endpoint, exc)

        layer1_raw = int(uf_row["raw_count"]) if uf_row else 0
        layer1_count = int(uf_row["filtered_count"]) if uf_row else 0
        layer2_count = int(sc_row["output_count"]) if sc_row else 0
        payload = {
            "trade_date": today,
            "total_universe": 2500,
            "layer1_raw": layer1_raw,
            "layer1_count": layer1_count,
            "layer1_rejected": max(0, layer1_raw - layer1_count),
            "layer2_count": layer2_count,
            "signals_count": int(sig_count),
            "positions_count": int(pos_count),
            "profile_counts": profile_counts,
        }
        logger.info("SUCCESS: GET %s payload=%s", endpoint, payload)
        return {"ok": True, "payload": payload}
    except Exception as exc:
        logger.error("FAIL: GET %s - %s", endpoint, exc)
        return JSONResponse(status_code=500, content={"ok": False, "error": "FUNNEL_SUMMARY_FAILED"})
