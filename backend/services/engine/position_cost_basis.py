"""원가 보조 원장(position_cost_basis) — 매수 fill 없는 포지션의 매수측 원가 단일출처.

배경(A2): KIS 보유 흡수(auto_imported)·정합(reconciled) 포지션은 매수 fill이 DB에 없어
fills 기반 손익(trade_pairs)이 matched_qty=min(buy_qty,sell_qty)=0으로 그 거래를 통째로
누락한다. 합성 매수 주문을 trading_orders에 넣으면 무결성 체크(A3)가 오염되므로, 별도
보조 원장에 KIS 평단·수량을 기록해 trade_pairs가 매수측을 보강하도록 한다.

원칙:
- 키는 (norm_symbol, trade_date) UNIQUE — 재기동·재흡수 중복을 idempotent하게 흡수.
- norm_symbol(symbol)로 정규화 키를 저장하고 원본 symbol도 함께 보존(표시·추적용).
- 조회는 norm_symbol 기준, trade_date <= as_of_date 중 가장 최근 1행.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ..db import get_connection
from .symbol_norm import norm_symbol

logger = logging.getLogger("PositionCostBasis")


def ensure_table() -> None:
    """position_cost_basis 테이블을 보장한다(CREATE IF NOT EXISTS, ALTER 없음).

    WAL 하 서버 가동 중에도 안전한 마이그레이션이다. lazy하게 매 진입점에서 호출한다.
    """
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS position_cost_basis (
                id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                norm_symbol TEXT NOT NULL,
                qty INTEGER NOT NULL,
                avg_price REAL NOT NULL,
                source TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(norm_symbol, trade_date)
            )
            """
        )


def upsert_cost_basis(
    symbol: str, qty: int, avg_price: float, source: str, trade_date: str
) -> None:
    """(norm_symbol, trade_date) 키로 원가 1행을 INSERT OR REPLACE한다(idempotent).

    Args:
        symbol: 원본 심볼(원본 보존, norm_symbol로 정규화 키 산출).
        qty: 보유 수량.
        avg_price: KIS 평균 매입가 등 원가 단가.
        source: 'auto_imported' | 'reconciled' | 'manual'.
        trade_date: 원가 기록 거래일(YYYY-MM-DD).
    """
    ensure_table()
    safe_symbol = str(symbol or "").strip()
    nsym = norm_symbol(safe_symbol)
    safe_qty = int(qty or 0)
    safe_avg = float(avg_price or 0)
    if not nsym or safe_qty <= 0 or safe_avg <= 0:
        logger.warning(
            "WARN: [CostBasis] invalid upsert symbol=%s qty=%s avg=%s", symbol, qty, avg_price
        )
        return
    now = datetime.now(timezone.utc).isoformat()
    # id는 (norm_symbol, trade_date)에 결정적 — REPLACE 시 PK 충돌 없이 같은 행을 덮어쓴다.
    row_id = f"{nsym}-{trade_date}"
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO position_cost_basis
                (id, symbol, norm_symbol, qty, avg_price, source, trade_date, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (row_id, safe_symbol, nsym, safe_qty, safe_avg, str(source), str(trade_date), now),
        )
    logger.info(
        "SUCCESS: [CostBasis] upsert symbol=%s norm=%s qty=%d avg=%.2f source=%s date=%s",
        safe_symbol, nsym, safe_qty, safe_avg, source, trade_date,
    )


def _row_to_dict(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "symbol": row["symbol"],
        "norm_symbol": row["norm_symbol"],
        "qty": int(row["qty"]),
        "avg_price": float(row["avg_price"]),
        "source": row["source"],
        "trade_date": row["trade_date"],
        "created_at": row["created_at"],
    }


def get_cost_basis(symbol: str, as_of_date: str) -> dict[str, Any] | None:
    """norm_symbol(symbol) 기준 trade_date <= as_of_date 중 가장 최근 원가 1행.

    Args:
        symbol: 조회 심볼(정규화해 매칭).
        as_of_date: 기준일(YYYY-MM-DD). 보통 매도일.
    """
    ensure_table()
    nsym = norm_symbol(symbol)
    if not nsym:
        return None
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, symbol, norm_symbol, qty, avg_price, source, trade_date, created_at
            FROM position_cost_basis
            WHERE norm_symbol = ? AND trade_date <= ?
            ORDER BY trade_date DESC, created_at DESC
            LIMIT 1
            """,
            (nsym, as_of_date),
        ).fetchone()
    return _row_to_dict(row) if row else None


def get_cost_basis_map(symbols, as_of_date: str) -> dict[str, dict[str, Any]]:
    """여러 심볼의 원가를 {norm_symbol: row}로 일괄 조회한다.

    각 norm_symbol에 대해 trade_date <= as_of_date 중 가장 최근 1행만 담는다.

    Args:
        symbols: 심볼 목록(원본·정규화 혼재 허용).
        as_of_date: 기준일(YYYY-MM-DD).
    """
    ensure_table()
    norm_keys = {norm_symbol(s) for s in (symbols or []) if str(s or "").strip()}
    if not norm_keys:
        return {}
    placeholders = ",".join("?" * len(norm_keys))
    out: dict[str, dict[str, Any]] = {}
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT id, symbol, norm_symbol, qty, avg_price, source, trade_date, created_at
            FROM position_cost_basis
            WHERE norm_symbol IN ({placeholders}) AND trade_date <= ?
            ORDER BY trade_date DESC, created_at DESC
            """,
            (*norm_keys, as_of_date),
        ).fetchall()
    for row in rows:
        nsym = row["norm_symbol"]
        if nsym not in out:  # ORDER BY DESC → 첫 행이 가장 최근
            out[nsym] = _row_to_dict(row)
    return out
