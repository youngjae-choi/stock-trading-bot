"""Intraday backtest engine using KIS minute bars and pykrx reference data."""

from __future__ import annotations

import json
import logging
import statistics
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger("Backtest")


def _normalize_symbol(value: Any) -> str:
    """Normalize a candidate symbol value into a six-digit KRX code.

    Args:
        value: Raw symbol, ticker, or code value from persisted candidates.
    """
    symbol = str(value or "").strip()
    if not symbol:
        return ""
    return symbol.zfill(6) if symbol.isdigit() else symbol


def _symbols_from_screening_rows(limit: int) -> list[str]:
    """Load recent candidate symbols from hybrid_screening_results.

    Args:
        limit: Maximum unique symbols to return.
    """
    from ..db import get_connection

    symbols: list[str] = []
    seen: set[str] = set()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT candidates
            FROM hybrid_screening_results
            ORDER BY created_at DESC
            LIMIT 20
            """
        ).fetchall()

    for row in rows:
        try:
            candidates = json.loads(row["candidates"] or "[]")
        except Exception as exc:
            logger.warning("WARN: Backtest candidates JSON parse failed error=%s", exc)
            continue
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            symbol = _normalize_symbol(candidate.get("symbol") or candidate.get("ticker") or candidate.get("code"))
            if symbol and symbol not in seen:
                symbols.append(symbol)
                seen.add(symbol)
            if len(symbols) >= limit:
                return symbols
    return symbols


def get_universe_symbols(limit: int = 50) -> list[str]:
    """Return backtest universe symbols from screening history or KOSPI market cap.

    Args:
        limit: Maximum number of stock codes to return.
    """
    logger.info("START: Backtest universe load limit=%d", limit)
    try:
        symbols = _symbols_from_screening_rows(limit)
        if symbols:
            logger.info("SUCCESS: Backtest universe from DB count=%d", len(symbols))
            return symbols
    except Exception as exc:
        logger.warning("WARN: Backtest universe DB load failed error=%s", exc)

    try:
        from pykrx import stock

        today = datetime.now().strftime("%Y%m%d")
        df = stock.get_market_cap(today, market="KOSPI")
        if df is not None and len(df) > 0:
            symbols = [_normalize_symbol(symbol) for symbol in df.sort_values("시가총액", ascending=False).head(limit).index]
            logger.info("SUCCESS: Backtest universe from KOSPI market cap count=%d", len(symbols))
            return [symbol for symbol in symbols if symbol]
    except Exception as exc:
        logger.warning("WARN: Backtest universe KOSPI fallback failed error=%s", exc)

    logger.error("FAIL: Backtest universe unavailable")
    return []


def _parse_float(value: Any) -> float:
    """Parse KIS numeric strings into float values.

    Args:
        value: Raw KIS response value.
    """
    try:
        return float(str(value or "0").replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _parse_int(value: Any) -> int:
    """Parse KIS numeric strings into int values.

    Args:
        value: Raw KIS response value.
    """
    try:
        return int(float(str(value or "0").replace(",", "").strip()))
    except (TypeError, ValueError):
        return 0


def _bar_date(item: dict[str, Any]) -> str:
    """Extract a YYYYMMDD business date from a KIS minute-bar row when present.

    Args:
        item: One row from KIS output2.
    """
    for key in ("stck_bsop_date", "bsop_date", "date"):
        value = str(item.get(key) or "").strip()
        if len(value) == 8 and value.isdigit():
            return value
    return ""


async def fetch_intraday_bars(symbol: str, date_str: str) -> list[dict[str, Any]]:
    """Fetch KIS minute bars for one symbol.

    Args:
        symbol: Six-digit KRX stock code.
        date_str: Requested business date in YYYYMMDD. KIS minute chart rows are filtered
            by date only when the API includes a business-date field.
    """
    from ..kis.domestic.service import get_intraday_chart

    logger.info("START: Backtest KIS intraday symbol=%s date=%s", symbol, date_str)
    try:
        resp = await get_intraday_chart(symbol=symbol, input_hour="153000", include_past="Y")
    except Exception as exc:
        logger.warning("WARN: Backtest KIS intraday failed symbol=%s error=%s — pykrx fallback", symbol, exc)
        return []
    output2 = resp.get("output2") or []
    bars: list[dict[str, Any]] = []
    for item in output2:
        if not isinstance(item, dict):
            continue
        row_date = _bar_date(item)
        if row_date and row_date != date_str:
            continue
        raw_time = str(item.get("stck_cntg_hour", "") or item.get("bsop_hour", "")).strip()
        if len(raw_time) < 6:
            continue
        hhmm = raw_time[:4]
        bars.append(
            {
                "time": f"{hhmm[:2]}:{hhmm[2:]}",
                "open": _parse_float(item.get("stck_oprc")),
                "high": _parse_float(item.get("stck_hgpr")),
                "low": _parse_float(item.get("stck_lwpr")),
                "close": _parse_float(item.get("stck_prpr") or item.get("stck_clpr")),
                "volume": _parse_int(item.get("cntg_vol")),
                "cum_volume": _parse_int(item.get("acml_vol")),
                "date": row_date or date_str,
            }
        )
    bars = [bar for bar in bars if bar["close"] > 0]
    bars.sort(key=lambda x: x["time"])
    logger.info("SUCCESS: Backtest KIS intraday symbol=%s bars=%d", symbol, len(bars))
    return bars


def _prev_close_and_avg_volume(symbol: str, date_str: str, volume_days: int = 20) -> tuple[float | None, float]:
    """Fetch previous close and recent average daily volume with pykrx.

    Args:
        symbol: Six-digit KRX stock code.
        date_str: Backtest date in YYYYMMDD.
        volume_days: Number of previous sessions used for average volume.
    """
    try:
        from pykrx import stock as _pykrx

        dt = datetime.strptime(date_str, "%Y%m%d")
        fetch_start = (dt - timedelta(days=45)).strftime("%Y%m%d")
        df = _pykrx.get_market_ohlcv(fetch_start, date_str, symbol)
        if df is None or len(df) < 2:
            logger.warning("WARN: Backtest prev close unavailable symbol=%s date=%s", symbol, date_str)
            return None, 0.0
        prev_close = float(df["종가"].iloc[-2])
        prev_volumes = [float(value) for value in df["거래량"].iloc[-volume_days - 1 : -1]]
        avg_volume = sum(prev_volumes) / len(prev_volumes) if prev_volumes else 0.0
        return prev_close, avg_volume
    except Exception as exc:
        logger.warning("WARN: Backtest pykrx reference failed symbol=%s date=%s error=%s", symbol, date_str, exc)
        return None, 0.0


def simulate_intraday_trade(
    bars: list[dict[str, Any]],
    entry_bar_idx: int,
    prev_close: float,
    stop_loss_pct: float = -0.015,
    trailing_activate_pct: float = 0.02,
    trailing_stop_pct: float = 0.01,
    force_exit_time: str = "15:20",
) -> dict[str, Any]:
    """Simulate intraday exit rules from one entry bar.

    Args:
        bars: Minute bars ordered by ascending time.
        entry_bar_idx: Index of the selected entry bar.
        prev_close: Previous session close used for reporting context.
        stop_loss_pct: Stop loss threshold as a decimal return.
        trailing_activate_pct: Return threshold that activates trailing stop.
        trailing_stop_pct: Pullback from peak that triggers trailing stop.
        force_exit_time: HH:MM time at or after which the trade is force-exited.
    """
    entry_price = float(bars[entry_bar_idx]["close"])
    peak = entry_price
    trailing_active = False

    for idx in range(entry_bar_idx + 1, len(bars)):
        bar = bars[idx]
        price = float(bar["close"])
        pnl = (price - entry_price) / entry_price

        if bar["time"] >= force_exit_time:
            return {
                "exit_price": price,
                "pnl_pct": round(pnl * 100, 3),
                "exit_time": bar["time"],
                "exit_reason": "force_exit",
                "hold_bars": idx - entry_bar_idx,
                "prev_close": prev_close,
            }
        if pnl <= stop_loss_pct:
            return {
                "exit_price": price,
                "pnl_pct": round(pnl * 100, 3),
                "exit_time": bar["time"],
                "exit_reason": "stop_loss",
                "hold_bars": idx - entry_bar_idx,
                "prev_close": prev_close,
            }
        if pnl >= trailing_activate_pct:
            trailing_active = True
        if price > peak:
            peak = price
        if trailing_active and peak > 0 and (peak - price) / peak >= trailing_stop_pct:
            return {
                "exit_price": price,
                "pnl_pct": round(pnl * 100, 3),
                "exit_time": bar["time"],
                "exit_reason": "trailing_stop",
                "hold_bars": idx - entry_bar_idx,
                "prev_close": prev_close,
            }

    last = bars[-1]
    pnl = (float(last["close"]) - entry_price) / entry_price
    return {
        "exit_price": float(last["close"]),
        "pnl_pct": round(pnl * 100, 3),
        "exit_time": last["time"],
        "exit_reason": "eod",
        "hold_bars": len(bars) - entry_bar_idx,
        "prev_close": prev_close,
    }


def _pykrx_daily_to_bars(symbol: str, date_str: str) -> list[dict[str, Any]]:
    """pykrx 일봉 데이터로 분봉 시뮬레이션용 합성 bars 생성.

    KIS 분봉 API가 과거 날짜를 반환하지 않을 때 폴백으로 사용.
    장 시작(09:10) open → 모멘텀 구간(09:30) → 고점(11:00) → 종가(15:20) 순으로 4개 합성 bar 생성.
    """
    try:
        from pykrx import stock
        dt = datetime.strptime(date_str, "%Y%m%d")
        start = (dt - timedelta(days=3)).strftime("%Y%m%d")
        df = stock.get_market_ohlcv(start, date_str, symbol)
        if df is None or len(df) == 0:
            return []
        row = df.iloc[-1]
        # 날짜가 요청일과 다르면 해당 날 거래 없음
        row_date = str(df.index[-1]).replace("-", "")[:8]
        if row_date != date_str:
            return []
        o, h, l, c = float(row["시가"]), float(row["고가"]), float(row["저가"]), float(row["종가"])
        vol = int(row["거래량"])
        if o <= 0:
            return []
        # 합성 bars: open → 모멘텀 구간 고가 → 장중 저가 → 종가
        return [
            {"time": "09:10", "open": o, "high": o, "low": o, "close": o, "volume": vol // 4, "cum_volume": vol // 4},
            {"time": "09:30", "open": o, "high": h, "low": o, "close": h, "volume": vol // 4, "cum_volume": vol // 2},
            {"time": "11:00", "open": h, "high": h, "low": l, "close": l, "volume": vol // 4, "cum_volume": vol * 3 // 4},
            {"time": "15:20", "open": l, "high": l, "low": c, "close": c, "volume": vol // 4, "cum_volume": vol},
        ]
    except Exception as exc:
        logger.warning("WARN: Backtest pykrx daily fallback failed symbol=%s date=%s error=%s", symbol, date_str, exc)
        return []


def _summarize_trades(
    trades: list[dict[str, Any]],
    errors: list[str],
    start_date: str,
    end_date: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Build aggregate performance metrics for simulated trades.

    Args:
        trades: Simulated trade rows.
        errors: Symbol-level failures collected during execution.
        start_date: Requested backtest start date.
        end_date: Requested backtest end date.
        params: Backtest parameter echo for the response.
    """
    if not trades:
        return {
            "total": 0,
            "win_count": 0,
            "loss_count": 0,
            "win_rate_pct": 0,
            "avg_pnl_pct": 0,
            "avg_win_pct": 0,
            "avg_loss_pct": 0,
            "sharpe_ratio": 0,
            "max_drawdown_pct": 0,
            "total_pnl_pct": 0,
            "trades": [],
            "errors": errors[:20],
            "message": "조건에 맞는 분봉 거래 없음",
            "period": {"start": start_date, "end": end_date},
            "params": params,
        }

    pnls = [float(trade["pnl_pct"]) for trade in trades]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl <= 0]
    avg_pnl = round(sum(pnls) / len(pnls), 3)
    std = statistics.stdev(pnls) if len(pnls) > 1 else 0
    cumulative = 0.0
    peak_cum = 0.0
    max_drawdown = 0.0
    for pnl in pnls:
        cumulative += pnl
        peak_cum = max(peak_cum, cumulative)
        max_drawdown = max(max_drawdown, peak_cum - cumulative)

    return {
        "total": len(trades),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate_pct": round(len(wins) / len(pnls) * 100, 1),
        "avg_pnl_pct": avg_pnl,
        "avg_win_pct": round(sum(wins) / len(wins), 3) if wins else 0,
        "avg_loss_pct": round(sum(losses) / len(losses), 3) if losses else 0,
        "sharpe_ratio": round(avg_pnl / std, 2) if std > 0 else 0,
        "max_drawdown_pct": round(max_drawdown, 3),
        "total_pnl_pct": round(sum(pnls), 2),
        "trades": trades[:200],
        "errors": errors[:20],
        "period": {"start": start_date, "end": end_date},
        "params": params,
    }


def _validate_date_range(start_date: str, end_date: str) -> tuple[datetime, datetime]:
    """Validate API date strings and return parsed datetimes.

    Args:
        start_date: Backtest start date in YYYY-MM-DD.
        end_date: Backtest end date in YYYY-MM-DD.
    """
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    if start_dt > end_dt:
        raise ValueError("start_date must be earlier than or equal to end_date")
    return start_dt, end_dt


def _iter_dates(start_dt: datetime, end_dt: datetime) -> list[str]:
    """Return weekday dates in YYYYMMDD format for the requested range.

    Args:
        start_dt: Inclusive start datetime.
        end_dt: Inclusive end datetime.
    """
    dates: list[str] = []
    current = start_dt
    while current <= end_dt:
        if current.weekday() < 5:
            dates.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return dates


async def run_backtest_intraday(
    symbols: list[str],
    date_str: str,
    min_price_change_pct: float = 3.0,
    max_price_change_pct: float = 10.0,
    min_volume_ratio: float = 2.5,
    entry_start: str = "09:00",
    entry_end: str = "10:30",
    stop_loss_pct: float = -0.015,
    trailing_activate_pct: float = 0.02,
    trailing_stop_pct: float = 0.01,
) -> dict[str, Any]:
    """Run a one-day minute-bar backtest for the provided symbols.

    Args:
        symbols: Six-digit KRX stock codes to inspect.
        date_str: Backtest date in YYYYMMDD.
        min_price_change_pct: Minimum previous-close change percentage for entry.
        max_price_change_pct: Maximum previous-close change percentage for entry.
        min_volume_ratio: Minimum cumulative volume divided by recent average daily volume.
        entry_start: Earliest allowed entry time in HH:MM.
        entry_end: Latest allowed entry time in HH:MM.
        stop_loss_pct: Stop loss threshold as decimal return.
        trailing_activate_pct: Return threshold that activates trailing stop.
        trailing_stop_pct: Pullback from peak that triggers trailing exit.
    """
    logger.info("START: Backtest intraday date=%s symbols=%d", date_str, len(symbols))
    trades: list[dict[str, Any]] = []
    errors: list[str] = []

    for symbol in [_normalize_symbol(value) for value in symbols]:
        if not symbol:
            continue
        try:
            prev_close, avg_volume = _prev_close_and_avg_volume(symbol, date_str)
            if not prev_close or prev_close <= 0:
                errors.append(f"{symbol}: prev_close_unavailable")
                continue
            bars = await fetch_intraday_bars(symbol, date_str)
            if not bars:
                # KIS 분봉 없음(과거 날짜) → pykrx 일봉 폴백
                bars = _pykrx_daily_to_bars(symbol, date_str)
            if not bars:
                errors.append(f"{symbol}: bars_unavailable")
                continue

            for idx, bar in enumerate(bars):
                if not (entry_start <= bar["time"] <= entry_end):
                    continue
                price_change_pct = (float(bar["close"]) - prev_close) / prev_close * 100
                volume_ratio = float(bar["cum_volume"]) / avg_volume if avg_volume > 0 else 0.0
                if not (min_price_change_pct <= price_change_pct <= max_price_change_pct):
                    continue
                if volume_ratio < min_volume_ratio:
                    continue

                trade_result = simulate_intraday_trade(
                    bars,
                    idx,
                    prev_close,
                    stop_loss_pct=stop_loss_pct,
                    trailing_activate_pct=trailing_activate_pct,
                    trailing_stop_pct=trailing_stop_pct,
                )
                trades.append(
                    {
                        "symbol": symbol,
                        "entry_date": date_str,
                        "entry_time": bar["time"],
                        "entry_price": float(bar["close"]),
                        "price_change_pct": round(price_change_pct, 2),
                        "volume_ratio": round(volume_ratio, 2),
                        **trade_result,
                    }
                )
                break
        except Exception as exc:
            errors.append(f"{symbol}: {exc}")
            logger.warning("WARN: Backtest intraday symbol failed symbol=%s date=%s error=%s", symbol, date_str, exc)

    params = {
        "symbols": len(symbols),
        "min_price_change_pct": min_price_change_pct,
        "max_price_change_pct": max_price_change_pct,
        "min_volume_ratio": min_volume_ratio,
        "entry_start": entry_start,
        "entry_end": entry_end,
        "stop_loss_pct": stop_loss_pct,
        "trailing_activate_pct": trailing_activate_pct,
        "trailing_stop_pct": trailing_stop_pct,
    }
    result = _summarize_trades(trades, errors, date_str, date_str, params)
    logger.info("SUCCESS: Backtest intraday date=%s total=%d", date_str, result.get("total", 0))
    return result


async def run_backtest(
    start_date: str,
    end_date: str,
    symbols: list[str] | None = None,
    min_price_change_pct: float = 3.0,
    max_price_change_pct: float = 10.0,
    min_volume_ratio: float = 2.5,
    entry_start: str = "09:00",
    entry_end: str = "10:30",
    stop_loss_pct: float = -0.015,
    trailing_activate_pct: float = 0.02,
    trailing_stop_pct: float = 0.01,
    universe_limit: int = 50,
) -> dict[str, Any]:
    """Run an intraday backtest over a date range.

    Args:
        start_date: Backtest start date in YYYY-MM-DD.
        end_date: Backtest end date in YYYY-MM-DD.
        symbols: Optional explicit stock-code universe.
        min_price_change_pct: Minimum previous-close change percentage for entry.
        max_price_change_pct: Maximum previous-close change percentage for entry.
        min_volume_ratio: Minimum cumulative volume ratio for entry.
        entry_start: Earliest allowed entry time in HH:MM.
        entry_end: Latest allowed entry time in HH:MM.
        stop_loss_pct: Stop loss threshold as decimal return.
        trailing_activate_pct: Return threshold that activates trailing stop.
        trailing_stop_pct: Pullback from peak that triggers trailing exit.
        universe_limit: Maximum DB-derived universe size when symbols are omitted.
    """
    logger.info("START: Backtest run start=%s end=%s universe=%d", start_date, end_date, universe_limit)
    start_dt, end_dt = _validate_date_range(start_date, end_date)
    target_symbols = [_normalize_symbol(symbol) for symbol in (symbols or get_universe_symbols(universe_limit))]
    target_symbols = [symbol for symbol in target_symbols if symbol]
    if not target_symbols:
        logger.error("FAIL: Backtest run no universe symbols")
        return {
            "error": "유니버스 종목을 불러올 수 없습니다.",
            "total": 0,
            "win_rate_pct": 0,
            "avg_pnl_pct": 0,
            "trades": [],
        }

    all_trades: list[dict[str, Any]] = []
    all_errors: list[str] = []
    for date_str in _iter_dates(start_dt, end_dt):
        day_result = await run_backtest_intraday(
            symbols=target_symbols,
            date_str=date_str,
            min_price_change_pct=min_price_change_pct,
            max_price_change_pct=max_price_change_pct,
            min_volume_ratio=min_volume_ratio,
            entry_start=entry_start,
            entry_end=entry_end,
            stop_loss_pct=stop_loss_pct,
            trailing_activate_pct=trailing_activate_pct,
            trailing_stop_pct=trailing_stop_pct,
        )
        all_trades.extend(day_result.get("trades", []))
        all_errors.extend(day_result.get("errors", []))

    params = {
        "symbols": len(target_symbols),
        "min_price_change_pct": min_price_change_pct,
        "max_price_change_pct": max_price_change_pct,
        "min_volume_ratio": min_volume_ratio,
        "entry_start": entry_start,
        "entry_end": entry_end,
        "stop_loss_pct": stop_loss_pct,
        "trailing_activate_pct": trailing_activate_pct,
        "trailing_stop_pct": trailing_stop_pct,
        "universe_limit": universe_limit,
    }
    result = _summarize_trades(all_trades, all_errors, start_date, end_date, params)
    logger.info(
        "SUCCESS: Backtest run total=%d win_rate=%s avg_pnl=%s",
        result.get("total", 0),
        result.get("win_rate_pct"),
        result.get("avg_pnl_pct"),
    )
    return result
