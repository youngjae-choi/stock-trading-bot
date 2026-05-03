"""S7 order execution service for converting trading signals into KIS orders."""

from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection
from ..kis.domestic.service import get_balance, order_cash
from .rulepack_store import get_active_rulepack_for_date

logger = logging.getLogger("OrderExecutor")

POSITION_SIZE_PCT_DEFAULT = 10.0
MAX_POSITIONS_DEFAULT = 5


def _now_kst() -> datetime:
    """Return the current Asia/Seoul datetime."""
    return datetime.now(ZoneInfo("Asia/Seoul"))


def _today_kst() -> str:
    """Return today's Asia/Seoul date as YYYY-MM-DD."""
    return _now_kst().strftime("%Y-%m-%d")


def _to_float(value: Any, default: float = 0.0) -> float:
    """Convert KIS numeric strings to float while tolerating blanks and commas.

    Args:
        value: Raw numeric value from KIS or local DB.
        default: Fallback value when conversion fails.
    """
    try:
        return float(str(value).replace(",", "").strip() or default)
    except (TypeError, ValueError):
        return default


def _as_list(value: Any) -> list[dict[str, Any]]:
    """Normalize KIS output fields into a list of dictionaries.

    Args:
        value: Raw KIS response field that can be a list, dict, or empty value.
    """
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _machine_rules(rulepack: dict[str, Any] | None) -> dict[str, Any]:
    """Extract the machine_rules object from a RulePack-like dictionary.

    Args:
        rulepack: Full RulePack row or a machine_rules dictionary.
    """
    if not isinstance(rulepack, dict):
        return {}
    machine_rules = rulepack.get("machine_rules")
    if isinstance(machine_rules, dict):
        return machine_rules
    return rulepack


def _risk_limits(rulepack: dict[str, Any] | None) -> dict[str, Any]:
    """Extract risk limits from either the current or legacy RulePack shape.

    Args:
        rulepack: Full RulePack row or a machine_rules dictionary.
    """
    machine_rules = _machine_rules(rulepack)
    risk = machine_rules.get("risk_limits")
    return risk if isinstance(risk, dict) else {}


def _ensure_orders_table() -> None:
    """Create the trading_orders table and indexes when they do not exist."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trading_orders (
                id              TEXT PRIMARY KEY,
                trade_date      TEXT NOT NULL,
                signal_id       TEXT NOT NULL DEFAULT '',
                symbol          TEXT NOT NULL,
                name            TEXT NOT NULL DEFAULT '',
                side            TEXT NOT NULL,
                order_type      TEXT NOT NULL DEFAULT 'limit',
                qty             INTEGER NOT NULL DEFAULT 0,
                price           REAL NOT NULL DEFAULT 0.0,
                kis_order_no    TEXT NOT NULL DEFAULT '',
                status          TEXT NOT NULL DEFAULT 'submitted',
                reason          TEXT NOT NULL DEFAULT '',
                created_at      TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_trading_orders_trade_date ON trading_orders(trade_date)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trading_orders_symbol ON trading_orders(symbol)")


def get_today_orders(trade_date: str) -> list[dict[str, Any]]:
    """Return orders created for the given trade date.

    Args:
        trade_date: YYYY-MM-DD trade date.
    """
    _ensure_orders_table()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM trading_orders WHERE trade_date = ? ORDER BY created_at DESC",
            (trade_date,),
        ).fetchall()
    return [dict(row) for row in rows]


class OrderExecutor:
    """S7: pending 신호를 주문으로 변환하고 KIS에 발행한다."""

    async def execute_signal(self, signal: dict[str, Any]) -> dict[str, Any]:
        """Execute one pending BUY signal through KIS and persist the order.

        Args:
            signal: Signal dictionary containing id, symbol, name, and trigger_price.
        """
        _ensure_orders_table()
        signal_id = str(signal.get("id") or "")
        symbol = str(signal.get("symbol") or "").strip()
        name = str(signal.get("name") or "")
        price = _to_float(signal.get("trigger_price"))
        today = _today_kst()
        logger.info("START: [S7] execute_signal signal_id=%s symbol=%s", signal_id, symbol)

        if not symbol or price <= 0:
            reason = "invalid_signal"
            self._save_order(
                trade_date=today,
                signal_id=signal_id,
                symbol=symbol,
                name=name,
                side="buy",
                order_type="limit",
                qty=0,
                price=price,
                kis_order_no="",
                status="failed",
                reason=reason,
            )
            self._update_signal_status(signal_id, "failed")
            logger.warning("WARN: [S7] invalid signal signal_id=%s symbol=%s price=%s", signal_id, symbol, price)
            return {"ok": False, "reason": reason, "symbol": symbol}

        rulepack = get_active_rulepack_for_date(today) or {}
        risk = _risk_limits(rulepack)
        current_position_count = self._current_position_count()
        allowed, reason = self._check_risk_limits(rulepack, current_position_count)
        if not allowed:
            self._save_order(
                trade_date=today,
                signal_id=signal_id,
                symbol=symbol,
                name=name,
                side="buy",
                order_type="limit",
                qty=0,
                price=price,
                kis_order_no="",
                status="failed",
                reason=reason,
            )
            self._update_signal_status(signal_id, "failed")
            logger.warning("WARN: [S7] risk limit blocked symbol=%s reason=%s", symbol, reason)
            return {"ok": False, "reason": reason, "symbol": symbol}

        try:
            balance = await get_balance()
            deposit = self._extract_deposit(balance)
            position_size_pct = self._position_size_pct(risk)
            qty = self._calc_qty(deposit, position_size_pct, price)
            if qty <= 0:
                raise ValueError("calculated quantity is zero")

            response = await order_cash(side="buy", symbol=symbol, qty=qty, price=self._price_text(price), ord_dvsn="00")
            kis_order_no = self._extract_order_no(response)
            order_id = self._save_order(
                trade_date=today,
                signal_id=signal_id,
                symbol=symbol,
                name=name,
                side="buy",
                order_type="limit",
                qty=qty,
                price=price,
                kis_order_no=kis_order_no,
                status="submitted",
                reason="",
            )
            self._update_signal_status(signal_id, "executed")

            from .position_manager import position_manager

            position_manager.add_position(symbol=symbol, name=name, qty=qty, entry_price=price, rulepack=rulepack)
            logger.info("SUCCESS: [S7] buy order submitted order_id=%s symbol=%s qty=%d", order_id, symbol, qty)
            return {"ok": True, "order_id": order_id, "symbol": symbol, "qty": qty, "kis_order_no": kis_order_no}
        except Exception as exc:
            order_id = self._save_order(
                trade_date=today,
                signal_id=signal_id,
                symbol=symbol,
                name=name,
                side="buy",
                order_type="limit",
                qty=0,
                price=price,
                kis_order_no="",
                status="failed",
                reason=str(exc),
            )
            self._update_signal_status(signal_id, "failed")
            logger.error("FAIL: [S7] buy order failed order_id=%s symbol=%s reason=%s", order_id, symbol, exc)
            return {"ok": False, "order_id": order_id, "symbol": symbol, "reason": str(exc)}

    async def execute_sell(self, symbol: str, qty: int, price: float = 0, reason: str = "manual") -> dict[str, Any]:
        """Submit a SELL order for stop-loss, take-profit, manual, or EOD liquidation.

        Args:
            symbol: Stock symbol to sell.
            qty: Quantity to sell.
            price: Limit price. A value of 0 submits a market order.
            reason: Exit reason saved in trading_orders.reason.
        """
        _ensure_orders_table()
        safe_symbol = str(symbol or "").strip()
        safe_qty = int(qty or 0)
        safe_price = _to_float(price)
        order_type = "market" if safe_price <= 0 else "limit"
        ord_dvsn = "01" if order_type == "market" else "00"
        today = _today_kst()
        logger.info("START: [S8/S9] execute_sell symbol=%s qty=%d reason=%s", safe_symbol, safe_qty, reason)

        if not safe_symbol or safe_qty <= 0:
            fail_reason = "invalid_sell_request"
            order_id = self._save_order(
                trade_date=today,
                signal_id="",
                symbol=safe_symbol,
                name="",
                side="sell",
                order_type=order_type,
                qty=safe_qty,
                price=safe_price,
                kis_order_no="",
                status="failed",
                reason=fail_reason,
            )
            logger.warning("WARN: [S8/S9] invalid sell request order_id=%s symbol=%s qty=%d", order_id, safe_symbol, safe_qty)
            return {"ok": False, "order_id": order_id, "symbol": safe_symbol, "reason": fail_reason}

        try:
            response = await order_cash(
                side="sell",
                symbol=safe_symbol,
                qty=safe_qty,
                price=self._price_text(safe_price) if order_type == "limit" else "0",
                ord_dvsn=ord_dvsn,
            )
            kis_order_no = self._extract_order_no(response)
            order_id = self._save_order(
                trade_date=today,
                signal_id="",
                symbol=safe_symbol,
                name="",
                side="sell",
                order_type=order_type,
                qty=safe_qty,
                price=safe_price,
                kis_order_no=kis_order_no,
                status="submitted",
                reason=reason,
            )
            from .position_manager import position_manager

            position_manager.remove_position(safe_symbol)
            logger.info("SUCCESS: [S8/S9] sell order submitted order_id=%s symbol=%s qty=%d", order_id, safe_symbol, safe_qty)
            return {"ok": True, "order_id": order_id, "symbol": safe_symbol, "qty": safe_qty, "kis_order_no": kis_order_no}
        except Exception as exc:
            order_id = self._save_order(
                trade_date=today,
                signal_id="",
                symbol=safe_symbol,
                name="",
                side="sell",
                order_type=order_type,
                qty=safe_qty,
                price=safe_price,
                kis_order_no="",
                status="failed",
                reason=str(exc),
            )
            logger.error("FAIL: [S8/S9] sell order failed order_id=%s symbol=%s reason=%s", order_id, safe_symbol, exc)
            return {"ok": False, "order_id": order_id, "symbol": safe_symbol, "reason": str(exc)}

    def _check_risk_limits(self, rulepack: dict[str, Any], current_position_count: int) -> tuple[bool, str]:
        """Check max position count from RulePack risk limits.

        Args:
            rulepack: Active RulePack row or machine_rules dictionary.
            current_position_count: Current in-memory position count.
        """
        risk = _risk_limits(rulepack)
        max_positions = int(_to_float(risk.get("max_positions"), float(MAX_POSITIONS_DEFAULT)))
        if max_positions > 0 and current_position_count >= max_positions:
            return False, "max_positions_exceeded"
        return True, ""

    def _calc_qty(self, deposit: float, position_size_pct: float, price: float) -> int:
        """Calculate order quantity as floor(deposit * pct / 100 / price), minimum 1.

        Args:
            deposit: Available cash amount in KRW.
            position_size_pct: Percent of deposit to allocate.
            price: Intended order price.
        """
        if deposit <= 0 or position_size_pct <= 0 or price <= 0:
            return 0
        return max(1, math.floor(deposit * position_size_pct / 100 / price))

    def _current_position_count(self) -> int:
        """Return current in-memory position count while avoiding import-time cycles."""
        try:
            from .position_manager import position_manager

            return len(position_manager.get_positions())
        except Exception as exc:
            logger.warning("WARN: [S7] current position count unavailable reason=%s", exc)
            return 0

    def _extract_deposit(self, data: dict[str, Any]) -> float:
        """Extract available cash from a KIS balance response.

        Args:
            data: Raw KIS get_balance() response.
        """
        summary_rows = _as_list(data.get("output2"))
        summary = summary_rows[0] if summary_rows else {}
        for key in ("ord_psbl_cash", "dnca_tot_amt", "nass_amt", "tot_evlu_amt"):
            value = _to_float(summary.get(key))
            if value > 0:
                return value
        return 0.0

    def _position_size_pct(self, risk: dict[str, Any]) -> float:
        """Return position size percent from current or legacy RulePack keys.

        Args:
            risk: RulePack risk_limits dictionary.
        """
        if "position_size_pct" in risk:
            return _to_float(risk.get("position_size_pct"), POSITION_SIZE_PCT_DEFAULT)
        legacy_rate = _to_float(risk.get("max_position_size_rate"), 0.0)
        if 0 < legacy_rate <= 1:
            return legacy_rate * 100
        if legacy_rate > 1:
            return legacy_rate
        return POSITION_SIZE_PCT_DEFAULT

    def _extract_order_no(self, response: dict[str, Any]) -> str:
        """Extract KIS order number from common response shapes.

        Args:
            response: Raw KIS order_cash() response.
        """
        output = response.get("output")
        if isinstance(output, dict):
            for key in ("ODNO", "odno", "ORD_NO", "ord_no"):
                if output.get(key):
                    return str(output[key])
        for key in ("ODNO", "odno", "ORD_NO", "ord_no"):
            if response.get(key):
                return str(response[key])
        return ""

    def _price_text(self, price: float) -> str:
        """Format a KIS order price string without leaking float decimals.

        Args:
            price: Numeric price to send to KIS.
        """
        return str(int(price)) if float(price).is_integer() else str(price)

    def _save_order(
        self,
        *,
        trade_date: str,
        signal_id: str,
        symbol: str,
        name: str,
        side: str,
        order_type: str,
        qty: int,
        price: float,
        kis_order_no: str,
        status: str,
        reason: str,
    ) -> str:
        """Persist one trading_orders row and return its local order id.

        Args:
            trade_date: YYYY-MM-DD trade date.
            signal_id: Source trading_signals.id, or empty for sell orders.
            symbol: Stock symbol.
            name: Stock display name.
            side: buy or sell.
            order_type: limit or market.
            qty: Submitted quantity.
            price: Limit price or 0 for market.
            kis_order_no: Broker order number returned by KIS.
            status: submitted, failed, filled, or cancelled.
            reason: Exit or failure reason.
        """
        order_id = str(uuid.uuid4())
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO trading_orders
                    (id, trade_date, signal_id, symbol, name, side, order_type, qty,
                     price, kis_order_no, status, reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    trade_date,
                    signal_id,
                    symbol,
                    name,
                    side,
                    order_type,
                    int(qty),
                    float(price),
                    kis_order_no,
                    status,
                    reason,
                    _now_kst().isoformat(),
                ),
            )
        return order_id

    def _update_signal_status(self, signal_id: str, status: str) -> None:
        """Update trading_signals.status when a source signal id is available.

        Args:
            signal_id: trading_signals.id to update.
            status: New signal status.
        """
        if not signal_id:
            return
        try:
            with get_connection() as conn:
                conn.execute("UPDATE trading_signals SET status = ? WHERE id = ?", (status, signal_id))
        except Exception as exc:
            logger.warning("WARN: [S7] signal status update failed signal_id=%s reason=%s", signal_id, exc)


order_executor = OrderExecutor()
