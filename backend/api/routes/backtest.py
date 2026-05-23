"""Backtest API routes."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/v1/backtest", tags=["backtest"])
logger = logging.getLogger("BacktestAPI")


def _to_float(value: Any, default: float) -> float:
    """Convert a setting value to float with a defensive fallback.

    Args:
        value: Raw setting value from persistent settings.
        default: Value returned when conversion fails.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_symbols(symbols: str | None) -> list[str] | None:
    """Parse comma-separated stock codes from the API query string.

    Args:
        symbols: Comma-separated KRX stock codes, for example "005930,000660".
    """
    if not symbols:
        return None
    parsed = [item.strip().zfill(6) for item in symbols.split(",") if item.strip()]
    return parsed or None


async def _execute_backtest(
    start_date: str,
    end_date: str,
    symbols: list[str] | None,
    min_price_change_pct: float,
    max_price_change_pct: float,
    min_volume_ratio: float,
    entry_start: str,
    entry_end: str,
    stop_loss_pct: float,
    trailing_activate_pct: float,
    trailing_stop_pct: float,
    universe_limit: int,
) -> dict[str, Any]:
    """Run the service layer and convert validation failures to API errors.

    Args:
        start_date: Backtest start date in YYYY-MM-DD.
        end_date: Backtest end date in YYYY-MM-DD.
        symbols: Optional explicit stock-code universe.
        min_price_change_pct: Minimum intraday price change percentage.
        max_price_change_pct: Maximum intraday price change percentage.
        min_volume_ratio: Minimum cumulative volume ratio.
        entry_start: Earliest allowed entry time in HH:MM.
        entry_end: Latest allowed entry time in HH:MM.
        stop_loss_pct: Stop loss threshold as decimal return.
        trailing_activate_pct: Return threshold that activates trailing stop.
        trailing_stop_pct: Pullback from peak that triggers trailing stop.
        universe_limit: Maximum universe size.
    """
    from ...services.engine.backtest import run_backtest as run_backtest_service

    try:
        return await run_backtest_service(
            start_date=start_date,
            end_date=end_date,
            symbols=symbols,
            min_price_change_pct=min_price_change_pct,
            max_price_change_pct=max_price_change_pct,
            min_volume_ratio=min_volume_ratio,
            entry_start=entry_start,
            entry_end=entry_end,
            stop_loss_pct=stop_loss_pct,
            trailing_activate_pct=trailing_activate_pct,
            trailing_stop_pct=trailing_stop_pct,
            universe_limit=universe_limit,
        )
    except ValueError as exc:
        logger.warning("WARN: BacktestAPI validation failed error=%s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("FAIL: BacktestAPI execution failed error=%s", exc)
        raise HTTPException(status_code=500, detail="백테스트 실행 중 서버 오류가 발생했습니다.") from exc


@router.post("/run")
async def run_backtest(
    start_date: str = Query(..., description="YYYY-MM-DD"),
    end_date: str = Query(..., description="YYYY-MM-DD"),
    symbols: str | None = Query(None, description="Comma-separated stock codes, e.g. 005930,000660"),
    min_price_change_pct: float = Query(3.0),
    max_price_change_pct: float = Query(10.0),
    min_volume_ratio: float = Query(2.5),
    entry_start: str = Query("09:00"),
    entry_end: str = Query("10:30"),
    stop_loss_pct: float = Query(-0.015),
    trailing_activate_pct: float = Query(0.02),
    trailing_stop_pct: float = Query(0.01),
    universe_limit: int = Query(30, ge=1, le=100),
) -> dict[str, Any]:
    """Run a parameterized intraday backtest using KIS minute bars."""
    logger.info("START: POST /api/v1/backtest/run start=%s end=%s", start_date, end_date)
    result = await _execute_backtest(
        start_date=start_date,
        end_date=end_date,
        symbols=_parse_symbols(symbols),
        min_price_change_pct=min_price_change_pct,
        max_price_change_pct=max_price_change_pct,
        min_volume_ratio=min_volume_ratio,
        entry_start=entry_start,
        entry_end=entry_end,
        stop_loss_pct=stop_loss_pct,
        trailing_activate_pct=trailing_activate_pct,
        trailing_stop_pct=trailing_stop_pct,
        universe_limit=universe_limit,
    )
    logger.info("SUCCESS: POST /api/v1/backtest/run total=%s", result.get("total", 0))
    return {"ok": True, "payload": result}


def _previous_weekday() -> str:
    """Return the most recent weekday before today as YYYY-MM-DD."""
    day = datetime.now() - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day.strftime("%Y-%m-%d")


async def _quick_backtest_payload() -> dict[str, Any]:
    """Build and execute the default one-day quick backtest."""
    from ...services.settings_store import get_setting
    from ...services.engine.backtest import get_universe_symbols

    target_date = _previous_weekday()
    symbols = get_universe_symbols(30)
    min_price_change_pct = _to_float(get_setting("engine.min_price_change_pct", 3.0), 3.0)
    max_price_change_pct = _to_float(get_setting("engine.max_price_change_pct", 10.0), 10.0)
    min_volume_ratio = _to_float(get_setting("engine.min_volume_ratio", 2.5), 2.5)
    stop_loss_pct = _to_float(get_setting("override_stop_loss_rate", -0.015), -0.015)
    trailing_activate_pct = _to_float(get_setting("override_trailing_activate_rate", 0.02), 0.02)
    trailing_stop_pct = _to_float(get_setting("override_trailing_stop_rate", 0.01), 0.01)
    return await _execute_backtest(
        start_date=target_date,
        end_date=target_date,
        symbols=symbols,
        min_price_change_pct=min_price_change_pct,
        max_price_change_pct=max_price_change_pct,
        min_volume_ratio=min_volume_ratio,
        entry_start=str(get_setting("engine.entry_start_time", "09:00") or "09:00"),
        entry_end=str(get_setting("engine.entry_end_time", "10:30") or "10:30"),
        stop_loss_pct=stop_loss_pct,
        trailing_activate_pct=trailing_activate_pct,
        trailing_stop_pct=trailing_stop_pct,
        universe_limit=30,
    )


@router.get("/quick")
async def quick_backtest() -> dict[str, Any]:
    """Run a one-day quick backtest with persisted engine settings."""
    logger.info("START: GET /api/v1/backtest/quick")
    result = await _quick_backtest_payload()
    logger.info("SUCCESS: GET /api/v1/backtest/quick total=%s", result.get("total", 0))
    return {"ok": True, "payload": result}


@router.post("/quick")
async def quick_backtest_post() -> dict[str, Any]:
    """Run the quick backtest through POST for the documented curl smoke test."""
    logger.info("START: POST /api/v1/backtest/quick")
    result = await _quick_backtest_payload()
    logger.info("SUCCESS: POST /api/v1/backtest/quick total=%s", result.get("total", 0))
    return {"ok": True, "payload": result}
