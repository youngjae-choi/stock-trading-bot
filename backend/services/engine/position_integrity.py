"""DB-only helpers for position, liquidation, and PnL integrity checks."""

from __future__ import annotations

import json
import logging
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection

logger = logging.getLogger("PositionIntegrity")

_ACTIVE_BUY_STATUSES = {"submitted", "filled", "partial_fill"}
_ACTIVE_SELL_STATUSES = {"submitted", "filled", "partial_fill", "submitted_without_order_no", "submit_uncertain"}
_UNVERIFIED_SELL_STATUSES = {"submitted", "submitted_without_order_no", "submit_uncertain"}
_UNVERIFIED_ORDER_STATUSES = {"submitted", "submitted_without_order_no", "submit_uncertain"}
_POSITION_FILLED_STATUSES = {"filled", "partial_fill"}


def _now_kst_iso() -> str:
    """Return the current KST timestamp for integrity rows."""
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()


def _table_exists(table_name: str) -> bool:
    """Return whether a SQLite table exists.

    Args:
        table_name: SQLite table name to inspect.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
    return row is not None


def _safe_int(value: Any) -> int:
    """Convert a DB value to int while treating blanks as zero.

    Args:
        value: Raw DB value.
    """
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    """Convert a DB value to float while treating blanks as zero.

    Args:
        value: Raw DB value.
    """
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _table_exists_in_connection(conn: Any, table_name: str) -> bool:
    """Return whether a table exists using the caller's SQLite connection.

    Args:
        conn: Open SQLite connection.
        table_name: SQLite table name to inspect.
    """
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def _fill_quantity_column(conn: Any) -> str:
    """Return the fills quantity column exposed by the current schema.

    Args:
        conn: Open SQLite connection.
    """
    columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(fills)").fetchall()}
    for column in ("quantity", "filled_qty", "fill_qty", "qty"):
        if column in columns:
            return column
    return "quantity"


def _load_fill_quantities_for_orders(conn: Any, order_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Load fill counts and quantities, restricted to the supplied trading order ids.

    Args:
        conn: Open SQLite connection.
        order_ids: trading_orders.id values for one trade date.
    """
    safe_ids = [str(order_id) for order_id in order_ids if str(order_id or "").strip()]
    if not safe_ids or not _table_exists_in_connection(conn, "fills"):
        return {}
    quantity_column = _fill_quantity_column(conn)
    placeholders = ",".join("?" for _ in safe_ids)
    rows = conn.execute(
        f"""
        SELECT order_id, COUNT(*) AS fill_count, COALESCE(SUM({quantity_column}), 0) AS fill_qty
        FROM fills
        WHERE order_id IN ({placeholders})
        GROUP BY order_id
        """,
        safe_ids,
    ).fetchall()
    return {
        str(row["order_id"]): {"fill_count": _safe_int(row["fill_count"]), "fill_qty": _safe_float(row["fill_qty"])}
        for row in rows
        if row["order_id"]
    }


def _verified_position_qty(order: dict[str, Any], fill_data: dict[str, Any] | None) -> int:
    """Return the quantity safe to use for DB fallback position math.

    Args:
        order: trading_orders row.
        fill_data: Optional fill aggregate for this order id.
    """
    status = str(order.get("status") or "").strip().lower()
    order_qty = _safe_int(order.get("qty"))
    if status == "filled":
        return order_qty
    if status == "partial_fill":
        return _safe_int((fill_data or {}).get("fill_qty"))
    return 0


def _load_verified_position_summaries(
    trade_date: str,
    candidate_symbols: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Summarize DB positions using only filled or fill-backed partial-fill quantities.

    Args:
        trade_date: YYYY-MM-DD trade date to inspect.
        candidate_symbols: Optional symbol allow-list for restart restore.
    """
    if not _table_exists("trading_orders"):
        return []

    safe_symbols = [str(symbol).strip() for symbol in candidate_symbols or [] if str(symbol).strip()]
    params: list[Any] = [trade_date]
    symbol_filter = ""
    if safe_symbols:
        symbol_filter = f"AND symbol IN ({','.join('?' for _ in safe_symbols)})"
        params.extend(safe_symbols)

    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM trading_orders
            WHERE trade_date = ?
              {symbol_filter}
            ORDER BY created_at ASC
            """,
            params,
        ).fetchall()
        orders = [dict(row) for row in rows]
        fills_by_order = _load_fill_quantities_for_orders(
            conn,
            [str(order.get("id") or "") for order in orders],
        )

    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "symbol": "",
            "name": "",
            "buy_qty": 0,
            "sell_qty": 0,
            "net_qty": 0,
            "buy_count": 0,
            "sell_count": 0,
            "pending_buy_qty": 0,
            "pending_buy_count": 0,
            "has_submitted_sell": False,
            "has_uncertain_sell": False,
            "latest_buy_price": 0.0,
            "latest_buy_created_at": "",
        }
    )
    for order in orders:
        symbol = str(order.get("symbol") or "").strip()
        if not symbol:
            continue
        side = str(order.get("side") or "").strip().lower()
        status = str(order.get("status") or "").strip().lower()
        order_qty = _safe_int(order.get("qty"))
        if order_qty <= 0:
            continue

        item = grouped[symbol]
        item["symbol"] = symbol
        item["name"] = item["name"] or str(order.get("name") or "")
        if side == "buy" and status in _UNVERIFIED_ORDER_STATUSES:
            item["pending_buy_qty"] += order_qty
            item["pending_buy_count"] += 1
            continue
        if side == "sell" and status in _UNVERIFIED_SELL_STATUSES:
            item["has_submitted_sell"] = True
            if status in {"submitted_without_order_no", "submit_uncertain"}:
                item["has_uncertain_sell"] = True
            continue
        if side not in {"buy", "sell"} or status not in _POSITION_FILLED_STATUSES:
            continue

        qty = _verified_position_qty(order, fills_by_order.get(str(order.get("id") or "")))
        if qty <= 0:
            continue
        if side == "buy":
            item["buy_qty"] += qty
            item["buy_count"] += 1
            item["latest_buy_price"] = _safe_float(order.get("price"))
            item["latest_buy_created_at"] = str(order.get("created_at") or "")
        else:
            item["sell_qty"] += qty
            item["sell_count"] += 1

    summaries = []
    for item in grouped.values():
        item["net_qty"] = int(item["buy_qty"]) - int(item["sell_qty"])
        summaries.append(dict(item))
    return sorted(summaries, key=lambda item: str(item.get("symbol") or ""))


def load_order_net_positions(trade_date: str, candidate_symbols: list[str] | None = None) -> list[dict[str, Any]]:
    """Summarize active buy/sell order quantities into DB net positions.

    Args:
        trade_date: YYYY-MM-DD trade date to inspect.
        candidate_symbols: Optional symbol allow-list for restart restore.
    """
    if not _table_exists("trading_orders"):
        return []

    safe_symbols = [str(symbol).strip() for symbol in candidate_symbols or [] if str(symbol).strip()]
    params: list[Any] = [trade_date]
    symbol_filter = ""
    if safe_symbols:
        symbol_filter = f"AND symbol IN ({','.join('?' for _ in safe_symbols)})"
        params.extend(safe_symbols)

    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM trading_orders
            WHERE trade_date = ?
              {symbol_filter}
            ORDER BY created_at ASC
            """,
            params,
        ).fetchall()

    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "symbol": "",
            "name": "",
            "buy_qty": 0,
            "sell_qty": 0,
            "net_qty": 0,
            "buy_count": 0,
            "sell_count": 0,
            "has_submitted_sell": False,
            "has_uncertain_sell": False,
            "latest_buy_price": 0.0,
            "latest_buy_created_at": "",
        }
    )
    for row in rows:
        order = dict(row)
        symbol = str(order.get("symbol") or "").strip()
        if not symbol:
            continue
        side = str(order.get("side") or "").strip().lower()
        status = str(order.get("status") or "").strip().lower()
        qty = _safe_int(order.get("qty"))
        if qty <= 0:
            continue

        item = grouped[symbol]
        item["symbol"] = symbol
        item["name"] = item["name"] or str(order.get("name") or "")
        if side == "buy" and status in _ACTIVE_BUY_STATUSES:
            item["buy_qty"] += qty
            item["buy_count"] += 1
            item["latest_buy_price"] = _safe_float(order.get("price"))
            item["latest_buy_created_at"] = str(order.get("created_at") or "")
        elif side == "sell" and status in _ACTIVE_SELL_STATUSES:
            item["sell_qty"] += qty
            item["sell_count"] += 1
            if status in _UNVERIFIED_ORDER_STATUSES:
                item["has_submitted_sell"] = True
            if status in {"submitted_without_order_no", "submit_uncertain"}:
                item["has_uncertain_sell"] = True

    summaries = []
    for item in grouped.values():
        item["net_qty"] = int(item["buy_qty"]) - int(item["sell_qty"])
        summaries.append(dict(item))
    return sorted(summaries, key=lambda item: str(item.get("symbol") or ""))


def find_active_sell_order(trade_date: str, symbol: str) -> dict[str, Any] | None:
    """Return the latest unverified sell order for a symbol, if any.

    Args:
        trade_date: YYYY-MM-DD trade date to inspect.
        symbol: Stock symbol to guard against duplicate sells.
    """
    safe_symbol = str(symbol or "").strip()
    if not safe_symbol or not _table_exists("trading_orders"):
        return None
    statuses = sorted(_UNVERIFIED_SELL_STATUSES)
    placeholders = ",".join("?" for _ in statuses)
    with get_connection() as conn:
        row = conn.execute(
            f"""
            SELECT *
            FROM trading_orders
            WHERE trade_date = ?
              AND symbol = ?
              AND side = 'sell'
              AND status IN ({placeholders})
            ORDER BY created_at DESC
            LIMIT 1
            """,
            [trade_date, safe_symbol, *statuses],
        ).fetchone()
    return dict(row) if row else None


def build_restore_position_plan(trade_date: str, candidate_symbols: list[str] | None = None) -> list[dict[str, Any]]:
    """Build restart restore decisions from buy-sell net quantities and stop state.

    Args:
        trade_date: YYYY-MM-DD trade date to inspect.
        candidate_symbols: Optional symbol allow-list from current S4/S5 candidates.
    """
    summaries = _load_verified_position_summaries(trade_date, candidate_symbols)
    if not summaries or not _table_exists("position_stop_states"):
        return [
            {**summary, "should_restore": False, "skipped_reason": "missing_stop_state"}
            for summary in summaries
        ]

    safe_symbols = [str(item.get("symbol") or "").strip() for item in summaries if item.get("symbol")]
    params: list[Any] = [trade_date]
    symbol_filter = ""
    if safe_symbols:
        symbol_filter = f"AND symbol_code IN ({','.join('?' for _ in safe_symbols)})"
        params.extend(safe_symbols)

    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT ps.*
            FROM position_stop_states ps
            JOIN (
                SELECT symbol_code, MAX(last_updated_at) AS latest_updated_at
                FROM position_stop_states
                WHERE date(last_updated_at) = ?
                  {symbol_filter}
                GROUP BY symbol_code
            ) latest
              ON latest.symbol_code = ps.symbol_code
             AND latest.latest_updated_at = ps.last_updated_at
            """,
            params,
        ).fetchall()
    stop_states = {str(row["symbol_code"]): dict(row) for row in rows}

    plan: list[dict[str, Any]] = []
    for summary in summaries:
        symbol = str(summary.get("symbol") or "")
        stop_state = stop_states.get(symbol, {})
        skipped_reason = ""
        if _safe_int(summary.get("buy_qty")) <= 0:
            skipped_reason = "no_active_buy"
        elif bool(summary.get("has_submitted_sell")):
            skipped_reason = "sell_submitted_unverified"
        elif _safe_int(summary.get("net_qty")) <= 0:
            skipped_reason = "net_qty_closed"
        elif _safe_float(stop_state.get("entry_price")) <= 0:
            skipped_reason = "missing_stop_state"
        plan.append(
            {
                **summary,
                **stop_state,
                "qty": max(0, _safe_int(summary.get("net_qty"))),
                "should_restore": not skipped_reason,
                "skipped_reason": skipped_reason,
            }
        )
    return plan


def load_db_open_positions(trade_date: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return safe DB net positions and skipped duplicate/uncertain sell rows.

    Args:
        trade_date: YYYY-MM-DD trade date to inspect.
    """
    positions: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for summary in _load_verified_position_summaries(trade_date):
        net_qty = _safe_int(summary.get("net_qty"))
        if net_qty <= 0:
            if summary.get("has_submitted_sell") or _safe_int(summary.get("sell_qty")) > _safe_int(summary.get("buy_qty")):
                skipped.append({**summary, "skipped_reason": "net_qty_closed_or_negative"})
            continue
        if summary.get("has_submitted_sell"):
            skipped.append({**summary, "skipped_reason": "sell_submitted_unverified"})
            continue
        positions.append(
            {
                "symbol": summary.get("symbol"),
                "name": summary.get("name") or "",
                "qty": net_qty,
                "avg_price": _safe_float(summary.get("latest_buy_price")),
            }
        )
    return positions, skipped


def detect_legacy_residual_positions(trade_date: str) -> list[dict[str, Any]]:
    """Detect strategy-owned net positions from dates before the target trade date.

    Args:
        trade_date: YYYY-MM-DD trade date whose prior residuals should be flagged.
    """
    if not _table_exists("trading_orders"):
        return []
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM trading_orders
            WHERE trade_date < ?
            ORDER BY trade_date ASC, created_at ASC
            """,
            (trade_date,),
        ).fetchall()
        orders = [dict(row) for row in rows]
        fills_by_order = _load_fill_quantities_for_orders(
            conn,
            [str(order.get("id") or "") for order in orders],
        )

    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"symbol": "", "name": "", "first_trade_date": "", "buy_qty": 0, "sell_qty": 0, "net_qty": 0}
    )
    for order in orders:
        symbol = str(order.get("symbol") or "").strip()
        if not symbol:
            continue
        side = str(order.get("side") or "").strip().lower()
        status = str(order.get("status") or "").strip().lower()
        qty = _verified_position_qty(order, fills_by_order.get(str(order.get("id") or "")))
        if qty <= 0:
            continue
        item = grouped[symbol]
        item["symbol"] = symbol
        item["name"] = item["name"] or str(order.get("name") or "")
        item["first_trade_date"] = item["first_trade_date"] or str(order.get("trade_date") or "")
        if side == "buy" and status in _POSITION_FILLED_STATUSES:
            item["buy_qty"] += qty
        elif side == "sell" and status in _POSITION_FILLED_STATUSES:
            item["sell_qty"] += qty

    residuals = []
    for item in grouped.values():
        item["net_qty"] = int(item["buy_qty"]) - int(item["sell_qty"])
        if item["net_qty"] > 0:
            residuals.append(dict(item))
    return sorted(residuals, key=lambda item: (str(item.get("first_trade_date") or ""), str(item.get("symbol") or "")))


def _ensure_system_alerts_table() -> None:
    """Create system_alerts when a temp smoke DB has not run full migrations."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS system_alerts (
                id TEXT PRIMARY KEY,
                trade_date TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'WARNING',
                title TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT '',
                acknowledged INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )


def create_integrity_alert_once(
    trade_date: str,
    *,
    alert_type: str,
    severity: str,
    title: str,
    detail: str,
) -> bool:
    """Persist one deduplicated system alert for review/operator visibility.

    Args:
        trade_date: YYYY-MM-DD trade date for the alert.
        alert_type: Existing alert taxonomy key such as risk_guard or fill_missing.
        severity: INFO, WARNING, or CRITICAL.
        title: Short operator-facing alert title.
        detail: Detailed JSON or text context.
    """
    _ensure_system_alerts_table()
    clean_title = str(title or "").strip()
    if not clean_title:
        return False
    with get_connection() as conn:
        existing = conn.execute(
            """
            SELECT id
            FROM system_alerts
            WHERE trade_date = ?
              AND alert_type = ?
              AND title = ?
              AND acknowledged = 0
            LIMIT 1
            """,
            (trade_date, alert_type, clean_title),
        ).fetchone()
        if existing:
            return False
        conn.execute(
            """
            INSERT INTO system_alerts
                (id, trade_date, alert_type, severity, title, detail, acknowledged, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (str(uuid.uuid4()), trade_date, alert_type, severity, clean_title, detail, _now_kst_iso()),
        )
    logger.warning("WARN: [Integrity] alert created type=%s title=%s", alert_type, clean_title)
    return True


def summarize_order_integrity(trade_date: str) -> dict[str, Any]:
    """Summarize whether orders/fills are complete enough to verify PnL.

    Args:
        trade_date: YYYY-MM-DD trade date to inspect.
    """
    if not _table_exists("trading_orders"):
        return {
            "pnl_status": "no_orders",
            "pnl_source": "none",
            "warnings": [],
            "submitted_only_orders": 0,
            "pending_buy_orders": [],
            "submitted_without_order_no": 0,
            "incomplete_fill_orders": [],
            "net_negative_positions": [],
            "duplicate_sell_orders": [],
            "sell_qty_exceeds_buy_qty": [],
        }

    with get_connection() as conn:
        orders = conn.execute("SELECT * FROM trading_orders WHERE trade_date = ?", (trade_date,)).fetchall()
        order_dicts = [dict(row) for row in orders]
        fills_by_order = _load_fill_quantities_for_orders(
            conn,
            [str(order.get("id") or "") for order in order_dicts],
        )

    unverified_orders = [
        order
        for order in order_dicts
        if str(order.get("status") or "").lower() in _UNVERIFIED_ORDER_STATUSES
        and not fills_by_order.get(str(order.get("id") or ""))
    ]
    pending_buy_orders = [
        {
            "order_id": str(order.get("id") or ""),
            "symbol": str(order.get("symbol") or ""),
            "name": str(order.get("name") or ""),
            "qty": _safe_int(order.get("qty")),
            "status": str(order.get("status") or ""),
        }
        for order in unverified_orders
        if str(order.get("side") or "").lower() == "buy"
    ]
    submitted_without_order_no = [
        order
        for order in unverified_orders
        if str(order.get("status") or "").lower() in {"submitted_without_order_no", "submit_uncertain"}
        or not str(order.get("kis_order_no") or "").strip()
    ]
    completed_orders = [
        order
        for order in order_dicts
        if str(order.get("status") or "").lower() in _POSITION_FILLED_STATUSES
        and _safe_int(order.get("qty")) > 0
    ]
    incomplete_fill_orders = []
    for order in completed_orders:
        order_id = str(order.get("id") or "")
        fill_data = fills_by_order.get(order_id, {})
        fill_qty = _safe_float(fill_data.get("fill_qty"))
        order_qty = _safe_float(order.get("qty"))
        if _safe_int(fill_data.get("fill_count")) <= 0:
            incomplete_fill_orders.append(
                {
                    "order_id": order_id,
                    "symbol": str(order.get("symbol") or ""),
                    "side": str(order.get("side") or ""),
                    "status": str(order.get("status") or ""),
                    "order_qty": order_qty,
                    "fill_qty": 0.0,
                    "reason": "missing_fill",
                }
            )
        elif abs(fill_qty - order_qty) > 0.000001:
            incomplete_fill_orders.append(
                {
                    "order_id": order_id,
                    "symbol": str(order.get("symbol") or ""),
                    "side": str(order.get("side") or ""),
                    "status": str(order.get("status") or ""),
                    "order_qty": order_qty,
                    "fill_qty": fill_qty,
                    "reason": "fill_qty_mismatch",
                }
            )

    order_summaries = load_order_net_positions(trade_date)
    net_negative_positions = [
        {
            "symbol": str(item.get("symbol") or ""),
            "name": str(item.get("name") or ""),
            "buy_qty": _safe_int(item.get("buy_qty")),
            "sell_qty": _safe_int(item.get("sell_qty")),
            "net_qty": _safe_int(item.get("net_qty")),
            "buy_count": _safe_int(item.get("buy_count")),
            "sell_count": _safe_int(item.get("sell_count")),
        }
        for item in order_summaries
        if _safe_int(item.get("net_qty")) < 0
    ]
    duplicate_sell_orders = [
        {
            "symbol": str(item.get("symbol") or ""),
            "name": str(item.get("name") or ""),
            "sell_count": _safe_int(item.get("sell_count")),
            "sell_qty": _safe_int(item.get("sell_qty")),
            "buy_qty": _safe_int(item.get("buy_qty")),
        }
        for item in order_summaries
        if _safe_int(item.get("sell_count")) > 1
    ]
    sell_qty_exceeds_buy_qty = [
        {
            "symbol": str(item.get("symbol") or ""),
            "name": str(item.get("name") or ""),
            "buy_qty": _safe_int(item.get("buy_qty")),
            "sell_qty": _safe_int(item.get("sell_qty")),
            "excess_qty": _safe_int(item.get("sell_qty")) - _safe_int(item.get("buy_qty")),
        }
        for item in order_summaries
        if _safe_int(item.get("sell_qty")) > _safe_int(item.get("buy_qty"))
    ]
    legacy_residuals = detect_legacy_residual_positions(trade_date)

    warnings: list[str] = []
    if unverified_orders:
        warnings.append("체결/손익 검증 미완료: submitted 주문에 대응하는 fills 기록이 없습니다.")
    if pending_buy_orders:
        symbols = ", ".join(
            f"{item['symbol']}({item['qty']})" for item in pending_buy_orders[:10]
        )
        warnings.append(f"submitted 매수는 체결 미검증 상태라 자동청산 대상에서 제외됩니다: {symbols}")
    if incomplete_fill_orders:
        warnings.append("오늘 filled/partial_fill 주문 중 order_id 기준 fills 누락 또는 수량 불일치가 있습니다.")
    if submitted_without_order_no:
        warnings.append("주문번호 없는 매도/매수 제출 기록이 있어 KIS 주문 상태 대조가 필요합니다.")
    if net_negative_positions:
        symbols = ", ".join(
            f"{item['symbol']}(buy {item['buy_qty']} / sell {item['sell_qty']})"
            for item in net_negative_positions[:10]
        )
        warnings.append(f"순매도 음수 포지션 이상 감지: {symbols}")
    if duplicate_sell_orders:
        symbols = ", ".join(
            f"{item['symbol']}(sell_count {item['sell_count']}, sell_qty {item['sell_qty']})"
            for item in duplicate_sell_orders[:10]
        )
        warnings.append(f"중복 매도 주문 이상 감지: {symbols}")
    if sell_qty_exceeds_buy_qty:
        symbols = ", ".join(
            f"{item['symbol']}(buy {item['buy_qty']} / sell {item['sell_qty']})"
            for item in sell_qty_exceeds_buy_qty[:10]
        )
        warnings.append(f"매도 수량이 매수 수량을 초과했습니다: {symbols}")
    if legacy_residuals:
        warnings.append("청산 대상 외 전일 전략 잔여 포지션이 있습니다.")

    if incomplete_fill_orders:
        pnl_status = "unverified"
        pnl_source = "fills_incomplete"
    elif unverified_orders:
        pnl_status = "unverified"
        pnl_source = "incomplete_orders"
    elif completed_orders:
        pnl_status = "verified"
        pnl_source = "fills"
    elif order_dicts:
        pnl_status = "unverified"
        pnl_source = "orders_without_fills"
        warnings.append("주문 기록은 있으나 체결 테이블이 비어 있어 손익을 확정할 수 없습니다.")
    else:
        pnl_status = "no_orders"
        pnl_source = "none"

    return {
        "pnl_status": pnl_status,
        "pnl_source": pnl_source,
        "warnings": warnings,
        "submitted_only_orders": len(unverified_orders),
        "pending_buy_orders": pending_buy_orders,
        "submitted_without_order_no": len(submitted_without_order_no),
        "incomplete_fill_orders": incomplete_fill_orders,
        "net_negative_positions": net_negative_positions,
        "duplicate_sell_orders": duplicate_sell_orders,
        "sell_qty_exceeds_buy_qty": sell_qty_exceeds_buy_qty,
        "legacy_residual_positions": legacy_residuals,
    }


def json_compact(value: Any) -> str:
    """Serialize integrity payloads for DB text columns.

    Args:
        value: JSON-serializable payload.
    """
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
