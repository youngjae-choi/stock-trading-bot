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


def _build_empty_reason(
    *,
    has_s3: bool,
    has_s4: bool,
    has_s5: bool,
    layer1_count: int,
    layer2_count: int,
) -> str:
    """Return a PM-facing reason for missing downstream Funnel stages.

    Args:
        has_s3: Whether today's S3 universe filter result exists.
        has_s4: Whether today's S4 screening result exists.
        has_s5: Whether today's S5 daily plan result exists.
        layer1_count: S3 filtered_count for the latest S3 row.
        layer2_count: S4 output_count for the latest S4 row.
    """
    if not has_s3:
        return "오늘 S3 유니버스 필터 결과가 아직 없습니다."
    if layer1_count == 0:
        return "S3는 실행됐으나 통과 종목 0개라 S4/S5 미생성"
    if not has_s4:
        return "S3 통과 종목은 있으나 오늘 S4 스크리닝 결과가 아직 없습니다."
    if layer2_count == 0:
        return "S4는 실행됐으나 후보 종목 0개라 S5 미생성"
    if not has_s5:
        return "S4 후보 종목은 있으나 오늘 S5 Daily Plan 결과가 아직 없습니다."
    return ""


@router.get("/intraday-refresh")
async def get_intraday_refresh_status(date: str = None):
    """특정 날짜 장중 재선별 이력 조회 (date 미지정 시 오늘)."""
    from ...services.engine.intraday_refresh import get_today_refresh_status
    trade_date = date or _today_kst()
    history = get_today_refresh_status(trade_date)
    return {"ok": True, "payload": {"trade_date": trade_date, "history": history}}


@router.get("/summary")
async def get_funnel_summary():
    """Return today's Funnel stage counts from persisted DB data."""
    today = _today_kst()
    endpoint = "/api/v1/funnel/summary"
    logger.info("START: GET %s trade_date=%s", endpoint, today)
    try:
        with get_connection() as conn:
            # Step 0: Canonical active-universe count for the overall market.
            total_universe = 0
            total_universe_source = "symbols.is_active=1 DB count"
            if _table_exists(conn, "symbols"):
                market_row = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM symbols WHERE is_active = 1"
                ).fetchone()
                total_universe = int(market_row["cnt"] or 0) if market_row else 0

            # Step 1: Read the latest S3 Universe Filter result when the table exists.
            uf_row = None
            if _table_exists(conn, "universe_filter_results"):
                uf_row = conn.execute(
                    "SELECT id, raw_count, filtered_count, created_at FROM universe_filter_results"
                    " WHERE trade_date = ? ORDER BY created_at DESC LIMIT 1",
                    (today,),
                ).fetchone()

            # Step 2: Read the latest S4 Hybrid Screening result when the table exists.
            sc_row = None
            if _table_exists(conn, "hybrid_screening_results"):
                sc_row = conn.execute(
                    "SELECT id, raw_input_count, output_count, created_at FROM hybrid_screening_results"
                    " WHERE trade_date = ? ORDER BY created_at DESC LIMIT 1",
                    (today,),
                ).fetchone()

            # Step 3: Count today's BUY signals.
            sig_count = conn.execute(
                "SELECT COUNT(*) FROM trading_signals WHERE trade_date = ? AND signal_type = 'BUY'",
                (today,),
            ).fetchone()[0]

            # Step 4: Read the active or validated daily plan for profile distribution.
            plan_row = conn.execute(
                "SELECT id, symbol_assignments, created_at FROM daily_trading_plans"
                " WHERE trade_date = ? AND status IN ('active', 'validated')"
                " ORDER BY created_at DESC LIMIT 1",
                (today,),
            ).fetchone()

        # position_manager가 실시간 보유 종목 수를 관리 (position_stop_states는 전체 추적 기록이라 부적합)
        pos_count = 0
        try:
            from ...services.engine.position_manager import position_manager
            pos_count = len(position_manager.get_positions())
        except Exception:
            pass

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
        has_s3 = uf_row is not None
        has_s4 = sc_row is not None
        has_s5 = plan_row is not None
        if total_universe <= 0 and layer1_raw > 0:
            total_universe = layer1_raw
            total_universe_source = "universe_filter_results.raw_count fallback"
        updated_candidates = [
            row["created_at"]
            for row in (uf_row, sc_row, plan_row)
            if row is not None and row["created_at"]
        ]
        # 장중 재선별 이력 (system_settings 저장값)
        intraday_history = []
        try:
            from ...services.engine.intraday_refresh import get_today_refresh_status
            intraday_history = get_today_refresh_status(today)
        except Exception:
            pass

        payload = {
            "trade_date": today,
            "total_universe": total_universe,
            "total_universe_source": total_universe_source,
            "layer1_raw": layer1_raw,
            "layer1_count": layer1_count,
            "layer1_rejected": max(0, layer1_raw - layer1_count),
            "layer1_rejection_breakdown": [],
            "layer2_count": layer2_count,
            "signals_count": int(sig_count),
            "positions_count": int(pos_count),
            "profile_counts": profile_counts,
            "has_s3": has_s3,
            "has_s4": has_s4,
            "has_s5": has_s5,
            "empty_reason": _build_empty_reason(
                has_s3=has_s3,
                has_s4=has_s4,
                has_s5=has_s5,
                layer1_count=layer1_count,
                layer2_count=layer2_count,
            ),
            "last_updated_at": max(updated_candidates) if updated_candidates else "",
            "intraday_refresh_history": intraday_history,
        }
        logger.info("SUCCESS: GET %s payload=%s", endpoint, payload)
        return {"ok": True, "payload": payload}
    except Exception as exc:
        logger.error("FAIL: GET %s - %s", endpoint, exc)
        return JSONResponse(status_code=500, content={"ok": False, "error": "FUNNEL_SUMMARY_FAILED"})


def _funnel_loads(text, default):
    """Parse a JSON column value, returning default on any failure."""
    try:
        return json.loads(text) if text else default
    except (TypeError, ValueError):
        return default


def _funnel_dropped(conn, trade_date: str, stage: str) -> list[dict]:
    """Read dropped (filtered-out) stocks for one funnel stage from missed_opportunities."""
    if not _table_exists(conn, "missed_opportunities"):
        return []
    rows = conn.execute(
        "SELECT symbol, symbol_name, missed_reason, price_at_missed FROM missed_opportunities"
        " WHERE trade_date = ? AND missed_stage = ? ORDER BY created_at",
        (trade_date, stage),
    ).fetchall()
    return [
        {
            "symbol": r["symbol"],
            "name": r["symbol_name"],
            "reason": r["missed_reason"],
            "price": r["price_at_missed"],
        }
        for r in rows
    ]


@router.get("/selection")
async def get_selection_funnel(trade_date: str | None = None):
    """Return the per-stock selection funnel: passed/dropped stocks with reasons at each stage.

    전체 → S3 유니버스 → S4 스크리닝 → S5 Daily Plan 각 단계의 통과·탈락 종목 명단(+사유).
    """
    td = trade_date or _today_kst()
    endpoint = "/api/v1/funnel/selection"
    logger.info("START: GET %s trade_date=%s", endpoint, td)
    try:
        with get_connection() as conn:
            # raw_count + S3 통과 (universe_filter_results)
            raw_count = 0
            s3_passed: list[dict] = []
            if _table_exists(conn, "universe_filter_results"):
                uf = conn.execute(
                    "SELECT raw_count, items FROM universe_filter_results"
                    " WHERE trade_date = ? ORDER BY created_at DESC LIMIT 1",
                    (td,),
                ).fetchone()
                if uf:
                    raw_count = int(uf["raw_count"] or 0)
                    items = _funnel_loads(uf["items"], [])
                    if isinstance(items, list):
                        for it in items:
                            if not isinstance(it, dict):
                                continue
                            s3_passed.append({
                                "symbol": it.get("symbol"),
                                "name": it.get("name"),
                                "score": it.get("score"),
                                "rank": it.get("rank"),
                                "change_rate": it.get("change_rate"),
                                "volume_surge": it.get("volume_surge"),
                                "price": it.get("price"),
                            })

            # S4 통과 (hybrid_screening_results.candidates)
            s4_passed: list[dict] = []
            if _table_exists(conn, "hybrid_screening_results"):
                sc = conn.execute(
                    "SELECT candidates FROM hybrid_screening_results"
                    " WHERE trade_date = ? ORDER BY created_at DESC LIMIT 1",
                    (td,),
                ).fetchone()
                if sc:
                    cands = _funnel_loads(sc["candidates"], [])
                    if isinstance(cands, list):
                        for c in cands:
                            if not isinstance(c, dict):
                                continue
                            s4_passed.append({
                                "symbol": c.get("ticker") or c.get("symbol"),
                                "name": c.get("name"),
                                "sector": c.get("sector"),
                                "score": c.get("suitability_score"),
                                "reason": c.get("reason"),
                                "selection_source": c.get("selection_source"),
                            })

            # S5 통과 (daily_trading_plans.symbol_assignments)
            s5_passed: list[dict] = []
            if _table_exists(conn, "daily_trading_plans"):
                dp = conn.execute(
                    "SELECT symbol_assignments FROM daily_trading_plans"
                    " WHERE trade_date = ? ORDER BY created_at DESC LIMIT 1",
                    (td,),
                ).fetchone()
                if dp:
                    sa = _funnel_loads(dp["symbol_assignments"], [])
                    if isinstance(sa, list):
                        for a in sa:
                            if not isinstance(a, dict):
                                continue
                            s5_passed.append({
                                "symbol": a.get("code") or a.get("symbol"),
                                "name": a.get("name"),
                                "profile": a.get("profile"),
                                "reason": a.get("reason"),
                            })

            s3_dropped = _funnel_dropped(conn, td, "S3_UNIVERSE_FILTER")
            s4_dropped = _funnel_dropped(conn, td, "S4_HYBRID_SCREENING")
            s5_dropped = _funnel_dropped(conn, td, "S5_DAILY_PLAN")

        stages = [
            {"id": "raw", "label": "전체 종목", "passed_count": raw_count},
            {"id": "s3", "label": "S3 유니버스 필터", "subtitle": "등락률+거래량급증",
             "passed_count": len(s3_passed), "passed": s3_passed,
             "dropped_count": len(s3_dropped), "dropped": s3_dropped},
            {"id": "s4", "label": "S4 하이브리드 스크리닝", "subtitle": "LLM 정성 평가",
             "passed_count": len(s4_passed), "passed": s4_passed,
             "dropped_count": len(s4_dropped), "dropped": s4_dropped},
            {"id": "s5", "label": "S5 Daily Plan", "subtitle": "Profile 배정",
             "passed_count": len(s5_passed), "passed": s5_passed,
             "dropped_count": len(s5_dropped), "dropped": s5_dropped},
        ]
        logger.info(
            "SUCCESS: GET %s s3=%d/%d s4=%d/%d s5=%d/%d",
            endpoint, len(s3_passed), len(s3_dropped),
            len(s4_passed), len(s4_dropped), len(s5_passed), len(s5_dropped),
        )
        return {"ok": True, "payload": {"trade_date": td, "stages": stages}}
    except Exception as exc:
        logger.error("FAIL: GET %s - %s", endpoint, exc)
        return JSONResponse(status_code=500, content={"ok": False, "error": "FUNNEL_SELECTION_FAILED"})
