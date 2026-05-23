"""Regime Set API routes for set listing, matching preview, and application history."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, HTTPException, Path, Query
from pydantic import BaseModel

from ...services.db import get_connection
from ...services.regime_set_service import (
    get_all_sets,
    get_match_preview,
    get_set_history,
    get_today_application,
    get_today_transitions,
)

router = APIRouter(prefix="/api/v1/regime", tags=["regime-sets"])
logger = logging.getLogger("RegimeSetsAPI")
KST = timezone(timedelta(hours=9))


class RegimeSetUpdateRequest(BaseModel):
    """Request body for partially updating a Regime Set configuration.

    Args:
        name: Optional replacement display name.
        description: Optional replacement description.
        settings: Optional settings fragment merged into the existing JSON settings.
        trigger_conditions: Optional replacement trigger condition JSON.
        is_active: Optional active/inactive flag.
    """

    name: str | None = None
    description: str | None = None
    settings: dict[str, Any] | None = None
    trigger_conditions: dict[str, Any] | None = None
    is_active: bool | None = None


def _today_kst() -> str:
    """Return today's KST date as YYYY-MM-DD for route defaults."""
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


def _now_kst() -> str:
    """Return the current KST timestamp in ISO format for DB updates."""
    return datetime.now(KST).isoformat()


def _json_loads(value: str | None, fallback: Any) -> Any:
    """Parse a JSON text value and return fallback when legacy data is malformed."""
    try:
        return json.loads(value or "")
    except Exception:
        return fallback


def _json_dumps(value: Any) -> str:
    """Serialize JSON columns without escaping Korean labels."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _table_columns(conn: Any, table_name: str) -> set[str]:
    """Return column names for a SQLite table using PRAGMA table_info.

    Args:
        conn: Open SQLite connection.
        table_name: Table name to inspect.
    """
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _get_profile_breakdown(conn: Any, trade_date: str) -> list[dict[str, Any]]:
    """Return Risk Profile performance for the given trade date.

    Uses profile_performance_daily (aggregated by daily_summary S9) which already
    has per-profile win_count / total_pnl without needing orders columns.
    This enables regime × profile cross-analysis: which profile wins in which regime.

    Args:
        conn: Open SQLite connection.
        trade_date: Trading day in YYYY-MM-DD format.
    """
    try:
        rows = conn.execute(
            """
            SELECT
                profile,
                COALESCE(trade_count, 0)  AS trades,
                COALESCE(win_count, 0)    AS win_count,
                COALESCE(total_pnl, 0.0)  AS total_pnl,
                COALESCE(avg_pnl, 0.0)    AS avg_pnl
            FROM profile_performance_daily
            WHERE trade_date = ?
            ORDER BY profile
            """,
            (trade_date,),
        ).fetchall()
    except Exception as exc:
        logger.warning("WARN: profile_performance_daily query failed: %s", exc)
        return []

    items: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        trades = int(item.get("trades") or 0)
        win_count = int(item.get("win_count") or 0)
        loss_count = max(0, trades - win_count)
        item["trades"] = trades
        item["win_count"] = win_count
        item["loss_count"] = loss_count
        item["total_pnl"] = float(item.get("total_pnl") or 0.0)
        item["win_rate_pct"] = round(win_count / trades * 100) if trades > 0 else 0
        items.append(item)
    return items


def _get_morning_context(conn: Any, trade_date: str) -> dict[str, Any] | None:
    """Return market regime context for a trade date, including parsed VIX/KOSPI values.

    Args:
        conn: Open SQLite connection.
        trade_date: Trading day in YYYY-MM-DD format.
    """
    try:
        row = conn.execute(
            "SELECT regime, risk_level, market_data FROM morning_context WHERE trade_date = ?",
            (trade_date,),
        ).fetchone()
    except Exception as exc:
        logger.warning("WARN: GET /api/v1/regime/day-detail morning_context unavailable error=%s", exc)
        return None
    if row is None:
        return None
    item = dict(row)
    market_data = _json_loads(item.get("market_data"), {})
    return {
        "regime": item.get("regime"),
        "risk_level": item.get("risk_level"),
        "vix": (market_data.get("vix") or {}).get("price") if isinstance(market_data, dict) else None,
        "kospi_change_pct": (market_data.get("kospi") or {}).get("change_pct") if isinstance(market_data, dict) else None,
    }


@router.get("/sets")
async def list_sets(active_only: bool = Query(True)) -> dict:
    """Return all Regime Sets visible to the backend console."""
    logger.info("START: GET /api/v1/regime/sets active_only=%s", active_only)
    try:
        items = get_all_sets(active_only=active_only)
        logger.info("SUCCESS: GET /api/v1/regime/sets count=%d", len(items))
        return {"ok": True, "items": items, "count": len(items)}
    except Exception as exc:
        logger.error("FAIL: GET /api/v1/regime/sets error=%s", exc)
        return {"ok": False, "items": [], "count": 0, "message": "Regime Set 목록 조회 중 서버 오류가 발생했습니다."}


@router.put("/sets/{set_id}")
async def update_regime_set(
    set_id: str = Path(...),
    body: RegimeSetUpdateRequest = Body(...),
) -> dict:
    """Update one Regime Set and merge settings as a partial JSON update.

    Args:
        set_id: Regime Set identifier.
        body: Partial update fields. Only non-null values are written.
    """
    logger.info("START: PUT /api/v1/regime/sets/%s", set_id)
    try:
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM regime_sets WHERE id = ?", (set_id,)).fetchone()
            if row is None:
                logger.warning("WARN: PUT /api/v1/regime/sets/%s not found", set_id)
                raise HTTPException(status_code=404, detail=f"Set not found: {set_id}")

            updated_fields: list[str] = []
            now = _now_kst()

            if body.name is not None:
                conn.execute("UPDATE regime_sets SET name = ?, updated_at = ? WHERE id = ?", (body.name, now, set_id))
                updated_fields.append("name")
            if body.description is not None:
                conn.execute(
                    "UPDATE regime_sets SET description = ?, updated_at = ? WHERE id = ?",
                    (body.description, now, set_id),
                )
                updated_fields.append("description")
            if body.is_active is not None:
                conn.execute(
                    "UPDATE regime_sets SET is_active = ?, updated_at = ? WHERE id = ?",
                    (1 if body.is_active else 0, now, set_id),
                )
                updated_fields.append("is_active")
            if body.trigger_conditions is not None:
                conn.execute(
                    "UPDATE regime_sets SET trigger_conditions = ?, updated_at = ? WHERE id = ?",
                    (_json_dumps(body.trigger_conditions), now, set_id),
                )
                updated_fields.append("trigger_conditions")
            if body.settings is not None:
                existing_settings = _json_loads(dict(row).get("settings"), {})
                if not isinstance(existing_settings, dict):
                    existing_settings = {}
                existing_settings.update(body.settings)
                conn.execute(
                    "UPDATE regime_sets SET settings = ?, updated_at = ? WHERE id = ?",
                    (_json_dumps(existing_settings), now, set_id),
                )
                updated_fields.append("settings")

            conn.commit()
        logger.info("SUCCESS: PUT /api/v1/regime/sets/%s updated_fields=%s", set_id, updated_fields)
        return {"ok": True, "set_id": set_id, "updated_fields": updated_fields}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("FAIL: PUT /api/v1/regime/sets/%s error=%s", set_id, exc)
        raise HTTPException(status_code=500, detail="Regime SET 수정 중 서버 오류가 발생했습니다.") from exc


@router.get("/today")
async def get_today_regime(trade_date: str | None = Query(default=None)) -> dict:
    """Return the active Regime Set application and all transitions for a trade date."""
    target_date = trade_date or _today_kst()
    logger.info("START: GET /api/v1/regime/today trade_date=%s", target_date)
    try:
        application = get_today_application(target_date)
        transitions = get_today_transitions(target_date)
        logger.info(
            "SUCCESS: GET /api/v1/regime/today found=%s transitions=%d",
            application is not None,
            len(transitions),
        )
        return {
            "ok": True,
            "date": target_date,
            "application": application,
            "transitions": transitions,
            "transition_count": len(transitions),
        }
    except Exception as exc:
        logger.error("FAIL: GET /api/v1/regime/today trade_date=%s error=%s", target_date, exc)
        return {
            "ok": False,
            "date": target_date,
            "application": None,
            "transitions": [],
            "transition_count": 0,
            "message": "오늘 적용 Regime Set 조회 중 서버 오류가 발생했습니다.",
        }


@router.get("/day-detail")
async def get_day_detail(trade_date: str = Query(...)) -> dict:
    """Return regime application and profile performance details for one trading day.

    Args:
        trade_date: Trading day in YYYY-MM-DD format.
    """
    logger.info("START: GET /api/v1/regime/day-detail trade_date=%s", trade_date)
    try:
        with get_connection() as conn:
            app_row = conn.execute(
                """
                SELECT * FROM regime_set_applications
                WHERE trade_date = ? AND current_flag = 1
                ORDER BY applied_at DESC, created_at DESC
                LIMIT 1
                """,
                (trade_date,),
            ).fetchone()

            regime_application = None
            if app_row is not None:
                app = dict(app_row)
                set_row = conn.execute(
                    "SELECT is_prebuilt FROM regime_sets WHERE id = ?",
                    (app.get("set_id"),),
                ).fetchone()
                app["is_prebuilt"] = bool(set_row["is_prebuilt"]) if set_row else False
                app["applied_settings"] = _json_loads(app.get("applied_settings"), {})
                regime_application = app

            profile_breakdown = _get_profile_breakdown(conn, trade_date)
            morning_context = _get_morning_context(conn, trade_date)

        logger.info(
            "SUCCESS: GET /api/v1/regime/day-detail trade_date=%s application=%s profiles=%d morning_context=%s",
            trade_date,
            regime_application is not None,
            len(profile_breakdown),
            morning_context is not None,
        )
        return {
            "ok": True,
            "trade_date": trade_date,
            "regime_application": regime_application,
            "profile_breakdown": profile_breakdown,
            "morning_context": morning_context,
        }
    except Exception as exc:
        logger.error("FAIL: GET /api/v1/regime/day-detail trade_date=%s error=%s", trade_date, exc)
        return {
            "ok": False,
            "trade_date": trade_date,
            "regime_application": None,
            "profile_breakdown": [],
            "morning_context": None,
            "message": "거래일 Regime 상세 조회 중 서버 오류가 발생했습니다.",
        }


@router.get("/history")
async def get_regime_history(days: int = Query(default=30, ge=1, le=365)) -> dict:
    """Return recent Regime Set application history."""
    logger.info("START: GET /api/v1/regime/history days=%s", days)
    try:
        items = get_set_history(days=days)
        logger.info("SUCCESS: GET /api/v1/regime/history count=%d", len(items))
        return {"ok": True, "items": items, "count": len(items)}
    except Exception as exc:
        logger.error("FAIL: GET /api/v1/regime/history error=%s", exc)
        return {"ok": False, "items": [], "count": 0, "message": "Regime Set 이력 조회 중 서버 오류가 발생했습니다."}


@router.get("/preview")
async def preview_match(
    regime_label: str = Query(default="neutral"),
    vix: float | None = Query(default=None),
    kospi_change_pct: float | None = Query(default=None),
    trade_date: str | None = Query(default=None),
) -> dict:
    """Simulate which Regime Set would match the provided market conditions."""
    target_date = trade_date or _today_kst()
    logger.info(
        "START: GET /api/v1/regime/preview trade_date=%s regime=%s vix=%s kospi=%s",
        target_date,
        regime_label,
        vix,
        kospi_change_pct,
    )
    try:
        preview = get_match_preview(regime_label, vix, kospi_change_pct, target_date)
        logger.info("SUCCESS: GET /api/v1/regime/preview set_id=%s", preview.get("set_id"))
        return {"ok": True, "date": target_date, "preview": preview}
    except Exception as exc:
        logger.error("FAIL: GET /api/v1/regime/preview error=%s", exc)
        return {
            "ok": False,
            "date": target_date,
            "preview": None,
            "message": "Regime Set 매칭 미리보기 중 서버 오류가 발생했습니다.",
        }
