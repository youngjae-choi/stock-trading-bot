"""S10: 당일 거래 결과 요약 저장 + DB 파일 백업."""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection
from .order_executor import get_today_orders
from .position_integrity import json_compact, summarize_order_integrity
from .rulepack_store import get_active_rulepack_for_date
from ...config import settings

logger = logging.getLogger("DailySummary")
_RETENTION_DAYS = 30


def _ensure_tables() -> None:
    """Create and migrate the daily_trade_summary table used by S10."""
    with get_connection() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS daily_trade_summary (
                id TEXT PRIMARY KEY,
                trade_date TEXT NOT NULL UNIQUE,
                total_orders INTEGER NOT NULL DEFAULT 0,
                buy_orders INTEGER NOT NULL DEFAULT 0,
                sell_orders INTEGER NOT NULL DEFAULT 0,
                failed_orders INTEGER NOT NULL DEFAULT 0,
                realized_pnl REAL NOT NULL DEFAULT 0.0,
                realized_pnl_pct REAL NOT NULL DEFAULT 0.0,
                symbols_traded TEXT NOT NULL DEFAULT '[]',
                market_tone TEXT NOT NULL DEFAULT '',
                rulepack_id TEXT NOT NULL DEFAULT '',
                pnl_status TEXT NOT NULL DEFAULT 'unverified',
                pnl_source TEXT NOT NULL DEFAULT 'orders_without_fills',
                integrity_warnings TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(daily_trade_summary)").fetchall()}
        migrations = [
            ("pnl_status", "ALTER TABLE daily_trade_summary ADD COLUMN pnl_status TEXT NOT NULL DEFAULT 'unverified'"),
            (
                "pnl_source",
                "ALTER TABLE daily_trade_summary ADD COLUMN pnl_source TEXT NOT NULL DEFAULT 'orders_without_fills'",
            ),
            (
                "integrity_warnings",
                "ALTER TABLE daily_trade_summary ADD COLUMN integrity_warnings TEXT NOT NULL DEFAULT '[]'",
            ),
        ]
        for column, statement in migrations:
            if column not in columns:
                conn.execute(statement)


def _prune_trade_history() -> None:
    """Keep trade history and DB backups within the rolling retention window."""
    cutoff_date = (datetime.now(ZoneInfo("Asia/Seoul")) - timedelta(days=_RETENTION_DAYS)).strftime("%Y-%m-%d")
    with get_connection() as conn:
        conn.execute("DELETE FROM daily_trade_summary WHERE trade_date < ?", (cutoff_date,))

    db_path = Path(settings.APP_DB_PATH)
    if not db_path.is_absolute():
        from pathlib import Path as _P
        import os

        db_path = _P(os.getcwd()) / db_path
    backup_dir = db_path.parent / "backups"
    if not backup_dir.exists():
        return

    prefix = "stock_trading_bot_"
    for backup_path in backup_dir.glob(f"{prefix}*.sqlite3"):
        backup_date = backup_path.stem[len(prefix):]
        try:
            if backup_date < cutoff_date:
                backup_path.unlink()
        except Exception:
            continue


async def run_daily_summary(trade_date: str | None = None) -> dict[str, Any]:
    """당일 거래 결과를 집계해 daily_trade_summary에 저장하고 DB를 백업한다."""
    _ensure_tables()
    _prune_trade_history()
    if trade_date is None:
        trade_date = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")

    now_iso = datetime.now(ZoneInfo("Asia/Seoul")).isoformat()

    # 당일 주문 집계
    orders = get_today_orders(trade_date)
    buy_list = [o for o in orders if o.get("side") == "buy"]
    sell_list = [o for o in orders if o.get("side") == "sell"]
    failed_list = [o for o in orders if o.get("status") == "failed"]

    # 실현 손익 계산 (매도 주문 기준)
    realized_pnl = 0.0
    realized_pnl_pcts: list[float] = []
    for sell in sell_list:
        sym = sell.get("symbol")
        sell_price = float(sell.get("price") or 0)
        qty = int(sell.get("qty") or 0)
        buys = [o for o in buy_list if o.get("symbol") == sym]
        if buys and sell_price > 0 and qty > 0:
            avg_buy = sum(float(b.get("price", 0)) for b in buys) / len(buys)
            pnl = (sell_price - avg_buy) * qty
            pnl_pct = (sell_price - avg_buy) / avg_buy * 100 if avg_buy > 0 else 0
            realized_pnl += pnl
            realized_pnl_pcts.append(pnl_pct)

    avg_pnl_pct = sum(realized_pnl_pcts) / len(realized_pnl_pcts) if realized_pnl_pcts else 0.0
    symbols_traded = list({o.get("symbol") for o in orders if o.get("symbol")})
    integrity = summarize_order_integrity(trade_date)

    # 시장 톤 조회
    market_tone = ""
    try:
        with get_connection() as conn:
            tone_row = conn.execute(
                "SELECT tone FROM market_tone_results WHERE trade_date = ? LIMIT 1",
                (trade_date,),
            ).fetchone()
            if tone_row:
                market_tone = tone_row["tone"]
    except Exception:
        pass

    # RulePack ID 조회
    rulepack_id = ""
    rulepack = get_active_rulepack_for_date(trade_date)
    if rulepack:
        rulepack_id = rulepack.get("rulepack_id", "")

    # DB 저장 (UPSERT)
    summary_id = str(uuid.uuid4())
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM daily_trade_summary WHERE trade_date = ?", (trade_date,)
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE daily_trade_summary SET
                   total_orders=?, buy_orders=?, sell_orders=?, failed_orders=?,
                   realized_pnl=?, realized_pnl_pct=?, symbols_traded=?,
                   market_tone=?, rulepack_id=?, pnl_status=?, pnl_source=?,
                   integrity_warnings=?, updated_at=?
                   WHERE trade_date=?""",
                (
                    len(orders), len(buy_list), len(sell_list), len(failed_list),
                    realized_pnl, avg_pnl_pct, json.dumps(symbols_traded),
                    market_tone, rulepack_id,
                    integrity.get("pnl_status", "unverified"),
                    integrity.get("pnl_source", "orders_without_fills"),
                    json_compact(integrity.get("warnings", [])),
                    now_iso, trade_date,
                ),
            )
        else:
            conn.execute(
                """INSERT INTO daily_trade_summary
                   (id, trade_date, total_orders, buy_orders, sell_orders, failed_orders,
                    realized_pnl, realized_pnl_pct, symbols_traded, market_tone, rulepack_id,
                    pnl_status, pnl_source, integrity_warnings, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    summary_id, trade_date,
                    len(orders), len(buy_list), len(sell_list), len(failed_list),
                    realized_pnl, avg_pnl_pct, json.dumps(symbols_traded),
                    market_tone, rulepack_id,
                    integrity.get("pnl_status", "unverified"),
                    integrity.get("pnl_source", "orders_without_fills"),
                    json_compact(integrity.get("warnings", [])),
                    now_iso, now_iso,
                ),
            )

    logger.info(
        "SUCCESS: DailySummary saved trade_date=%s orders=%d pnl=%.0f pnl_status=%s pnl_source=%s",
        trade_date, len(orders), realized_pnl, integrity.get("pnl_status"), integrity.get("pnl_source"),
    )

    backup_result = _backup_db(trade_date)

    return {
        "trade_date": trade_date,
        "total_orders": len(orders),
        "buy_orders": len(buy_list),
        "sell_orders": len(sell_list),
        "failed_orders": len(failed_list),
        "realized_pnl": realized_pnl,
        "realized_pnl_pct": avg_pnl_pct,
        "pnl_status": integrity.get("pnl_status", "unverified"),
        "pnl_source": integrity.get("pnl_source", "orders_without_fills"),
        "integrity_warnings": integrity.get("warnings", []),
        "pending_buy_orders": integrity.get("pending_buy_orders", []),
        "incomplete_fill_orders": integrity.get("incomplete_fill_orders", []),
        "net_negative_positions": integrity.get("net_negative_positions", []),
        "duplicate_sell_orders": integrity.get("duplicate_sell_orders", []),
        "sell_qty_exceeds_buy_qty": integrity.get("sell_qty_exceeds_buy_qty", []),
        "legacy_residual_positions": integrity.get("legacy_residual_positions", []),
        "symbols_traded": symbols_traded,
        "market_tone": market_tone,
        "rulepack_id": rulepack_id,
        "backup": backup_result,
    }


def _backup_db(trade_date: str) -> dict[str, Any]:
    """SQLite DB 파일을 data/backups/ 디렉토리에 날짜별로 복사한다."""
    try:
        db_path = Path(settings.APP_DB_PATH)
        if not db_path.is_absolute():
            from pathlib import Path as _P
            import os
            db_path = _P(os.getcwd()) / db_path
        backup_dir = db_path.parent / "backups"
        backup_dir.mkdir(exist_ok=True)
        backup_path = backup_dir / f"stock_trading_bot_{trade_date}.sqlite3"
        shutil.copy2(db_path, backup_path)
        logger.info("SUCCESS: DB backup saved path=%s", backup_path)
        return {"ok": True, "path": str(backup_path)}
    except Exception as exc:
        logger.error("FAIL: DB backup failed reason=%s", exc)
        return {"ok": False, "error": str(exc)}


def get_trade_history(limit: int = 31) -> list[dict[str, Any]]:
    """daily_trade_summary 최근 N일 조회."""
    _ensure_tables()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM daily_trade_summary ORDER BY trade_date DESC LIMIT ?",
            (limit,),
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        if isinstance(d.get("symbols_traded"), str):
            try:
                d["symbols_traded"] = json.loads(d["symbols_traded"])
            except Exception:
                pass
        if isinstance(d.get("integrity_warnings"), str):
            try:
                d["integrity_warnings"] = json.loads(d["integrity_warnings"])
            except Exception:
                pass
        result.append(d)
    return result
