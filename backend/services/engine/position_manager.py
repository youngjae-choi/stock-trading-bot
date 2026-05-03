"""S8 realtime position manager for stop-loss, take-profit, and time exits."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..settings_store import get_setting
from ..kis.realtime_ws import realtime_ws_manager

logger = logging.getLogger("PositionManager")

STOP_LOSS_PCT_DEFAULT = 1.5
TAKE_PROFIT_PCT_DEFAULT = 3.0
TRAILING_TRIGGER_PCT = 2.0
TRAILING_SLIP_PCT = 1.0
TIME_STOP_MINUTES = 30
TIME_STOP_MIN_PROFIT_PCT = 0.5


def _now_kst() -> datetime:
    """Return the current Asia/Seoul datetime."""
    return datetime.now(ZoneInfo("Asia/Seoul"))


def _to_float(value: Any, default: float = 0.0) -> float:
    """Convert numeric-like values into float with a safe fallback.

    Args:
        value: Raw numeric value.
        default: Fallback value when conversion fails.
    """
    try:
        return float(str(value).replace(",", "").strip() or default)
    except (TypeError, ValueError):
        return default


def _machine_rules(rulepack: dict[str, Any] | None) -> dict[str, Any]:
    """Extract machine_rules from a full RulePack row or return the input dictionary.

    Args:
        rulepack: Full RulePack row or machine_rules dictionary.
    """
    if not isinstance(rulepack, dict):
        return {}
    machine_rules = rulepack.get("machine_rules")
    return machine_rules if isinstance(machine_rules, dict) else rulepack


def _risk_limits(rulepack: dict[str, Any] | None) -> dict[str, Any]:
    """Extract risk limits from current or legacy RulePack shapes.

    Args:
        rulepack: Full RulePack row or machine_rules dictionary.
    """
    risk = _machine_rules(rulepack).get("risk_limits")
    return risk if isinstance(risk, dict) else {}


def _exit_rules(rulepack: dict[str, Any] | None) -> dict[str, Any]:
    """Extract exit rules from current or legacy RulePack shapes.

    Args:
        rulepack: Full RulePack row or machine_rules dictionary.
    """
    exit_rules = _machine_rules(rulepack).get("exit_rules")
    return exit_rules if isinstance(exit_rules, dict) else {}


def _rate_to_pct(value: Any, default_pct: float, *, negative_is_loss: bool = False) -> float:
    """Normalize RulePack percent/rate values into positive percentage points.

    Args:
        value: RulePack rate or percent value.
        default_pct: Fallback percentage points.
        negative_is_loss: Whether negative values represent loss rates.
    """
    parsed = _to_float(value, 0.0)
    if parsed == 0:
        return default_pct
    if abs(parsed) <= 1:
        parsed *= 100
    if negative_is_loss:
        return abs(parsed)
    return parsed if parsed > 0 else default_pct


def _get_exit_param(key: str, rulepack_value: Any, default_rate: float) -> float:
    """Return a decimal exit rate from settings override, RulePack, or default.

    Args:
        key: system_settings override key.
        rulepack_value: RulePack value to use when no override exists.
        default_rate: Fallback decimal rate.
    """
    override = get_setting(key, "")
    if override not in ("", None):
        try:
            return float(override)
        except (TypeError, ValueError):
            logger.warning("WARN: [S8] invalid exit override ignored key=%s value=%s", key, override)
    return _to_float(rulepack_value, default_rate) if rulepack_value is not None else default_rate


class PositionManager:
    """S8: 보유 포지션의 손절/익절/트레일링/시간손절을 실시간 WS tick으로 감시한다."""

    def __init__(self):
        """Initialize in-memory positions and closing guards."""
        self._positions: dict[str, dict[str, Any]] = {}
        self._closing: set[str] = set()
        self._active = False

    def add_position(self, symbol: str, name: str, qty: int, entry_price: float, rulepack: dict[str, Any]) -> None:
        """Register a newly submitted position and calculate exit thresholds.

        Args:
            symbol: Stock symbol.
            name: Stock display name.
            qty: Position quantity.
            entry_price: Entry price used for threshold calculations.
            rulepack: Active RulePack row or machine_rules dictionary.
        """
        safe_symbol = str(symbol or "").strip()
        safe_qty = int(qty or 0)
        safe_entry = _to_float(entry_price)
        if not safe_symbol or safe_qty <= 0 or safe_entry <= 0:
            logger.warning("WARN: [S8] invalid position ignored symbol=%s qty=%s entry=%s", symbol, qty, entry_price)
            return

        risk = _risk_limits(rulepack)
        exit_rules = _exit_rules(rulepack)
        stop_loss_rate = _get_exit_param(
            "override_stop_loss_rate",
            exit_rules.get("stop_loss_rate", risk.get("stop_loss_pct", risk.get("stop_loss_rate"))),
            -STOP_LOSS_PCT_DEFAULT / 100,
        )
        take_profit_rate = _get_exit_param(
            "override_take_profit_rate",
            exit_rules.get("take_profit_rate", risk.get("take_profit_pct", risk.get("take_profit_rate"))),
            TAKE_PROFIT_PCT_DEFAULT / 100,
        )
        trailing_activate_rate = _get_exit_param(
            "override_trailing_activate_rate",
            exit_rules.get("trailing_activate_profit_rate"),
            TRAILING_TRIGGER_PCT / 100,
        )
        trailing_stop_rate = _get_exit_param(
            "override_trailing_stop_rate",
            exit_rules.get("trailing_stop_rate"),
            TRAILING_SLIP_PCT / 100,
        )
        stop_loss_pct = _rate_to_pct(stop_loss_rate, STOP_LOSS_PCT_DEFAULT, negative_is_loss=True)
        take_profit_pct = _rate_to_pct(take_profit_rate, TAKE_PROFIT_PCT_DEFAULT)
        trailing_activate_pct = _rate_to_pct(trailing_activate_rate, TRAILING_TRIGGER_PCT)
        trailing_stop_pct = _rate_to_pct(trailing_stop_rate, TRAILING_SLIP_PCT)
        self._positions[safe_symbol] = {
            "symbol": safe_symbol,
            "name": str(name or ""),
            "qty": safe_qty,
            "entry_price": safe_entry,
            "entry_time": _now_kst().isoformat(),
            "stop_loss_price": safe_entry * (1 - stop_loss_pct / 100),
            "take_profit_price": safe_entry * (1 + take_profit_pct / 100),
            "trailing_active": False,
            "trailing_high": safe_entry,
            "trailing_activate_pct": trailing_activate_pct,
            "trailing_stop_pct": trailing_stop_pct,
        }
        self._closing.discard(safe_symbol)
        logger.info("SUCCESS: [S8] position added symbol=%s qty=%d entry=%.2f", safe_symbol, safe_qty, safe_entry)

    def remove_position(self, symbol: str) -> None:
        """Remove a position after liquidation order submission.

        Args:
            symbol: Stock symbol to remove.
        """
        safe_symbol = str(symbol or "").strip()
        existed = safe_symbol in self._positions
        self._positions.pop(safe_symbol, None)
        self._closing.discard(safe_symbol)
        if existed:
            logger.info("SUCCESS: [S8] position removed symbol=%s", safe_symbol)

    def get_positions(self) -> list[dict[str, Any]]:
        """Return current in-memory positions."""
        return [dict(position) for position in self._positions.values()]

    async def on_tick(self, tick: dict[str, Any]) -> None:
        """Evaluate one realtime tick against active exit conditions.

        Args:
            tick: Parsed realtime tick from RealtimeWSManager.
        """
        symbol = str(tick.get("symbol") or "").strip()
        position = self._positions.get(symbol)
        if not position or symbol in self._closing:
            return

        price = _to_float(tick.get("price"))
        if price <= 0:
            logger.warning("WARN: [S8] tick price parse failed symbol=%s price=%s", symbol, tick.get("price"))
            return

        reason = self._exit_reason(position, price)
        if not reason:
            return

        self._closing.add(symbol)
        logger.info("START: [S8] exit triggered symbol=%s reason=%s price=%.2f", symbol, reason, price)
        try:
            from .order_executor import order_executor

            await order_executor.execute_sell(symbol=symbol, qty=int(position["qty"]), price=0, reason=reason)
            logger.info("SUCCESS: [S8] exit order requested symbol=%s reason=%s", symbol, reason)
        except Exception as exc:
            self._closing.discard(symbol)
            logger.error("FAIL: [S8] exit order failed symbol=%s reason=%s error=%s", symbol, reason, exc)

    def activate(self) -> None:
        """Register the realtime websocket tick callback for position monitoring."""
        if not self._active:
            realtime_ws_manager.register_tick_callback(self.on_tick)
            self._active = True
            logger.info("SUCCESS: [S8] PositionManager activated")

    def deactivate(self) -> None:
        """Unregister the realtime websocket tick callback for position monitoring."""
        if self._active:
            realtime_ws_manager.unregister_tick_callback(self.on_tick)
            self._active = False
            logger.info("SUCCESS: [S8] PositionManager deactivated")

    def _exit_reason(self, position: dict[str, Any], price: float) -> str:
        """Return the first matching exit reason for the current price.

        Args:
            position: In-memory position dictionary.
            price: Current tick price.
        """
        if price <= _to_float(position.get("stop_loss_price")):
            return "stop_loss"
        if price >= _to_float(position.get("take_profit_price")):
            return "take_profit"

        entry_price = _to_float(position.get("entry_price"))
        trailing_high = max(_to_float(position.get("trailing_high"), entry_price), price)
        trailing_activate_pct = _to_float(position.get("trailing_activate_pct"), TRAILING_TRIGGER_PCT)
        trailing_stop_pct = _to_float(position.get("trailing_stop_pct"), TRAILING_SLIP_PCT)
        position["trailing_high"] = trailing_high
        if not position.get("trailing_active") and price >= entry_price * (1 + trailing_activate_pct / 100):
            position["trailing_active"] = True
            logger.info("INFO: [S8] trailing activated symbol=%s high=%.2f", position.get("symbol"), trailing_high)
        if position.get("trailing_active") and price <= trailing_high * (1 - trailing_stop_pct / 100):
            return "trailing"

        entry_time = self._parse_entry_time(position.get("entry_time"))
        pnl_pct = ((price - entry_price) / entry_price) * 100 if entry_price > 0 else 0.0
        if entry_time and _now_kst() - entry_time >= timedelta(minutes=TIME_STOP_MINUTES) and pnl_pct < TIME_STOP_MIN_PROFIT_PCT:
            return "time_stop"
        return ""

    def _parse_entry_time(self, value: Any) -> datetime | None:
        """Parse a stored entry_time ISO string.

        Args:
            value: entry_time value saved in add_position().
        """
        try:
            parsed = datetime.fromisoformat(str(value))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=ZoneInfo("Asia/Seoul"))
            return parsed
        except (TypeError, ValueError):
            return None


position_manager = PositionManager()
