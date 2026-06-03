"""Entry-signal technical indicator snapshots backed by pykrx OHLCV data."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger("TechnicalIndicators")

_CACHE: dict[str, dict[str, Any]] = {}


def _pykrx_ohlcv(symbol: str, start: str, end: str):
    """Fetch a stock OHLCV dataframe from pykrx.

    Args:
        symbol: KRX stock code.
        start: Start date in YYYYMMDD.
        end: End date in YYYYMMDD.
    """
    try:
        from pykrx import stock

        df = stock.get_market_ohlcv(start, end, symbol)
        if df is None or len(df) == 0:
            logger.warning("WARN: pykrx OHLCV empty symbol=%s start=%s end=%s", symbol, start, end)
            return None
        return df
    except Exception as exc:
        logger.warning("WARN: pykrx OHLCV fetch failed symbol=%s error=%s", symbol, exc)
        return None


def _pykrx_kospi_ohlcv(start: str, end: str):
    """Fetch KOSPI index OHLCV with the pykrx index API.

    Args:
        start: Start date in YYYYMMDD.
        end: End date in YYYYMMDD.
    """
    try:
        from pykrx import stock

        # KODEX 200 ETF(069500)을 KOSPI 방향성 proxy로 사용 (로그인 불필요)
        df = stock.get_market_ohlcv(start, end, "069500")
        if df is None or len(df) == 0:
            logger.warning("WARN: pykrx KOSPI OHLCV empty start=%s end=%s", start, end)
            return None
        return df
    except Exception as exc:
        logger.warning("WARN: pykrx KOSPI OHLCV fetch failed error=%s", exc)
        return None


def _calc_rsi(closes: list[float], period: int = 14) -> float | None:
    """Calculate a simple RSI value from closing prices.

    Args:
        closes: Closing prices ordered oldest to newest.
        period: RSI lookback period.
    """
    if len(closes) < period + 1:
        return None

    gains: list[float] = []
    losses: list[float] = []
    for index in range(1, len(closes)):
        diff = closes[index] - closes[index - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def _safe_float_series(values: Any) -> list[float]:
    """Convert a dataframe series-like object to floats while preserving order.

    Args:
        values: Iterable values from a pykrx dataframe column.
    """
    result: list[float] = []
    for value in list(values):
        try:
            result.append(float(value))
        except (TypeError, ValueError):
            continue
    return result


def calculate_indicators(symbol: str, trade_date: str) -> dict[str, Any]:
    """Calculate technical indicators for a symbol on a trade date.

    Args:
        symbol: KRX stock code.
        trade_date: Trade date in YYYY-MM-DD.
    """
    cache_key = f"{symbol}:{trade_date}"
    if cache_key in _CACHE:
        return dict(_CACHE[cache_key])

    logger.info("START: calculate signal indicators symbol=%s date=%s", symbol, trade_date)
    result: dict[str, Any] = {}

    try:
        dt = datetime.strptime(trade_date, "%Y-%m-%d")
    except ValueError as exc:
        logger.warning("WARN: calculate_indicators invalid date symbol=%s date=%s error=%s", symbol, trade_date, exc)
        return result

    start = (dt - timedelta(days=40)).strftime("%Y%m%d")
    end = dt.strftime("%Y%m%d")

    try:
        df = _pykrx_ohlcv(symbol, start, end)
        if df is None or len(df) < 5:
            logger.warning("WARN: calculate_indicators insufficient rows symbol=%s date=%s", symbol, trade_date)
        else:
            closes = _safe_float_series(df["종가"])
            from .tsi import tsi_for_closes
            result["tsi"] = tsi_for_closes(closes)
            volumes = _safe_float_series(df["거래량"])
            if len(closes) >= 2:
                today_close = closes[-1]
                prev_close = closes[-2]
                result["price_change_pct"] = round((today_close - prev_close) / prev_close * 100, 2) if prev_close else None

                if len(closes) >= 5:
                    ma5 = sum(closes[-5:]) / 5
                    result["price_vs_ma5_pct"] = round((today_close - ma5) / ma5 * 100, 2) if ma5 else None

                if len(closes) >= 20:
                    ma20 = sum(closes[-20:]) / 20
                    result["price_vs_ma20_pct"] = round((today_close - ma20) / ma20 * 100, 2) if ma20 else None

                result["rsi14"] = _calc_rsi(closes)

                if len(closes) >= 6 and closes[-6]:
                    result["momentum5d_pct"] = round((today_close - closes[-6]) / closes[-6] * 100, 2)

            if len(volumes) >= 21:
                avg_vol20 = sum(volumes[-21:-1]) / 20
                result["volume_ratio"] = round(volumes[-1] / avg_vol20, 2) if avg_vol20 > 0 else None
    except Exception as exc:
        logger.warning("WARN: calculate_indicators stock metrics failed symbol=%s date=%s error=%s", symbol, trade_date, exc)

    try:
        kstart = (dt - timedelta(days=5)).strftime("%Y%m%d")
        kdf = _pykrx_kospi_ohlcv(kstart, end)
        if kdf is not None and len(kdf) >= 2:
            kcloses = _safe_float_series(kdf["종가"])
            if len(kcloses) >= 2 and kcloses[-2]:
                result["kospi_change_pct"] = round((kcloses[-1] - kcloses[-2]) / kcloses[-2] * 100, 2)
    except Exception as exc:
        logger.warning("WARN: calculate_indicators KOSPI metric failed symbol=%s date=%s error=%s", symbol, trade_date, exc)

    _CACHE[cache_key] = dict(result)
    logger.info("SUCCESS: calculate signal indicators symbol=%s date=%s keys=%s", symbol, trade_date, sorted(result))
    return result


def _ensure_signal_indicators_table() -> None:
    """Create the signal technical indicator table when direct service use precedes app startup."""
    from ..db import get_connection

    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS signal_technical_indicators (
                id                  TEXT PRIMARY KEY,
                signal_id           TEXT NOT NULL,
                symbol              TEXT NOT NULL,
                trade_date          TEXT NOT NULL,
                price_change_pct    REAL,
                price_vs_ma5_pct    REAL,
                price_vs_ma20_pct   REAL,
                rsi14               REAL,
                momentum5d_pct      REAL,
                tsi                 REAL,
                volume_ratio        REAL,
                kospi_change_pct    REAL,
                outcome_pnl_pct     REAL,
                outcome_hold_min    REAL,
                created_at          TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sti_symbol_date ON signal_technical_indicators(symbol, trade_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sti_signal_id ON signal_technical_indicators(signal_id)")
        try:
            conn.execute("ALTER TABLE signal_technical_indicators ADD COLUMN tsi REAL")
        except Exception:
            pass  # column already exists on existing DBs


def save_signal_indicators(signal_id: str, symbol: str, trade_date: str) -> bool:
    """Persist a technical indicator snapshot for a BUY signal.

    Args:
        signal_id: trading_signals.id value.
        symbol: KRX stock code.
        trade_date: Signal trade date in YYYY-MM-DD.
    """
    from ..db import get_connection

    logger.info("START: save_signal_indicators signal_id=%s symbol=%s date=%s", signal_id, symbol, trade_date)
    indicators = calculate_indicators(symbol, trade_date)
    if not indicators:
        logger.warning("WARN: save_signal_indicators skipped empty indicators signal_id=%s symbol=%s", signal_id, symbol)
        return False

    now = datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
    try:
        _ensure_signal_indicators_table()
        with get_connection() as conn:
            existing = conn.execute(
                "SELECT id FROM signal_technical_indicators WHERE signal_id = ? LIMIT 1",
                (signal_id,),
            ).fetchone()
            if existing:
                logger.info("SUCCESS: save_signal_indicators already exists signal_id=%s", signal_id)
                return True

            conn.execute(
                """
                INSERT INTO signal_technical_indicators
                    (id, signal_id, symbol, trade_date,
                     price_change_pct, price_vs_ma5_pct, price_vs_ma20_pct,
                     rsi14, momentum5d_pct, tsi, volume_ratio, kospi_change_pct,
                     created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    signal_id,
                    symbol,
                    trade_date,
                    indicators.get("price_change_pct"),
                    indicators.get("price_vs_ma5_pct"),
                    indicators.get("price_vs_ma20_pct"),
                    indicators.get("rsi14"),
                    indicators.get("momentum5d_pct"),
                    indicators.get("tsi"),
                    indicators.get("volume_ratio"),
                    indicators.get("kospi_change_pct"),
                    now,
                ),
            )
        logger.info("SUCCESS: save_signal_indicators signal_id=%s symbol=%s", signal_id, symbol)
        return True
    except Exception as exc:
        logger.warning("WARN: save_signal_indicators DB error signal_id=%s error=%s", signal_id, exc)
        return False


def update_signal_outcome(signal_id: str, pnl_pct: float, hold_minutes: float) -> bool:
    """Update realized outcome fields for a saved signal indicator snapshot.

    Args:
        signal_id: trading_signals.id value.
        pnl_pct: Realized return percentage.
        hold_minutes: Holding duration in minutes.
    """
    from ..db import get_connection

    logger.info("START: update_signal_outcome signal_id=%s pnl_pct=%.2f hold_min=%.2f", signal_id, pnl_pct, hold_minutes)
    try:
        _ensure_signal_indicators_table()
        with get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE signal_technical_indicators
                SET outcome_pnl_pct = ?, outcome_hold_min = ?
                WHERE signal_id = ?
                """,
                (pnl_pct, hold_minutes, signal_id),
            )
        logger.info("SUCCESS: update_signal_outcome signal_id=%s updated=%d", signal_id, cursor.rowcount)
        return cursor.rowcount > 0
    except Exception as exc:
        logger.warning("WARN: update_signal_outcome failed signal_id=%s error=%s", signal_id, exc)
        return False
