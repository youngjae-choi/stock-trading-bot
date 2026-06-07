"""Missed Opportunity Tracker."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
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


def _to_float(value: Any) -> float | None:
    """안전 float 변환. None/0/빈문자/파싱실패 시 None."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out > 0 else None


async def update_missed_returns(trade_date: str, improvement_threshold: float = 2.0) -> dict[str, Any]:
    """EOD에 미진입 종목들의 장중 최고/최저 상승률을 계산하여 DB를 업데이트한다.

    측정값은 [제외시점가 · 장중 최고가 · 장중 최저가] 3개만 사용한다(분봉 10m/30m 폐기).
    일봉(get_daily_chart)을 종목당 1회만 호출해 daily_rows[0]의 stck_hgpr/stck_lwpr를 읽는다.

    - intraday_high_return = (stck_hgpr - price_at_missed) / price_at_missed * 100
    - intraday_low_return  = (stck_lwpr - price_at_missed) / price_at_missed * 100  (음수 가능)
    - improvement_candidate = 1 if intraday_high_return >= improvement_threshold(설정값)
    - 저장: max_return_until_eod = intraday_high_return(장중 최고가 상승률로 의미 재정의),
            intraday_low_return = intraday_low_return.
      (max_return_after_10m/30m 은 더 이상 채우지 않음 = NULL 유지)

    Args:
        trade_date: YYYY-MM-DD 형식 거래일.
        improvement_threshold: 개선 후보 판정 최소 상승률(%). 호출부에서 명시하지 않으면(기본 2.0)
            settings 의 missed.improvement_threshold 값으로 보정한다.
    """
    logger.info("START: MissedOpportunity update_returns trade_date=%s", trade_date)

    # 임계치 설정값 보정: 명시값(기본 2.0)이 들어오면 설정값으로 덮어쓴다.
    if improvement_threshold == 2.0:
        try:
            from ..settings_store import get_setting

            setting_val = get_setting("missed.improvement_threshold", 2.0)
            improvement_threshold = float(setting_val)
        except (TypeError, ValueError, Exception) as exc:  # noqa: BLE001 - 설정 조회 실패 시 기본값 유지
            logger.warning("WARN: missed.improvement_threshold read failed, using default=%s error=%s", improvement_threshold, exc)

    # 아직 업데이트되지 않은 레코드만 조회 (max_return_until_eod IS NULL)
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, symbol, price_at_missed, created_at
            FROM missed_opportunities
            WHERE trade_date = ? AND max_return_until_eod IS NULL AND price_at_missed > 0
            ORDER BY created_at
            """,
            (trade_date,),
        ).fetchall()

    if not rows:
        logger.info("SKIP: MissedOpportunity update_returns — no pending rows trade_date=%s", trade_date)
        return {"updated": 0, "skipped": 0, "errors": 0}

    from ..kis.domestic.service import get_daily_chart

    updated = skipped = errors = 0

    for row in rows:
        row_id: str = row["id"]
        symbol: str = row["symbol"]
        price_at_missed: float = float(row["price_at_missed"])

        try:
            # ── 일봉 1회 호출: 당일 장중 최고가/최저가
            daily_resp = await get_daily_chart(symbol=symbol, period_code="D", adjusted_price="1")
            daily_rows: list[dict] = daily_resp.get("output") or []
            high_price: float | None = None
            low_price: float | None = None
            if daily_rows:
                high_price = _to_float(daily_rows[0].get("stck_hgpr"))
                low_price = _to_float(daily_rows[0].get("stck_lwpr"))

            intraday_high_return = (
                round((high_price - price_at_missed) / price_at_missed * 100, 4)
                if high_price is not None
                else None
            )
            intraday_low_return = (
                round((low_price - price_at_missed) / price_at_missed * 100, 4)
                if low_price is not None
                else None
            )

            is_candidate = 1 if (intraday_high_return is not None and intraday_high_return >= improvement_threshold) else 0

            with get_connection() as conn:
                conn.execute(
                    """
                    UPDATE missed_opportunities
                    SET max_return_until_eod = ?,
                        intraday_low_return = ?,
                        improvement_candidate = ?
                    WHERE id = ?
                    """,
                    (intraday_high_return, intraday_low_return, is_candidate, row_id),
                )

            logger.info(
                "UPDATED: MissedOpportunity id=%s symbol=%s high=%s low=%s candidate=%d",
                row_id, symbol, intraday_high_return, intraday_low_return, is_candidate,
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
