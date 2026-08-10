"""일자별 KIS 검증 보유 스냅샷 (daily_holdings_snapshot) — 이월(carried-in) 손익의 단일 진실.

배경: DB 드리프트로 trading_orders·fills·cost_basis 어느 것도 KIS 실보유와 일치하지 않아
(예: 0039P0 fills net +7,877인데 KIS 실보유 0), 이월 포지션 손익을 종목별로 정확히
계산할 수 없다. 유일한 KIS 진실은 잔고 조회다.

해법: 매 거래일 장전(08:50 baseline 캡처와 동일 시점·동일 get_balance 호출 재사용)에
KIS 실보유를 종목별로 스냅샷한다. 이 스냅샷(금일 open) = 밤사이 이월된 carried-in.
이월 P&L = carried_in(qty·KIS평단) × (금일 매도가 − 평단).

원칙:
- 키는 (trade_date, norm_symbol) — 재캡처 idempotent.
- 추가 KIS 호출 없음(스케줄러 baseline 잡의 balance 재사용) → 토큰 경합 없음.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ..db import get_connection
from .symbol_norm import norm_symbol

logger = logging.getLogger("HoldingsSnapshot")


def ensure_table() -> None:
    """daily_holdings_snapshot 테이블 보장(CREATE IF NOT EXISTS, WAL 안전)."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_holdings_snapshot (
                trade_date   TEXT NOT NULL,
                symbol       TEXT NOT NULL,
                norm_symbol  TEXT NOT NULL,
                qty          INTEGER NOT NULL,
                avg_price    REAL NOT NULL,
                market_price REAL NOT NULL DEFAULT 0,
                captured_at  TEXT NOT NULL,
                PRIMARY KEY (trade_date, norm_symbol)
            )
            """
        )


def upsert_holdings(trade_date: str, positions: list[dict[str, Any]]) -> int:
    """KIS 보유 리스트를 (trade_date, norm_symbol) 키로 idempotent 저장한다.

    Args:
        trade_date: 스냅샷 거래일(YYYY-MM-DD).
        positions: [{symbol, qty, avg_price, current_price}] (get_balance 파싱 결과).

    Returns:
        저장한 종목 수(qty>0만).
    """
    ensure_table()
    now = datetime.now(timezone.utc).isoformat()
    count = 0
    with get_connection() as conn:
        for p in positions or []:
            symbol = str(p.get("symbol") or "").strip()
            try:
                qty = int(float(str(p.get("qty") or 0)))
            except (TypeError, ValueError):
                qty = 0
            avg = _to_float(p.get("avg_price"))
            if not symbol or qty <= 0:
                continue
            nsym = norm_symbol(symbol)
            mkt = _to_float(p.get("current_price") or p.get("market_price"))
            conn.execute(
                """
                INSERT OR REPLACE INTO daily_holdings_snapshot
                    (trade_date, symbol, norm_symbol, qty, avg_price, market_price, captured_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (str(trade_date), symbol, nsym, qty, avg, mkt, now),
            )
            count += 1
    logger.info("SUCCESS: [HoldingsSnapshot] trade_date=%s captured=%d", trade_date, count)
    return count


def capture_from_balance(trade_date: str, balance: dict[str, Any]) -> int:
    """get_balance() 원응답에서 종목별 보유를 파싱해 스냅샷 저장한다.

    Args:
        trade_date: 스냅샷 거래일.
        balance: kis get_balance() 원응답(dict, output1 보유 리스트 포함).

    Returns:
        저장한 종목 수.
    """
    from ...api.routes.account import _build_balance_payload

    payload = _build_balance_payload(balance)
    return upsert_holdings(trade_date, payload.get("positions", []) or [])


def get_holdings(trade_date: str) -> dict[str, dict[str, Any]]:
    """해당 거래일 open 스냅샷을 {norm_symbol: {symbol,qty,avg_price,market_price}}로 반환."""
    ensure_table()
    out: dict[str, dict[str, Any]] = {}
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT symbol, norm_symbol, qty, avg_price, market_price FROM daily_holdings_snapshot WHERE trade_date = ?",
            (str(trade_date),),
        ).fetchall()
    for r in rows:
        out[str(r["norm_symbol"])] = {
            "symbol": str(r["symbol"]),
            "qty": int(r["qty"]),
            "avg_price": float(r["avg_price"]),
            "market_price": float(r["market_price"]),
            "trade_date": str(trade_date),
        }
    return out


def has_snapshot(trade_date: str) -> bool:
    """해당 거래일 스냅샷 존재 여부(이월 계산 가능 여부 판정)."""
    ensure_table()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM daily_holdings_snapshot WHERE trade_date = ? LIMIT 1", (str(trade_date),)
        ).fetchone()
    return row is not None


def _to_float(value: Any) -> float:
    try:
        return float(str(value).replace(",", "")) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0
