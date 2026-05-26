"""S8 Position Manager — 초기손절 + 트레일링스탑 + 강제청산.

고정 익절(take_profit)은 사용하지 않는다.
손절선은 절대 하향되지 않는다 (stop_price_can_only_increase = True).

청산 우선순위:
  1. INITIAL_STOP_LOSS  — 진입 후 초기 손절선 이탈
  2. TRAILING_STOP      — 트레일링 스탑 이탈
  3. TIME_EXIT          — 최대 보유 시간 초과 (손익분기 미달 시)
  4. DAILY_FORCE_EXIT   — 장마감 강제청산 (15:20 이후)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection
from ..kis.realtime_ws import realtime_ws_manager

logger = logging.getLogger("PositionManager")

_DEFAULT_RULE = {
    "initial_stop_loss": -0.03,
    "trailing_activate_profit": 0.025,
    "trailing_stop_rate": 0.03,
    "max_position_rate": 0.12,
    "max_holding_minutes": 180,
    "force_exit_time": "15:20:00",
    "new_entry_cutoff_time": "15:10:00",
    "profile_assigned": "MID_VOL",
}

EXIT_REASONS = ("INITIAL_STOP_LOSS", "TRAILING_STOP", "TIME_EXIT", "DAILY_FORCE_EXIT", "EMERGENCY_HALT", "MANUAL_EXIT")


def _now_kst() -> datetime:
    return datetime.now(ZoneInfo("Asia/Seoul"))


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).replace(",", "").strip() or default)
    except (TypeError, ValueError):
        return default


def _upsert_stop_state(position_id: str, data: dict[str, Any]) -> None:
    now = _now_kst().isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO position_stop_states
                (position_id, symbol_code, entry_price, highest_price_since_entry,
                 initial_stop_price, trailing_stop_price, active_stop_price,
                 trailing_active, profile_assigned, last_updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                position_id,
                data["symbol_code"],
                data["entry_price"],
                data["highest_price_since_entry"],
                data["initial_stop_price"],
                data["trailing_stop_price"],
                data["active_stop_price"],
                1 if data["trailing_active"] else 0,
                data["profile_assigned"],
                now,
            ),
        )


class PositionManager:
    """S8: 보유 포지션의 손절/트레일링/강제청산을 실시간 WS tick으로 감시한다."""

    def __init__(self):
        self._positions: dict[str, dict[str, Any]] = {}
        self._closing: set[str] = set()
        self._active = False

    def add_position(
        self,
        symbol: str,
        name: str,
        qty: int,
        entry_price: float,
        final_rule: dict[str, Any],
    ) -> None:
        """포지션 등록. final_rule은 rule_cache.get_rule() 결과를 넘긴다."""
        safe_symbol = str(symbol or "").strip()
        safe_qty = int(qty or 0)
        safe_entry = _to_float(entry_price)
        if not safe_symbol or safe_qty <= 0 or safe_entry <= 0:
            logger.warning("WARN: [S8] invalid position symbol=%s qty=%s entry=%s", symbol, qty, entry_price)
            return

        rule = {**_DEFAULT_RULE, **(final_rule or {})}
        initial_stop_loss = _to_float(rule.get("initial_stop_loss"), -0.03)
        if initial_stop_loss > 0:
            initial_stop_loss = -initial_stop_loss  # 양수로 들어온 경우 보정
        trailing_activate = _to_float(rule.get("trailing_activate_profit"), 0.025)
        trailing_rate = _to_float(rule.get("trailing_stop_rate"), 0.03)
        max_minutes = int(rule.get("max_holding_minutes") or 180)
        profile = str(rule.get("profile_assigned") or "MID_VOL")

        initial_stop_price = safe_entry * (1 + initial_stop_loss)
        position_id = f"{safe_symbol}-{_now_kst().strftime('%H%M%S%f')}"

        self._positions[safe_symbol] = {
            "position_id": position_id,
            "symbol": safe_symbol,
            "name": str(name or ""),
            "qty": safe_qty,
            "entry_price": safe_entry,
            "entry_time": _now_kst().isoformat(),
            "profile_assigned": profile,
            # 손절선 (절대 하향 불가)
            "initial_stop_price": initial_stop_price,
            "active_stop_price": initial_stop_price,
            # 트레일링
            "highest_price_since_entry": safe_entry,
            "trailing_active": False,
            "trailing_stop_price": initial_stop_price,
            "trailing_activate_profit": trailing_activate,
            "trailing_stop_rate": trailing_rate,
            # 시간 기반
            "max_holding_minutes": max_minutes,
            "force_exit_time": str(rule.get("force_exit_time") or "15:20:00"),
        }
        self._closing.discard(safe_symbol)

        _upsert_stop_state(position_id, {
            "symbol_code": safe_symbol,
            "entry_price": safe_entry,
            "highest_price_since_entry": safe_entry,
            "initial_stop_price": initial_stop_price,
            "trailing_stop_price": initial_stop_price,
            "active_stop_price": initial_stop_price,
            "trailing_active": False,
            "profile_assigned": profile,
        })
        logger.info("SUCCESS: [S8] position added symbol=%s profile=%s entry=%.2f stop=%.2f",
                    safe_symbol, profile, safe_entry, initial_stop_price)


    def update_position_quantity(self, symbol: str, qty: int) -> bool:
        """Update an already managed position quantity from KIS real holdings.

        Args:
            symbol: Managed symbol code.
            qty: Current account holding quantity.
        """
        safe_symbol = str(symbol or "").strip()
        safe_qty = int(qty or 0)
        position = self._positions.get(safe_symbol)
        if not position or safe_qty <= 0:
            return False
        previous_qty = int(position.get("qty") or 0)
        if previous_qty != safe_qty:
            position["qty"] = safe_qty
            logger.info("SUCCESS: [S8] position qty synced symbol=%s previous=%d current=%d", safe_symbol, previous_qty, safe_qty)
        return True

    def sync_account_position(
        self,
        *,
        symbol: str,
        name: str,
        qty: int,
        entry_price: float,
        final_rule: dict[str, Any] | None,
    ) -> bool:
        """Create or update a PositionManager entry from the KIS account SSOT.

        Args:
            symbol: KIS holding symbol.
            name: KIS product name.
            qty: Current KIS holding quantity.
            entry_price: KIS average purchase price used as the S8 entry price.
            final_rule: Active risk rule; LOW_VOL fallback is applied for imports.
        """
        safe_symbol = str(symbol or "").strip()
        safe_qty = int(qty or 0)
        safe_entry = _to_float(entry_price)
        if not safe_symbol or safe_qty <= 0 or safe_entry <= 0:
            logger.warning(
                "WARN: [S8] account sync skipped invalid holding symbol=%s qty=%s entry=%s",
                symbol,
                qty,
                entry_price,
            )
            return False

        if safe_symbol in self._positions:
            updated = self.update_position_quantity(safe_symbol, safe_qty)
            position = self._positions[safe_symbol]
            if name and not position.get("name"):
                position["name"] = str(name)
            return updated

        rule = {"profile_assigned": "LOW_VOL", **(final_rule or {})}
        if not rule.get("profile_assigned"):
            rule["profile_assigned"] = "LOW_VOL"
        self.add_position(
            symbol=safe_symbol,
            name=name,
            qty=safe_qty,
            entry_price=safe_entry,
            final_rule=rule,
        )
        logger.info(
            "SUCCESS: [S8] account holding imported symbol=%s qty=%d entry=%.2f profile=%s",
            safe_symbol,
            safe_qty,
            safe_entry,
            rule.get("profile_assigned"),
        )
        return True

    def remove_position(self, symbol: str) -> None:
        safe_symbol = str(symbol or "").strip()
        self._positions.pop(safe_symbol, None)
        self._closing.discard(safe_symbol)
        logger.info("SUCCESS: [S8] position removed symbol=%s", safe_symbol)

    def get_positions(self) -> list[dict[str, Any]]:
        return [dict(p) for p in self._positions.values()]

    async def on_tick(self, tick: dict[str, Any]) -> None:
        symbol = str(tick.get("symbol") or "").strip()
        position = self._positions.get(symbol)
        if not position or symbol in self._closing:
            return

        price = _to_float(tick.get("price"))
        if price <= 0:
            try:
                from .data_quality_guard import publish_event as _dq_publish
                _dq_publish(
                    source="position_manager",
                    event_type="price_zero_or_negative",
                    severity="DEGRADED",
                    detail={"symbol": symbol, "price": price},
                    notify_telegram=False,
                )
            except Exception:
                pass
            return

        # 트레일링 상태 업데이트
        self._update_trailing(position, price)

        reason = self._exit_reason(position, price)
        if not reason:
            return

        self._closing.add(symbol)
        logger.info("START: [S8] exit symbol=%s reason=%s price=%.2f", symbol, reason, price)
        try:
            from .order_executor import order_executor
            sell_result = await order_executor.execute_sell(symbol=symbol, qty=int(position["qty"]), price=0, reason=reason)
            logger.info("SUCCESS: [S8] exit order symbol=%s reason=%s", symbol, reason)
            if reason == "TRAILING_STOP" and isinstance(sell_result, dict) and sell_result.get("ok"):
                await self._notify_trailing_slot_opened(symbol, reason)
        except Exception as exc:
            self._closing.discard(symbol)
            logger.error("FAIL: [S8] exit order failed symbol=%s error=%s", symbol, exc)

    async def _notify_trailing_slot_opened(self, symbol: str, reason: str) -> None:
        """Re-arm S6 candidate evaluation after a trailing stop opens capacity.

        Args:
            symbol: Exited symbol.
            reason: Exit reason. This notification never places a buy order directly.
        """
        try:
            from .decision_engine import decision_engine

            await decision_engine.on_position_slot_opened(symbol, reason)
        except Exception as exc:
            logger.warning("WARN: [S8] trailing slot-open notification failed symbol=%s reason=%s", symbol, exc)

    def _update_trailing(self, position: dict[str, Any], price: float) -> None:
        """트레일링 스탑 상태 업데이트. 손절선은 절대 하향하지 않는다."""
        entry_price = _to_float(position["entry_price"])
        prev_high = _to_float(position["highest_price_since_entry"])
        new_high = max(prev_high, price)
        position["highest_price_since_entry"] = new_high

        trailing_activate = _to_float(position["trailing_activate_profit"])
        trailing_rate = _to_float(position["trailing_stop_rate"])

        was_trailing_active = bool(position["trailing_active"])

        # 트레일링 활성화 여부
        if not was_trailing_active and price >= entry_price * (1 + trailing_activate):
            position["trailing_active"] = True
            logger.info("INFO: [S8] trailing activated symbol=%s high=%.2f", position["symbol"], new_high)

        # 트레일링 손절선 계산
        new_trailing_stop = new_high * (1 - trailing_rate)
        position["trailing_stop_price"] = new_trailing_stop

        # active_stop_price는 절대 하향 불가
        prev_active = _to_float(position["active_stop_price"])
        new_active = max(prev_active, position["initial_stop_price"], new_trailing_stop if position["trailing_active"] else 0)
        position["active_stop_price"] = new_active

        trailing_state_changed = bool(position["trailing_active"]) != was_trailing_active
        active_stop_changed = new_active > prev_active
        if new_high > prev_high or trailing_state_changed or active_stop_changed:
            _upsert_stop_state(position["position_id"], {
                "symbol_code": position["symbol"],
                "entry_price": entry_price,
                "highest_price_since_entry": new_high,
                "initial_stop_price": _to_float(position["initial_stop_price"]),
                "trailing_stop_price": new_trailing_stop,
                "active_stop_price": new_active,
                "trailing_active": position["trailing_active"],
                "profile_assigned": position.get("profile_assigned", "MID_VOL"),
            })

    # 시장 톤별 강제청산 시간 (부정적 시황일수록 일찍 청산)
    _TONE_FORCE_EXIT: dict[str, str] = {
        "positive": "15:25:00",
        "neutral":  "15:20:00",
        "negative": "15:10:00",
        "mixed":    "15:15:00",
        "fallback": "15:20:00",
    }
    # 시장 톤별 TIME_EXIT pnl 임계값 (부정적 시황일수록 손익분기 기준 높임)
    _TONE_TIME_EXIT_PNL: dict[str, float] = {
        "positive": 0.0,    # 수익 중이면 계속 보유
        "neutral":  0.005,  # 0.5% 미달 시 시간 손절
        "negative": 0.01,   # 1% 미달 시 시간 손절 (더 일찍 컷)
        "mixed":    0.008,
        "fallback": 0.005,
    }

    def _get_today_tone(self) -> str:
        """오늘 시장 톤을 DB에서 조회. 실패 시 fallback 반환."""
        try:
            from zoneinfo import ZoneInfo as _ZI
            trade_date = _now_kst().strftime("%Y-%m-%d")
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT tone FROM market_tone_results WHERE trade_date = ? ORDER BY created_at DESC LIMIT 1",
                    (trade_date,),
                ).fetchone()
            if row:
                return str(row["tone"]).lower()
        except Exception:
            pass
        return "fallback"

    def _exit_reason(self, position: dict[str, Any], price: float) -> str:
        now = _now_kst()
        active_stop = _to_float(position["active_stop_price"])

        # 1. 강제청산 시간 (최우선) — 시장 톤에 따라 조정
        tone = self._get_today_tone()
        default_force_time = self._TONE_FORCE_EXIT.get(tone, "15:20:00")
        force_time_str = str(position.get("force_exit_time") or default_force_time)
        try:
            h, m, s = map(int, force_time_str.split(":"))
            force_dt = now.replace(hour=h, minute=m, second=s, microsecond=0)
            if now >= force_dt:
                return "DAILY_FORCE_EXIT"
        except Exception:
            pass

        # 2. 초기손절 / 트레일링 손절 (active_stop_price 이탈)
        if price <= active_stop:
            if position["trailing_active"]:
                return "TRAILING_STOP"
            return "INITIAL_STOP_LOSS"

        # 3. 시간 손절 (최대 보유 시간 초과 + 손익분기 미달) — pnl 임계값 톤에 따라 조정
        try:
            entry_time = datetime.fromisoformat(position["entry_time"])
            if entry_time.tzinfo is None:
                entry_time = entry_time.replace(tzinfo=ZoneInfo("Asia/Seoul"))
            max_minutes = int(position.get("max_holding_minutes") or 180)
            entry_price = _to_float(position["entry_price"])
            pnl_pct = (price - entry_price) / entry_price if entry_price > 0 else 0
            time_exit_pnl = self._TONE_TIME_EXIT_PNL.get(tone, 0.005)
            if now - entry_time >= timedelta(minutes=max_minutes) and pnl_pct < time_exit_pnl:
                return "TIME_EXIT"
        except Exception:
            pass

        return ""

    def activate(self) -> None:
        if not self._active:
            realtime_ws_manager.register_tick_callback(self.on_tick)
            self._active = True
            logger.info("SUCCESS: [S8] PositionManager activated")

    def deactivate(self) -> None:
        if self._active:
            realtime_ws_manager.unregister_tick_callback(self.on_tick)
            self._active = False
            logger.info("SUCCESS: [S8] PositionManager deactivated")


position_manager = PositionManager()
