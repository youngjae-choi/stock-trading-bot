"""False Positive Tracker."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection

logger = logging.getLogger("FalsePositive")


def _now_kst_iso() -> str:
    """Return the current KST timestamp for false positive rows."""
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()


def _json_dumps(value: Any) -> str:
    """Serialize applied id lists into compact JSON text."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_loads(value: str | None) -> list[Any]:
    """Parse JSON id list text and default to an empty list when malformed."""
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except (TypeError, json.JSONDecodeError):
        return []


def _row_to_dict(row: Any) -> dict[str, Any]:
    """Convert a SQLite row and decode JSON list columns for API responses."""
    payload = dict(row)
    payload["applied_knowledge_ids"] = _json_loads(payload.get("applied_knowledge_ids"))
    payload["applied_memory_ids"] = _json_loads(payload.get("applied_memory_ids"))
    return payload


def _validate_required(**values: Any) -> None:
    """Validate required false positive fields before persistence."""
    missing = [name for name, value in values.items() if value in (None, "")]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")


def _ensure_fp_pnl_columns() -> None:
    """Ensure buy_price/sell_price/pnl columns exist (migration for existing DBs)."""
    with get_connection() as conn:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(false_positive_cases)").fetchall()}
        for col, stmt in [
            ("buy_price",  "ALTER TABLE false_positive_cases ADD COLUMN buy_price  REAL"),
            ("sell_price", "ALTER TABLE false_positive_cases ADD COLUMN sell_price REAL"),
            ("pnl_amount", "ALTER TABLE false_positive_cases ADD COLUMN pnl_amount REAL"),
            ("pnl_pct",    "ALTER TABLE false_positive_cases ADD COLUMN pnl_pct    REAL"),
        ]:
            if col not in existing:
                conn.execute(stmt)


def _summarize_rule_matched(rule_matched_json: str) -> str:
    """rule_matched JSON 오브젝트를 짧은 텍스트 요약으로 변환한다."""
    try:
        rules = json.loads(rule_matched_json or "{}")
    except Exception:
        return ""
    parts: list[str] = []
    for k, v in rules.items():
        if isinstance(v, dict):
            if v.get("passed") or v.get("ok"):
                parts.append(k)
        elif v is True:
            parts.append(k)
    return ", ".join(parts[:4]) if parts else ""


def record_false_positive(
    trade_date: str,
    symbol: str,
    symbol_name: str,
    false_positive_type: str,
    original_score: float | None = None,
    original_confidence: float | None = None,
    assigned_profile: str | None = None,
    entry_reason: str = "",
    loss_reason: str = "",
    exit_reason: str = "",
    applied_knowledge_ids: list[str] | None = None,
    applied_memory_ids: list[str] | None = None,
    suggested_penalty: float | None = None,
    buy_price: float | None = None,
    sell_price: float | None = None,
    pnl_amount: float | None = None,
    pnl_pct: float | None = None,
) -> dict:
    """Persist a false positive case for later learning review.

    Args:
        trade_date: YYYY-MM-DD trade date.
        symbol: Stock symbol for the case.
        symbol_name: Display name for the symbol.
        false_positive_type: entry_fail, early_exit, or wrong_profile.
        original_score: Original screening score when available.
        original_confidence: Original AI confidence when available.
        assigned_profile: Risk profile assigned at entry time.
        entry_reason: Entry rationale text.
        loss_reason: Loss rationale text.
        exit_reason: Exit rationale text.
        applied_knowledge_ids: Expert Knowledge ids used in the decision.
        applied_memory_ids: Learning Memory ids used in the decision.
        suggested_penalty: Suggested penalty for future scoring.
        buy_price: Effective buy fill price.
        sell_price: Effective sell fill price.
        pnl_amount: Realized P&L in KRW.
        pnl_pct: Realized P&L percentage.
    """
    logger.info("START: FalsePositive record symbol=%s trade_date=%s", symbol, trade_date)
    _validate_required(trade_date=trade_date, symbol=symbol, false_positive_type=false_positive_type)
    _ensure_fp_pnl_columns()
    row_id = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO false_positive_cases
                (id, trade_date, symbol, symbol_name, false_positive_type,
                 original_score, original_confidence, assigned_profile, entry_reason,
                 loss_reason, exit_reason, applied_knowledge_ids, applied_memory_ids,
                 suggested_penalty, buy_price, sell_price, pnl_amount, pnl_pct, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row_id,
                trade_date,
                symbol,
                symbol_name or "",
                false_positive_type,
                original_score,
                original_confidence,
                assigned_profile,
                entry_reason,
                loss_reason,
                exit_reason,
                _json_dumps(applied_knowledge_ids or []),
                _json_dumps(applied_memory_ids or []),
                suggested_penalty,
                buy_price,
                sell_price,
                pnl_amount,
                pnl_pct,
                _now_kst_iso(),
            ),
        )
        row = conn.execute("SELECT * FROM false_positive_cases WHERE id = ?", (row_id,)).fetchone()
    logger.info("SUCCESS: FalsePositive record id=%s symbol=%s", row_id, symbol)
    return _row_to_dict(row)


def get_today_false_positives(trade_date: str) -> list[dict]:
    """Return false positive cases for one trade date.

    Args:
        trade_date: YYYY-MM-DD trade date.
    """
    logger.info("START: FalsePositive list trade_date=%s", trade_date)
    _ensure_fp_pnl_columns()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM false_positive_cases WHERE trade_date = ? ORDER BY created_at DESC",
            (trade_date,),
        ).fetchall()
    logger.info("SUCCESS: FalsePositive list trade_date=%s count=%d", trade_date, len(rows))
    return [_row_to_dict(row) for row in rows]


def get_false_positives(start_date: str, end_date: str) -> list[dict]:
    """날짜 범위 내 false positive 케이스를 최신순으로 반환한다.

    Args:
        start_date: YYYY-MM-DD 시작일.
        end_date: YYYY-MM-DD 종료일.
    """
    logger.info("START: FalsePositive range start=%s end=%s", start_date, end_date)
    _ensure_fp_pnl_columns()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM false_positive_cases
            WHERE trade_date >= ? AND trade_date <= ?
            ORDER BY trade_date DESC, created_at DESC
            """,
            (start_date, end_date),
        ).fetchall()
    logger.info("SUCCESS: FalsePositive range count=%d", len(rows))
    return [_row_to_dict(row) for row in rows]


def generate_false_positives_for_date(trade_date: str) -> dict:
    """매도일 기준 손실 거래를 분석해 false_positive_cases에 자동 저장한다.

    trade_pairs에서 매도완료 + pnl < 0 + rep_date == trade_date인 페어를 추출해
    아직 기록되지 않은 케이스를 DB에 저장한다.

    Args:
        trade_date: YYYY-MM-DD 매도 기준 날짜.
    """
    from .trade_pairs import get_trade_pairs

    logger.info("START: FalsePositive generate trade_date=%s", trade_date)
    _ensure_fp_pnl_columns()

    # 매수는 최대 30일 전일 수 있으므로 넉넉하게 조회
    dt = datetime.fromisoformat(trade_date)
    start = (dt - timedelta(days=30)).strftime("%Y-%m-%d")

    pairs = get_trade_pairs(start, trade_date)

    # 매도완료 + 손실 + 매도 대표날짜가 trade_date인 페어만 대상
    losing = [
        p for p in pairs
        if p["trade_date"] == trade_date
        and p["status"] == "매도완료"
        and p.get("pnl_amount") is not None
        and p["pnl_amount"] < 0
    ]

    saved: list[str] = []
    skipped: list[str] = []

    for pair in losing:
        symbol = pair["symbol"]

        # 중복 방지: 같은 (날짜, 종목) 조합이 이미 기록된 경우 스킵
        with get_connection() as conn:
            existing = conn.execute(
                "SELECT id FROM false_positive_cases WHERE trade_date = ? AND symbol = ? LIMIT 1",
                (trade_date, symbol),
            ).fetchone()
        if existing:
            skipped.append(symbol)
            continue

        # 매수 주문의 거래일 (trading_signals 조회용)
        buy_orders = [o for o in (pair.get("orders") or []) if o.get("side") == "buy"]
        buy_date = buy_orders[0]["trade_date"] if buy_orders else trade_date

        # 진입 신호 정보 조회
        original_confidence: float | None = None
        assigned_profile: str | None = None
        entry_reason = "S6 BUY 신호 발생"
        try:
            with get_connection() as conn:
                sig_row = conn.execute(
                    """
                    SELECT confidence, rule_matched, profile_assigned
                    FROM trading_signals
                    WHERE symbol = ? AND trade_date = ? AND signal_type = 'BUY'
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (symbol, buy_date),
                ).fetchone()
            if sig_row:
                original_confidence = float(sig_row["confidence"] or 0)
                assigned_profile = sig_row["profile_assigned"]
                rule_summary = _summarize_rule_matched(sig_row["rule_matched"] or "{}")
                if rule_summary:
                    conf_str = f"{original_confidence:.2f}" if original_confidence else "-"
                    entry_reason = f"진입조건 충족: {rule_summary} (confidence={conf_str})"
        except Exception as exc:
            logger.warning("WARN: FalsePositive signal lookup symbol=%s error=%s", symbol, exc)

        # 손익 정보
        buy_price = float(pair.get("buy_price") or 0)
        sell_price = float(pair.get("sell_price") or 0)
        pnl_amount = float(pair.get("pnl_amount") or 0)
        pnl_pct = float(pair.get("pnl_pct") or 0)
        exit_reason_text = str(pair.get("exit_reason") or "")

        loss_reason = (
            f"매수가 {buy_price:,.0f}원 → 매도가 {sell_price:,.0f}원, "
            f"손실 {pnl_pct:.1f}% ({pnl_amount:+,.0f}원)"
        )
        if exit_reason_text:
            loss_reason += f". 청산사유: {exit_reason_text}"

        try:
            record_false_positive(
                trade_date=trade_date,
                symbol=symbol,
                symbol_name=pair.get("name") or symbol,
                false_positive_type="entry_fail",
                original_confidence=original_confidence,
                assigned_profile=assigned_profile,
                entry_reason=entry_reason,
                loss_reason=loss_reason,
                exit_reason=exit_reason_text,
                suggested_penalty=min(abs(pnl_pct) / 100, 1.0) if pnl_pct else None,
                buy_price=buy_price if buy_price > 0 else None,
                sell_price=sell_price if sell_price > 0 else None,
                pnl_amount=pnl_amount,
                pnl_pct=pnl_pct,
            )
            saved.append(symbol)
        except Exception as exc:
            logger.warning("WARN: FalsePositive save failed symbol=%s error=%s", symbol, exc)

    logger.info(
        "SUCCESS: FalsePositive generate trade_date=%s losing=%d saved=%d skipped=%d",
        trade_date, len(losing), len(saved), len(skipped),
    )
    return {
        "trade_date": trade_date,
        "total_losing": len(losing),
        "saved": saved,
        "skipped": skipped,
    }
