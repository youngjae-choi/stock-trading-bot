"""S10: 당일 거래 결과 요약 저장 + DB 파일 백업."""

from __future__ import annotations

import json
import logging
import sqlite3
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
            ("net_pnl", "ALTER TABLE daily_trade_summary ADD COLUMN net_pnl REAL NOT NULL DEFAULT 0.0"),
            ("net_pnl_pct", "ALTER TABLE daily_trade_summary ADD COLUMN net_pnl_pct REAL NOT NULL DEFAULT 0.0"),
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

    # 거래 비용 설정 로드
    commission_rate = 0.0
    transaction_tax_rate = 0.0
    try:
        with get_connection() as conn:
            def _read_setting(key: str, default: float) -> float:
                row = conn.execute("SELECT value_json FROM system_settings WHERE key=?", (key,)).fetchone()
                if row:
                    import json as _j
                    return float(_j.loads(row["value_json"]) or default)
                return default
            commission_rate = _read_setting("trading.commission_rate", 0.015) / 100.0
            transaction_tax_rate = _read_setting("trading.transaction_tax_rate", 0.20) / 100.0
    except Exception as _cost_exc:
        logger.warning("WARN: DailySummary 거래 비용 설정 로드 실패, 기본값 사용 reason=%s", _cost_exc)

    # 실현 손익 계산 — trade_pairs 페어 원장(SSOT)으로 단일화한다(A2).
    # 구식 주문가 인라인 계산은 체결가·FIFO·원가보강(흡수 포지션)을 반영하지 못해
    # day_score/Review와 어긋났다. 그날 종료(rep_date==trade_date) 완료 페어만 합산한다.
    # net(비용 차감)·평균 수익률은 페어 단위로 동일 비용식을 적용해 산출한다.
    from .trade_pairs import get_trade_pairs

    gross_pnl = 0.0
    net_pnl = 0.0
    realized_pnl_pcts: list[float] = []
    net_pnl_pcts: list[float] = []
    cost_basis_contributed = False
    try:
        day_pairs = [
            p for p in get_trade_pairs(trade_date, trade_date)
            if p.get("trade_date") == trade_date and p.get("pnl_amount") is not None
        ]
    except Exception as _tp_exc:
        logger.warning("WARN: DailySummary trade_pairs 집계 실패 reason=%s", _tp_exc)
        day_pairs = []
    for p in day_pairs:
        gross = float(p.get("pnl_amount") or 0)
        buy_p = float(p.get("buy_price") or 0)
        sell_p = float(p.get("sell_price") or 0)
        matched = min(int(p.get("buy_qty") or 0), int(p.get("sell_qty") or 0))
        gross_pnl += gross
        if p.get("cost_basis_source"):
            cost_basis_contributed = True
        if buy_p > 0 and sell_p > 0 and matched > 0:
            buy_amount = buy_p * matched
            sell_amount = sell_p * matched
            cost = buy_amount * commission_rate + sell_amount * (commission_rate + transaction_tax_rate)
            net_pnl += gross - cost
            pnl_pct = float(p.get("pnl_pct") or 0)
            realized_pnl_pcts.append(pnl_pct)
            net_pnl_pcts.append(pnl_pct - (commission_rate * 2 + transaction_tax_rate) * 100)
        else:
            net_pnl += gross

    # realized_pnl = gross (기존 컬럼 유지, 하위호환), net_pnl 별도
    realized_pnl = gross_pnl
    avg_pnl_pct = sum(realized_pnl_pcts) / len(realized_pnl_pcts) if realized_pnl_pcts else 0.0
    avg_net_pnl_pct = sum(net_pnl_pcts) / len(net_pnl_pcts) if net_pnl_pcts else 0.0
    symbols_traded = list({o.get("symbol") for o in orders if o.get("symbol")})
    integrity = summarize_order_integrity(trade_date)
    # pnl_source: 흡수 원가가 기여하면 'fills+cost_basis', 아니면 무결성 판정값(fills/fills_incomplete 등) 보존.
    pnl_source = "fills+cost_basis" if cost_basis_contributed else integrity.get("pnl_source", "orders_without_fills")

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
                   realized_pnl=?, realized_pnl_pct=?, net_pnl=?, net_pnl_pct=?,
                   symbols_traded=?, market_tone=?, rulepack_id=?, pnl_status=?, pnl_source=?,
                   integrity_warnings=?, updated_at=?
                   WHERE trade_date=?""",
                (
                    len(orders), len(buy_list), len(sell_list), len(failed_list),
                    realized_pnl, avg_pnl_pct, net_pnl, avg_net_pnl_pct,
                    json.dumps(symbols_traded),
                    market_tone, rulepack_id,
                    integrity.get("pnl_status", "unverified"),
                    pnl_source,
                    json_compact(integrity.get("warnings", [])),
                    now_iso, trade_date,
                ),
            )
        else:
            conn.execute(
                """INSERT INTO daily_trade_summary
                   (id, trade_date, total_orders, buy_orders, sell_orders, failed_orders,
                    realized_pnl, realized_pnl_pct, net_pnl, net_pnl_pct,
                    symbols_traded, market_tone, rulepack_id,
                    pnl_status, pnl_source, integrity_warnings, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    summary_id, trade_date,
                    len(orders), len(buy_list), len(sell_list), len(failed_list),
                    realized_pnl, avg_pnl_pct, net_pnl, avg_net_pnl_pct,
                    json.dumps(symbols_traded),
                    market_tone, rulepack_id,
                    integrity.get("pnl_status", "unverified"),
                    pnl_source,
                    json_compact(integrity.get("warnings", [])),
                    now_iso, now_iso,
                ),
            )

    logger.info(
        "SUCCESS: DailySummary saved trade_date=%s orders=%d pnl=%.0f pnl_status=%s pnl_source=%s",
        trade_date, len(orders), realized_pnl, integrity.get("pnl_status"), pnl_source,
    )

    # False Positive 자동 생성: 당일 매도 완료된 손실 거래를 탐지해 DB에 저장
    fp_result: dict[str, Any] = {"ok": False, "error": "skipped"}
    try:
        from .false_positive import generate_false_positives_for_date
        fp_result = generate_false_positives_for_date(trade_date)
        fp_result["ok"] = True
        logger.info(
            "SUCCESS: DailySummary false_positive generated trade_date=%s saved=%d skipped=%d",
            trade_date,
            len(fp_result.get("saved", [])),
            len(fp_result.get("skipped", [])),
        )
    except Exception as exc:
        fp_result = {"ok": False, "error": str(exc)}
        logger.warning("WARN: DailySummary false_positive generation failed reason=%s", exc)

    backup_result = _backup_db(trade_date)

    return {
        "trade_date": trade_date,
        "total_orders": len(orders),
        "buy_orders": len(buy_list),
        "sell_orders": len(sell_list),
        "failed_orders": len(failed_list),
        "realized_pnl": realized_pnl,
        "realized_pnl_pct": avg_pnl_pct,
        "net_pnl": net_pnl,
        "net_pnl_pct": avg_net_pnl_pct,
        "trading_cost_rate_pct": round((commission_rate * 2 + transaction_tax_rate) * 100, 4),
        "pnl_status": integrity.get("pnl_status", "unverified"),
        "pnl_source": pnl_source,
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
        "false_positive": fp_result,
    }


def _backup_db(trade_date: str, retention: int = 30) -> dict[str, Any]:
    """SQLite 온라인 백업 API로 data/backups/에 날짜별 일관 스냅샷을 만든다.

    shutil.copy2(생파일 복사)는 동시 쓰기/WAL 중에 불일치·손상 백업을 만들 수 있어
    sqlite3 .backup(온라인 백업)으로 교체. 백업 후 integrity_check로 검증하고, 손상이면
    실패로 처리(나쁜 백업을 남기지 않음). 오래된 백업은 retention일치만 보관.
    """
    try:
        db_path = Path(settings.APP_DB_PATH)
        if not db_path.is_absolute():
            import os
            db_path = Path(os.getcwd()) / db_path
        backup_dir = db_path.parent / "backups"
        backup_dir.mkdir(exist_ok=True)
        backup_path = backup_dir / f"stock_trading_bot_{trade_date}.sqlite3"

        # 온라인 백업 — 동시 쓰기/WAL 중에도 일관된 스냅샷
        src = sqlite3.connect(str(db_path))
        try:
            dst = sqlite3.connect(str(backup_path))
            try:
                with dst:
                    src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()

        # 무결성 검증 — 손상 백업은 남기지 않음
        verify = sqlite3.connect(str(backup_path))
        try:
            integrity = verify.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            verify.close()
        if integrity != "ok":
            logger.error("FAIL: DB backup integrity=%s path=%s — 백업 폐기", integrity, backup_path)
            try:
                backup_path.unlink()
            except OSError:
                pass
            return {"ok": False, "error": f"integrity_check={integrity}"}

        # 보관 정책 — 최근 retention개만 유지
        try:
            backups = sorted(backup_dir.glob("stock_trading_bot_*.sqlite3"))
            for old in backups[:-retention]:
                old.unlink()
        except OSError as ret_exc:
            logger.warning("WARN: DB backup 보관정책 정리 실패 — %s", ret_exc)

        logger.info("SUCCESS: DB backup saved path=%s integrity=ok", backup_path)
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
