"""Missed Opportunity Tracker."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection

logger = logging.getLogger("MissedOpportunity")


def _now_kst_iso() -> str:
    """Return the current KST timestamp for missed opportunity rows."""
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()


def _row_to_dict(row: Any) -> dict[str, Any]:
    """Convert a SQLite row into a plain dictionary for API responses."""
    return dict(row)


def _validate_required(**values: Any) -> None:
    """Validate required missed opportunity fields before persistence."""
    missing = [name for name, value in values.items() if value in (None, "")]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")


def record_missed_opportunity(
    trade_date: str,
    symbol: str,
    symbol_name: str,
    missed_stage: str,
    missed_reason: str,
    price_at_missed: float,
    max_10m: float | None = None,
    max_30m: float | None = None,
    max_eod: float | None = None,
    improvement_candidate: bool = False,
) -> dict:
    """Persist a missed opportunity and its post-miss return evidence.

    Args:
        trade_date: YYYY-MM-DD trade date.
        symbol: Stock symbol that was missed.
        symbol_name: Display name for the symbol.
        missed_stage: Pipeline stage where the symbol was missed.
        missed_reason: Human-readable missed reason.
        price_at_missed: Price observed when the opportunity was missed.
        max_10m: Maximum return after 10 minutes.
        max_30m: Maximum return after 30 minutes.
        max_eod: Maximum return until end of day.
        improvement_candidate: Whether this row should be reviewed for improvement.
    """
    logger.info("START: MissedOpportunity record symbol=%s trade_date=%s", symbol, trade_date)
    _validate_required(
        trade_date=trade_date,
        symbol=symbol,
        missed_stage=missed_stage,
        missed_reason=missed_reason,
    )
    row_id = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO missed_opportunities
                (id, trade_date, symbol, symbol_name, missed_stage, missed_reason,
                 price_at_missed, max_return_after_10m, max_return_after_30m,
                 max_return_until_eod, improvement_candidate, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row_id,
                trade_date,
                symbol,
                symbol_name or "",
                missed_stage,
                missed_reason,
                float(price_at_missed or 0.0),
                max_10m,
                max_30m,
                max_eod,
                1 if improvement_candidate else 0,
                _now_kst_iso(),
            ),
        )
        row = conn.execute("SELECT * FROM missed_opportunities WHERE id = ?", (row_id,)).fetchone()
    logger.info("SUCCESS: MissedOpportunity record id=%s symbol=%s", row_id, symbol)
    return _row_to_dict(row)


def get_today_missed(trade_date: str) -> list[dict]:
    """Return missed opportunities for one trade date.

    Args:
        trade_date: YYYY-MM-DD trade date.
    """
    logger.info("START: MissedOpportunity list trade_date=%s", trade_date)
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM missed_opportunities WHERE trade_date = ? ORDER BY created_at DESC",
            (trade_date,),
        ).fetchall()
    logger.info("SUCCESS: MissedOpportunity list trade_date=%s count=%d", trade_date, len(rows))
    return [_row_to_dict(row) for row in rows]


def get_improvement_candidates(trade_date: str) -> list[dict]:
    """Return same-day missed opportunities marked as improvement candidates.

    Args:
        trade_date: YYYY-MM-DD trade date.
    """
    logger.info("START: MissedOpportunity candidates trade_date=%s", trade_date)
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM missed_opportunities
            WHERE trade_date = ? AND improvement_candidate = 1
            ORDER BY created_at DESC
            """,
            (trade_date,),
        ).fetchall()
    logger.info("SUCCESS: MissedOpportunity candidates trade_date=%s count=%d", trade_date, len(rows))
    return [_row_to_dict(row) for row in rows]


def _parse_miss_time(created_at: str) -> datetime | None:
    """Parse created_at ISO string into a KST-aware datetime."""
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(created_at[:26], fmt[:len(fmt)])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo("Asia/Seoul"))
            return dt
        except ValueError:
            continue
    return None


def _add_minutes_hhmmss(base_hhmmss: str, minutes: int) -> str:
    """Add minutes to a HHMMSS string and return HHMMSS."""
    h = int(base_hhmmss[:2])
    m = int(base_hhmmss[2:4])
    s = int(base_hhmmss[4:6])
    dt = datetime(2000, 1, 1, h, m, s) + timedelta(minutes=minutes)
    return dt.strftime("%H%M%S")


def _find_closest_price(candles: list[dict], target_hhmmss: str) -> float | None:
    """Find the closing price in candles closest to target_hhmmss (HHMMSS)."""
    target_min = int(target_hhmmss[:2]) * 60 + int(target_hhmmss[2:4])
    best_price: float | None = None
    best_diff = 9999
    for c in candles:
        t = str(c.get("stck_cntg_hour", "") or c.get("stck_bsop_hour", ""))
        if len(t) < 6:
            continue
        c_min = int(t[:2]) * 60 + int(t[2:4])
        diff = abs(c_min - target_min)
        if diff < best_diff:
            best_diff = diff
            v = c.get("stck_prpr") or c.get("stck_clpr")
            try:
                best_price = float(v)
            except (TypeError, ValueError):
                pass
    return best_price if best_diff <= 10 else None  # 10분 이내 candle만 사용


async def update_missed_returns(trade_date: str, improvement_threshold: float = 2.0) -> dict[str, Any]:
    """EOD에 미진입 종목들의 실제 수익률을 계산하여 DB를 업데이트한다.

    - 10분 후 / 30분 후: get_intraday_chart() 로 분봉 데이터 조회
    - 장마감: get_daily_chart() 로 당일 종가 조회
    - improvement_candidate: max_return_until_eod >= improvement_threshold(%) 이면 1

    Args:
        trade_date: YYYY-MM-DD 형식 거래일.
        improvement_threshold: 개선 후보 판정 최소 수익률(%). 기본값 2.0%.
    """
    logger.info("START: MissedOpportunity update_returns trade_date=%s", trade_date)

    # 아직 업데이트되지 않은 레코드만 조회 (max_return_after_10m IS NULL)
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, symbol, price_at_missed, created_at
            FROM missed_opportunities
            WHERE trade_date = ? AND max_return_after_10m IS NULL AND price_at_missed > 0
            ORDER BY created_at
            """,
            (trade_date,),
        ).fetchall()

    if not rows:
        logger.info("SKIP: MissedOpportunity update_returns — no pending rows trade_date=%s", trade_date)
        return {"updated": 0, "skipped": 0, "errors": 0}

    from ..kis.domestic.service import get_daily_chart, get_intraday_chart

    updated = skipped = errors = 0

    for row in rows:
        row_id: str = row["id"]
        symbol: str = row["symbol"]
        price_at_missed: float = float(row["price_at_missed"])
        created_at_str: str = row["created_at"]

        try:
            miss_dt = _parse_miss_time(created_at_str)
            miss_hhmmss = miss_dt.strftime("%H%M%S") if miss_dt else "093000"

            # ── 분봉 데이터: miss 시각 +35분 기준으로 30개 candle 조회
            target_hour = _add_minutes_hhmmss(miss_hhmmss, 35)
            intraday_resp = await get_intraday_chart(symbol=symbol, input_hour=target_hour, include_past="Y")
            candles: list[dict] = intraday_resp.get("output2") or []

            t10_hhmmss = _add_minutes_hhmmss(miss_hhmmss, 10)
            t30_hhmmss = _add_minutes_hhmmss(miss_hhmmss, 30)
            price_10m = _find_closest_price(candles, t10_hhmmss)
            price_30m = _find_closest_price(candles, t30_hhmmss)

            ret_10m = round((price_10m - price_at_missed) / price_at_missed * 100, 4) if price_10m else None
            ret_30m = round((price_30m - price_at_missed) / price_at_missed * 100, 4) if price_30m else None

            # ── 당일 종가
            daily_resp = await get_daily_chart(symbol=symbol, period_code="D", adjusted_price="1")
            daily_rows: list[dict] = daily_resp.get("output") or []
            close_price: float | None = None
            if daily_rows:
                try:
                    close_price = float(daily_rows[0].get("stck_clpr", 0) or 0) or None
                except (TypeError, ValueError):
                    close_price = None

            ret_eod = (
                round((close_price - price_at_missed) / price_at_missed * 100, 4)
                if close_price and close_price > 0
                else None
            )

            is_candidate = 1 if (ret_eod is not None and ret_eod >= improvement_threshold) else 0

            with get_connection() as conn:
                conn.execute(
                    """
                    UPDATE missed_opportunities
                    SET max_return_after_10m = ?,
                        max_return_after_30m = ?,
                        max_return_until_eod = ?,
                        improvement_candidate = ?
                    WHERE id = ?
                    """,
                    (ret_10m, ret_30m, ret_eod, is_candidate, row_id),
                )

            logger.info(
                "UPDATED: MissedOpportunity id=%s symbol=%s ret10m=%s ret30m=%s retEOD=%s candidate=%d",
                row_id, symbol, ret_10m, ret_30m, ret_eod, is_candidate,
            )
            updated += 1

        except Exception as exc:
            logger.warning("WARN: MissedOpportunity update id=%s symbol=%s error=%s", row_id, symbol, exc)
            errors += 1

        # KIS API rate limit 보호
        await asyncio.sleep(0.15)

    logger.info(
        "SUCCESS: MissedOpportunity update_returns trade_date=%s updated=%d skipped=%d errors=%d",
        trade_date, updated, skipped, errors,
    )
    return {"updated": updated, "skipped": skipped, "errors": errors}
