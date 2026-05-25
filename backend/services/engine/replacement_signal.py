"""Replacement signal generation for intraday reselection."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection
from ..settings_store import get_setting

logger = logging.getLogger("ReplacementSignal")
KST = ZoneInfo("Asia/Seoul")


def _today() -> str:
    """Return today's KST trade date."""
    return datetime.now(KST).strftime("%Y-%m-%d")


def _slot_now() -> str:
    """Return the current HH:MM slot when the caller does not pass one."""
    return datetime.now(KST).strftime("%H:%M")


def _to_float(value: Any, default: float = 0.0) -> float:
    """Convert score, percentage, and DB payload values to float safely."""
    try:
        return float(str(value).replace(",", "").strip() or default)
    except (TypeError, ValueError):
        return default


def _setting_bool(key: str, default: bool) -> bool:
    """Read a boolean system setting each time so kill switches apply immediately."""
    try:
        value = get_setting(key, default)
    except Exception as exc:
        logger.warning("WARN: ReplacementSignal setting read failed key=%s reason=%s", key, exc)
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def _setting_float(key: str, default: float) -> float:
    """Read a numeric system setting with a defensive fallback."""
    try:
        return _to_float(get_setting(key, default), default)
    except Exception as exc:
        logger.warning("WARN: ReplacementSignal setting read failed key=%s reason=%s", key, exc)
        return default


def _setting_int(key: str, default: int) -> int:
    """Read an integer system setting with a defensive fallback."""
    try:
        return int(_to_float(get_setting(key, default), float(default)))
    except Exception as exc:
        logger.warning("WARN: ReplacementSignal setting read failed key=%s reason=%s", key, exc)
        return default


def _candidate_symbol(candidate: dict[str, Any]) -> str:
    """Extract the canonical symbol from S4/S5 compatible candidate keys."""
    return str(candidate.get("symbol") or candidate.get("ticker") or candidate.get("code") or "").strip()


def _candidate_score(candidate: dict[str, Any]) -> float:
    """Extract a comparable candidate score from known S4/S6 score fields."""
    return _to_float(
        candidate.get("suitability_score")
        if candidate.get("suitability_score") is not None
        else candidate.get("score")
        if candidate.get("score") is not None
        else candidate.get("confidence")
    )


def _ensure_replacement_signals_table() -> None:
    """Create the replacement signal table for standalone tests or old databases."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS replacement_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date TEXT NOT NULL,
                slot TEXT NOT NULL,
                current_symbol TEXT NOT NULL,
                current_score REAL NOT NULL,
                current_pnl_pct REAL,
                new_symbol TEXT NOT NULL,
                new_score REAL NOT NULL,
                score_gap REAL NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_replacement_signals_date ON replacement_signals(trade_date)")


def _symbol_names(symbols: list[str]) -> dict[str, str]:
    """Load display names for symbols from the local symbol master."""
    if not symbols:
        return {}
    placeholders = ",".join("?" for _ in symbols)
    try:
        with get_connection() as conn:
            rows = conn.execute(f"SELECT symbol, name FROM symbols WHERE symbol IN ({placeholders})", symbols).fetchall()
        return {str(row["symbol"]): str(row["name"] or "") for row in rows}
    except Exception as exc:
        logger.warning("WARN: ReplacementSignal symbol name lookup failed reason=%s", exc)
        return {}


def _latest_signal_score(symbol: str, trade_date: str) -> float:
    """Use the latest BUY signal confidence as the held position score fallback."""
    try:
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT confidence
                FROM trading_signals
                WHERE trade_date = ? AND symbol = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (trade_date, symbol),
            ).fetchone()
        return _to_float(row["confidence"]) if row else 0.0
    except Exception:
        return 0.0


def _current_score(position: dict[str, Any], trade_date: str) -> float:
    """Resolve the score of a held position from memory fields or persisted BUY signal."""
    direct = _candidate_score(position)
    if direct > 0:
        return direct
    symbol = str(position.get("symbol") or "").strip()
    return _latest_signal_score(symbol, trade_date) if symbol else 0.0


def _existing_signal_counts(trade_date: str, current_symbol: str) -> tuple[int, int]:
    """Return today's signal counts for all symbols and the current held symbol."""
    _ensure_replacement_signals_table()
    with get_connection() as conn:
        daily_row = conn.execute(
            "SELECT COUNT(*) AS count FROM replacement_signals WHERE trade_date = ?",
            (trade_date,),
        ).fetchone()
        symbol_row = conn.execute(
            "SELECT COUNT(*) AS count FROM replacement_signals WHERE trade_date = ? AND current_symbol = ?",
            (trade_date, current_symbol),
        ).fetchone()
    return int(daily_row["count"] or 0), int(symbol_row["count"] or 0)


def _save_signal(
    *,
    trade_date: str,
    slot: str,
    current_symbol: str,
    current_score: float,
    current_pnl_pct: float | None,
    new_symbol: str,
    new_score: float,
    score_gap: float,
    reason: str,
) -> int:
    """Persist one replacement signal and return its row id."""
    _ensure_replacement_signals_table()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO replacement_signals
                (trade_date, slot, current_symbol, current_score, current_pnl_pct,
                 new_symbol, new_score, score_gap, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade_date,
                slot,
                current_symbol,
                current_score,
                current_pnl_pct,
                new_symbol,
                new_score,
                score_gap,
                reason,
            ),
        )
        return int(cursor.lastrowid)


async def _notify_signal(signal: dict[str, Any]) -> None:
    """Send a Telegram notification for a generated replacement signal."""
    try:
        from ..alert_service import send_telegram_alert

        current_name = signal.get("current_name") or signal["current_symbol"]
        new_name = signal.get("new_name") or signal["new_symbol"]
        pnl_text = "확인불가" if signal.get("current_pnl_pct") is None else f"{signal['current_pnl_pct']:+.1f}%"
        body = (
            f"📊 현재 보유: {current_name}({signal['current_symbol']}) 점수 {signal['current_score']:.2f}, 손익 {pnl_text}\n"
            f"🎯 신규 후보: {new_name}({signal['new_symbol']}) 점수 {signal['new_score']:.2f} (+{signal['score_gap'] * 100:.1f}%)\n"
            f"사유: {signal['reason']}\n"
            "※ 강제 교체 없음. 트레일링 스탑 발동 시 자연 교체."
        )
        await send_telegram_alert("교체 신호 발생", body)
    except Exception as exc:
        logger.warning("WARN: ReplacementSignal telegram alert failed reason=%s", exc)


async def evaluate_replacement_signals(
    new_candidates: dict[str, dict[str, Any]] | list[dict[str, Any]],
    current_positions: list[dict[str, Any]],
    slot: str | None = None,
    trade_date: str | None = None,
) -> dict[str, Any]:
    """Compare new candidates with held positions and persist signal-only replacements.

    Args:
        new_candidates: Fresh S4/S5 candidates from intraday reselection.
        current_positions: PositionManager holdings. No buy or sell order is created here.
        slot: Optional HH:MM slot for audit storage.
        trade_date: Optional YYYY-MM-DD trade date.
    """
    trade_date = trade_date or _today()
    slot = slot or _slot_now()
    logger.info("START: ReplacementSignal evaluate trade_date=%s slot=%s", trade_date, slot)

    if not _setting_bool("intraday_refresh.master_enabled", True):
        return {"ok": True, "enabled": False, "created": 0, "reason": "master_disabled", "signals": []}
    if not _setting_bool("intraday_refresh.replacement_signal_enabled", True):
        return {"ok": True, "enabled": False, "created": 0, "reason": "replacement_signal_disabled", "signals": []}

    candidates_iter = new_candidates.values() if isinstance(new_candidates, dict) else new_candidates
    candidates = [candidate for candidate in candidates_iter if isinstance(candidate, dict) and _candidate_symbol(candidate)]
    candidates.sort(key=_candidate_score, reverse=True)
    if not candidates or not current_positions:
        return {"ok": True, "enabled": True, "created": 0, "reason": "no_candidates_or_positions", "signals": []}

    threshold = _setting_float("intraday_refresh.replacement_score_gap", 0.15)
    max_per_symbol = _setting_int("intraday_refresh.max_replacement_per_symbol", 1)
    max_per_day = _setting_int("intraday_refresh.max_replacement_per_day", 5)
    names = _symbol_names(
        list(
            {
                *[_candidate_symbol(candidate) for candidate in candidates],
                *[str(position.get("symbol") or "").strip() for position in current_positions],
            }
        )
    )
    created: list[dict[str, Any]] = []

    for position in current_positions:
        current_symbol = str(position.get("symbol") or "").strip()
        if not current_symbol:
            continue
        daily_count, symbol_count = _existing_signal_counts(trade_date, current_symbol)
        if daily_count >= max_per_day:
            logger.info("INFO: ReplacementSignal daily limit reached count=%d limit=%d", daily_count, max_per_day)
            break
        if symbol_count >= max_per_symbol:
            continue

        current_score = _current_score(position, trade_date)
        if current_score <= 0:
            logger.warning("WARN: ReplacementSignal current score unavailable symbol=%s", current_symbol)
            continue

        best_candidate = next((candidate for candidate in candidates if _candidate_symbol(candidate) != current_symbol), None)
        if not best_candidate:
            continue
        new_symbol = _candidate_symbol(best_candidate)
        new_score = _candidate_score(best_candidate)
        score_gap = (new_score - current_score) / current_score if current_score > 0 else 0.0
        if score_gap < threshold:
            continue

        reason = (
            f"신규 후보 점수 우위 {score_gap * 100:.1f}% "
            f"(기준 {threshold * 100:.1f}%)"
        )
        pnl_pct = position.get("pnl_pct")
        current_pnl_pct = None if pnl_pct is None else _to_float(pnl_pct)
        row_id = _save_signal(
            trade_date=trade_date,
            slot=slot,
            current_symbol=current_symbol,
            current_score=current_score,
            current_pnl_pct=current_pnl_pct,
            new_symbol=new_symbol,
            new_score=new_score,
            score_gap=score_gap,
            reason=reason,
        )
        signal = {
            "id": row_id,
            "trade_date": trade_date,
            "slot": slot,
            "current_symbol": current_symbol,
            "current_name": str(position.get("name") or names.get(current_symbol) or ""),
            "current_score": current_score,
            "current_pnl_pct": current_pnl_pct,
            "new_symbol": new_symbol,
            "new_name": str(best_candidate.get("name") or names.get(new_symbol) or ""),
            "new_score": new_score,
            "score_gap": score_gap,
            "reason": reason,
        }
        created.append(signal)
        asyncio.create_task(_notify_signal(signal))
        logger.info(
            "SIGNAL: ReplacementSignal current=%s new=%s gap=%.3f row_id=%d",
            current_symbol,
            new_symbol,
            score_gap,
            row_id,
        )

    logger.info("SUCCESS: ReplacementSignal evaluate created=%d", len(created))
    return {"ok": True, "enabled": True, "created": len(created), "signals": created}


def get_replacement_signals(trade_date: str) -> list[dict[str, Any]]:
    """Return persisted replacement signals for one trade date."""
    _ensure_replacement_signals_table()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM replacement_signals WHERE trade_date = ? ORDER BY created_at ASC, id ASC",
            (trade_date,),
        ).fetchall()
    records = [dict(row) for row in rows]
    names = _symbol_names(
        list({symbol for row in records for symbol in (row.get("current_symbol"), row.get("new_symbol")) if symbol})
    )
    for row in records:
        row["current_name"] = names.get(str(row.get("current_symbol") or ""), "")
        row["new_name"] = names.get(str(row.get("new_symbol") or ""), "")
    return records
