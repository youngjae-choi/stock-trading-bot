"""장 개시 예수금 baseline 캡처/조회 + 레짐 예산률 + 당일 누적 매수액 집계.

포지션 사이징(order_executor)과 누적 예산 상한 가드(order_preflight)가 공유한다.
baseline은 일자별 1회 캡처(idempotent)되어 서버 재기동에도 유지된다.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection
from ..regime_set_service import get_today_application

logger = logging.getLogger("DailyCapital")

_DEFAULT_BUDGET_RATE = 0.8
_DEFAULT_MAX_POSITIONS = 7


def _today_kst() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


def _ensure_table() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_capital_baseline (
                trade_date   TEXT PRIMARY KEY,
                deposit_krw  REAL NOT NULL,
                captured_at  TEXT NOT NULL
            )
            """
        )


def capture_baseline(deposit: float, trade_date: str | None = None) -> float | None:
    d = trade_date or _today_kst()
    try:
        value = float(deposit)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        logger.warning("WARN: baseline 캡처 거부 — deposit<=0 trade_date=%s value=%s", d, deposit)
        return None
    _ensure_table()
    existing = get_baseline(d)
    if existing is not None:
        logger.info("INFO: baseline 이미 존재 — 재캡처 생략 trade_date=%s value=%.0f", d, existing)
        return existing
    now = datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO daily_capital_baseline (trade_date, deposit_krw, captured_at) VALUES (?, ?, ?)",
            (d, value, now),
        )
    logger.info("SUCCESS: baseline 캡처 trade_date=%s deposit=%.0f", d, value)
    return value


def get_baseline(trade_date: str | None = None) -> float | None:
    d = trade_date or _today_kst()
    _ensure_table()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT deposit_krw FROM daily_capital_baseline WHERE trade_date = ?", (d,)
        ).fetchone()
    if row is None:
        return None
    try:
        return float(row["deposit_krw"])
    except (TypeError, ValueError, KeyError):
        return None


def get_active_budget_rate(trade_date: str | None = None) -> float:
    d = trade_date or _today_kst()
    try:
        app = get_today_application(d)
        if app:
            rate = app.get("applied_settings", {}).get("daily_budget_rate")
            if rate is not None:
                r = float(rate)
                if 0 < r <= 1:
                    return r
    except Exception as exc:
        logger.warning("WARN: budget_rate 조회 실패 trade_date=%s reason=%s", d, exc)
    return _DEFAULT_BUDGET_RATE


def get_active_max_positions(trade_date: str | None = None) -> int:
    d = trade_date or _today_kst()
    try:
        app = get_today_application(d)
        if app:
            mp = app.get("applied_settings", {}).get("max_positions")
            if mp:
                return int(mp)
    except Exception as exc:
        logger.warning("WARN: max_positions 조회 실패 trade_date=%s reason=%s", d, exc)
    return _DEFAULT_MAX_POSITIONS


def get_cumulative_buy_amount(trade_date: str | None = None) -> float:
    d = trade_date or _today_kst()
    with get_connection() as conn:
        if not _table_exists(conn, "trading_orders"):
            return 0.0
        row = conn.execute(
            """
            SELECT COALESCE(SUM(qty * price), 0.0) AS total
            FROM trading_orders
            WHERE trade_date = ? AND side = 'buy'
              AND status NOT IN ('cancelled', 'failed')
            """,
            (d,),
        ).fetchone()
    try:
        return float(row["total"]) if row else 0.0
    except (TypeError, ValueError, KeyError):
        return 0.0


def _table_exists(conn: Any, name: str) -> bool:
    return conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?", (name,)
    ).fetchone() is not None


def _delete_baseline(trade_date: str) -> None:
    _ensure_table()
    with get_connection() as conn:
        conn.execute("DELETE FROM daily_capital_baseline WHERE trade_date = ?", (trade_date,))


def _insert_order_for_test(trade_date: str, symbol: str, side: str, qty: int, price: float, status: str) -> None:
    import uuid
    from .order_executor import _ensure_orders_table
    _ensure_orders_table()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO trading_orders (id, trade_date, signal_id, symbol, name, side, order_type, qty, price, kis_order_no, status, reason, created_at)
               VALUES (?, ?, '', ?, '', ?, 'limit', ?, ?, '', ?, '', ?)""",
            (str(uuid.uuid4()), trade_date, symbol, side, qty, price, status, datetime.now().isoformat()),
        )


def _delete_orders_for_test(trade_date: str) -> None:
    with get_connection() as conn:
        if _table_exists(conn, "trading_orders"):
            conn.execute("DELETE FROM trading_orders WHERE trade_date = ?", (trade_date,))
