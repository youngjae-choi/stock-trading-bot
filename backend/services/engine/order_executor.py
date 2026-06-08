"""S7 order execution service for converting trading signals into KIS orders."""

from __future__ import annotations

import asyncio
import logging
import math
import time
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..db import get_connection
from ..kis.domestic.service import get_balance, order_cash
from .order_preflight import is_new_buy_blocked_by_emergency_halt, run_preflight
from .position_integrity import find_active_sell_order, load_order_net_positions
from .position_manager import position_manager
from .rule_cache import get_rule

logger = logging.getLogger("OrderExecutor")

POSITION_SIZE_PCT_DEFAULT = 10.0


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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trading_orders_created_at ON trading_orders(created_at)")


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


def get_recent_orders(limit: int = 5) -> list[dict[str, Any]]:
    """Return the newest trading orders across trade dates.

    Args:
        limit: Maximum number of rows to return. Values are clamped to 1..100.
    """
    safe_limit = max(1, min(int(limit or 5), 100))
    _ensure_orders_table()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM trading_orders ORDER BY created_at DESC LIMIT ?",
            (safe_limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_orders_by_range(start_date: str, end_date: str, limit: int = 500) -> list[dict[str, Any]]:
    """Return orders between start_date and end_date inclusive.

    Args:
        start_date: Start trade date in YYYY-MM-DD format.
        end_date: End trade date in YYYY-MM-DD format.
        limit: Maximum number of rows to return. Values are clamped to 1..1000.
    """
    safe_limit = max(1, min(int(limit or 500), 1000))
    _ensure_orders_table()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM trading_orders WHERE trade_date >= ? AND trade_date <= ? ORDER BY created_at DESC LIMIT ?",
            (start_date, end_date, safe_limit),
        ).fetchall()
    return [dict(row) for row in rows]


class OrderExecutor:
    """S7: pending 신호를 주문으로 변환하고 KIS에 발행한다."""

    def __init__(self) -> None:
        """Initialize KIS rate-limit guards and short-lived balance cache."""
        self._semaphore = asyncio.Semaphore(1)
        self._balance_cache: dict[str, Any] = {}
        self._balance_cache_at: float = 0.0
        self._BALANCE_TTL = 30.0

    _BUY_MAX_RETRY = 3
    _BUY_RETRY_DELAYS = (2.0, 4.0, 8.0)  # 초 단위 — 지수 백오프

    async def execute_signal(self, signal: dict[str, Any]) -> dict[str, Any]:
        """Serialize BUY signal execution with up to 3 retries on transient failure.

        Args:
            signal: Signal dictionary containing id, symbol, name, and trigger_price.
        """
        async with self._semaphore:
            last_result: dict[str, Any] = {}
            for attempt in range(self._BUY_MAX_RETRY):
                result = await self._execute_signal_inner(signal)
                if result.get("ok"):
                    return result
                last_result = result
                # preflight/validation 실패는 재시도해도 의미 없음
                non_retryable = {"invalid_signal", "preflight_blocked", "emergency_halt_active", "emergency_halt_status_uncertain"}
                if result.get("reason") in non_retryable:
                    return result
                if attempt < self._BUY_MAX_RETRY - 1:
                    delay = self._BUY_RETRY_DELAYS[attempt]
                    logger.warning(
                        "WARN: [S7] BUY 재시도 %d/%d symbol=%s reason=%s delay=%.1fs",
                        attempt + 1,
                        self._BUY_MAX_RETRY,
                        signal.get("symbol"),
                        result.get("reason"),
                        delay,
                    )
                    await asyncio.sleep(delay)
            logger.error(
                "FAIL: [S7] BUY 최대 재시도(%d회) 초과 symbol=%s",
                self._BUY_MAX_RETRY,
                signal.get("symbol"),
            )
            return last_result

    async def _execute_signal_inner(self, signal: dict[str, Any]) -> dict[str, Any]:
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

        emergency_halt_blocked, emergency_halt_reason = is_new_buy_blocked_by_emergency_halt()
        if emergency_halt_blocked:
            reason = emergency_halt_reason or "emergency_halt_active"
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
                status="blocked",
                reason=reason,
            )
            self._update_signal_status(signal_id, "preflight_blocked")
            logger.warning(
                "BLOCK: [S7] emergency halt guard blocks BUY order_id=%s signal_id=%s symbol=%s reason=%s",
                order_id,
                signal_id,
                symbol,
                reason,
            )
            return {"ok": False, "order_id": order_id, "reason": reason, "symbol": symbol}

        final_rule = get_rule(symbol) or {}

        try:
            balance = await self._get_cached_balance()
            deposit = self._extract_deposit(balance)
            from .daily_capital import get_baseline, get_active_budget_rate
            from .exploration_gate import select_sizing_params
            baseline = get_baseline(today)
            from .exploration_gate import is_exploration_allowed
            from ..settings_store import get_setting as _get_setting
            if is_exploration_allowed():
                # 탐색: Profile 비중대로 + 95% 배포 한도 내 실시간 가용현금 기준
                total_eval = self._extract_total_eval(balance)
                profile_rate = self._position_size_pct(final_rule) / 100.0
                deploy_target = float(_get_setting("exploration.deploy_target_rate", 0.95) or 0.95)
                buffer = total_eval * (1.0 - deploy_target)
                deployable = max(0.0, deposit - buffer)  # deposit=ord_psbl_cash(실시간)
                qty = self._calc_profile_qty(total_eval, profile_rate, deployable, price)
                logger.info(
                    "INFO: [S7] Profile비중 사이징 symbol=%s rate=%.2f total_eval=%.0f deployable=%.0f qty=%d",
                    symbol, profile_rate, total_eval, deployable, qty,
                )
            else:
                explore_budget_rate, max_positions = select_sizing_params(final_rule)
                budget_rate = explore_budget_rate if explore_budget_rate is not None else get_active_budget_rate(today)
                qty = self._calc_budget_qty(baseline, budget_rate, max_positions, price, deposit)
                if qty <= 0:
                    qty = self._calc_qty(deposit, self._position_size_pct(final_rule), price)
                logger.info("INFO: [S7] 기존(보수) 사이징 symbol=%s qty=%d", symbol, qty)
            if qty <= 0:
                logger.info("INFO: [S7] 배포 여력 없음 — 매수 스킵 symbol=%s", symbol)
                self._update_signal_status(signal_id, "skipped_no_room")
                return {"ok": False, "reason": "no_deployable_room", "symbol": symbol}

            current_pos_count = len(position_manager.get_positions())
            preflight = run_preflight(signal, final_rule, current_positions_count=current_pos_count)
            if not preflight["ok"]:
                logger.warning(
                    "BLOCK: [S7] Pre-Flight 차단 signal_id=%s symbol=%s reason=%s",
                    signal_id,
                    symbol,
                    preflight.get("block_reason"),
                )
                with get_connection() as conn:
                    conn.execute(
                        "UPDATE trading_signals SET status = 'preflight_blocked' WHERE id = ?",
                        (signal_id,),
                    )
                return {"ok": False, "reason": "preflight_blocked", "detail": preflight.get("block_reason")}

            try:
                response = await order_cash(side="buy", symbol=symbol, qty=qty, price=self._price_text(price), ord_dvsn="00")
            finally:
                await asyncio.sleep(0.2)
            kis_order_no = self._extract_order_no(response)

            # KIS 모의투자 환경에서 rate-limit 부하 시 ODNO가 응답에서 빠지는 경우가 있다.
            # 주문 자체는 HTTP 200으로 접수됐을 가능성이 높으므로 체결내역 재조회로 주문번호를 보정한다.
            if not kis_order_no:
                logger.warning(
                    "WARN: [S7] buy response missing ODNO — fallback to inquire-daily-ccld symbol=%s",
                    symbol,
                )
                try:
                    from ..kis.domestic.service import get_daily_order_inquiry
                    date_str = today.replace("-", "")
                    ccld = await get_daily_order_inquiry(date_str, side="buy")
                    for row in (ccld.get("output1") or []):
                        if str(row.get("pdno") or "") == symbol:
                            candidate = str(row.get("odno") or "").strip()
                            if candidate:
                                kis_order_no = candidate
                                logger.info(
                                    "INFO: [S7] buy ODNO recovered from ccld symbol=%s odno=%s",
                                    symbol,
                                    kis_order_no,
                                )
                                break
                except Exception as ccld_exc:
                    logger.warning("WARN: [S7] buy ccld fallback failed symbol=%s reason=%s", symbol, ccld_exc)

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
                reason="" if kis_order_no else "submit_uncertain",
            )
            self._update_signal_status(signal_id, "executed")

            position_manager.add_position(symbol=symbol, name=name, qty=qty, entry_price=price, final_rule=final_rule)
            logger.info(
                "SUCCESS: [S7] buy order submitted order_id=%s symbol=%s qty=%d kis_order_no=%s",
                order_id, symbol, qty, kis_order_no or "(missing)",
            )
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

    async def _get_cached_balance(self) -> dict[str, Any]:
        """Return KIS balance data using a 30-second cache to reduce API pressure."""
        now = time.monotonic()
        if now - self._balance_cache_at > self._BALANCE_TTL or not self._balance_cache:
            self._balance_cache = await get_balance()
            self._balance_cache_at = now
            logger.info("SUCCESS: [S7] balance cache refreshed")
        else:
            logger.info("INFO: [S7] balance cache reused")
        return self._balance_cache

    async def execute_sell(
        self,
        symbol: str,
        qty: int,
        price: float = 0,
        reason: str = "manual",
        name: str = "",
    ) -> dict[str, Any]:
        """Submit a SELL order for stop-loss, take-profit, manual, or EOD liquidation.

        Args:
            symbol: Stock symbol to sell.
            qty: Quantity to sell.
            price: Limit price. A value of 0 submits a market order.
            reason: Exit reason saved in trading_orders.reason.
            name: Optional stock display name from KIS holdings or local state.
        """
        _ensure_orders_table()
        safe_symbol = str(symbol or "").strip()
        safe_name = str(name or "").strip()
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
                name=safe_name,
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

        duplicate_sell = find_active_sell_order(today, safe_symbol)
        if duplicate_sell:
            logger.warning(
                "WARN: [S8/S9] duplicate sell skipped symbol=%s qty=%d existing_order_id=%s existing_status=%s",
                safe_symbol,
                safe_qty,
                duplicate_sell.get("id"),
                duplicate_sell.get("status"),
            )
            return {
                "ok": False,
                "status": "skipped_duplicate",
                "symbol": safe_symbol,
                "qty": safe_qty,
                "reason": "sell_already_submitted",
                "existing_order_id": duplicate_sell.get("id"),
                "existing_status": duplicate_sell.get("status"),
            }

        summaries = load_order_net_positions(today, [safe_symbol])
        if summaries and int(summaries[0].get("buy_qty") or 0) > 0 and int(summaries[0].get("net_qty") or 0) <= 0:
            logger.warning(
                "WARN: [S8/S9] sell skipped because DB net position is closed symbol=%s buy_qty=%s sell_qty=%s net_qty=%s",
                safe_symbol,
                summaries[0].get("buy_qty"),
                summaries[0].get("sell_qty"),
                summaries[0].get("net_qty"),
            )
            return {
                "ok": False,
                "status": "skipped_duplicate",
                "symbol": safe_symbol,
                "qty": safe_qty,
                "reason": "net_position_closed",
                "buy_qty": summaries[0].get("buy_qty"),
                "sell_qty": summaries[0].get("sell_qty"),
                "net_qty": summaries[0].get("net_qty"),
            }

        try:
            try:
                response = await order_cash(
                    side="sell",
                    symbol=safe_symbol,
                    qty=safe_qty,
                    price=self._price_text(safe_price) if order_type == "limit" else "0",
                    ord_dvsn=ord_dvsn,
                )
            except Exception as first_exc:
                # 매도 실패 — 최대 2회 시장가 재시도 (총 3회 시도)
                logger.warning(
                    "WARN: [S8/S9] sell 1차 실패, 시장가 재시도 symbol=%s reason=%s",
                    safe_symbol, first_exc,
                )
                _sell_retry_delays = (2.0, 4.0)
                _sell_success = False
                for _sell_attempt, _sell_delay in enumerate(_sell_retry_delays, start=1):
                    await asyncio.sleep(_sell_delay)
                    try:
                        response = await order_cash(
                            side="sell",
                            symbol=safe_symbol,
                            qty=safe_qty,
                            price="0",
                            ord_dvsn="01",  # 시장가
                        )
                        order_type = "market"
                        safe_price = 0.0
                        logger.info(
                            "INFO: [S8/S9] sell 시장가 재시도 성공 attempt=%d symbol=%s",
                            _sell_attempt,
                            safe_symbol,
                        )
                        _sell_success = True
                        break
                    except Exception as retry_exc:
                        logger.warning(
                            "WARN: [S8/S9] sell 재시도 %d/%d 실패 symbol=%s reason=%s",
                            _sell_attempt,
                            len(_sell_retry_delays),
                            safe_symbol,
                            retry_exc,
                        )
                if not _sell_success:
                    raise first_exc
            await asyncio.sleep(0.2)
            kis_order_no = self._extract_order_no(response)

            # KIS 모의투자 환경에서 rate-limit 부하 시 output에 ODNO가 빠지는 경우가 있다.
            # 주문 자체는 HTTP 200으로 접수됐으므로, 체결내역 재조회로 주문번호를 보정한다.
            if not kis_order_no:
                logger.warning(
                    "WARN: [S8/S9] sell response missing ODNO — fallback to inquire-daily-ccld symbol=%s",
                    safe_symbol,
                )
                try:
                    from ..kis.domestic.service import get_daily_order_inquiry
                    ccld = await get_daily_order_inquiry(today, side="sell")
                    for row in (ccld.get("output1") or []):
                        if str(row.get("pdno") or "") == safe_symbol:
                            candidate = str(row.get("odno") or "").strip()
                            if candidate:
                                kis_order_no = candidate
                                logger.info(
                                    "INFO: [S8/S9] ODNO recovered from ccld symbol=%s odno=%s",
                                    safe_symbol,
                                    kis_order_no,
                                )
                                break
                except Exception as ccld_exc:
                    logger.warning("WARN: [S8/S9] ccld fallback failed symbol=%s reason=%s", safe_symbol, ccld_exc)

            status = "submitted" if kis_order_no else "submitted_without_order_no"
            saved_reason = reason if kis_order_no else f"{reason}:submit_uncertain"
            order_id = self._save_order(
                trade_date=today,
                signal_id="",
                symbol=safe_symbol,
                name=safe_name,
                side="sell",
                order_type=order_type,
                qty=safe_qty,
                price=safe_price,
                kis_order_no=kis_order_no,
                status=status,
                reason=saved_reason,
            )
            if not kis_order_no:
                logger.warning(
                    "WARN: [S8/S9] sell submit uncertain order_id=%s symbol=%s qty=%d reason=missing_kis_order_no",
                    order_id,
                    safe_symbol,
                    safe_qty,
                )
                # 주문은 접수됐을 가능성이 높으므로 포지션에서 제거해 중복 매도 방지
                position_manager.remove_position(safe_symbol)
                return {
                    "ok": False,
                    "order_id": order_id,
                    "status": status,
                    "symbol": safe_symbol,
                    "qty": safe_qty,
                    "kis_order_no": kis_order_no,
                    "reason": "missing_kis_order_no",
                    "uncertain": True,
                }
            position_manager.remove_position(safe_symbol)
            logger.info("SUCCESS: [S8/S9] sell order submitted order_id=%s symbol=%s qty=%d", order_id, safe_symbol, safe_qty)
            return {
                "ok": True,
                "order_id": order_id,
                "status": status,
                "symbol": safe_symbol,
                "qty": safe_qty,
                "kis_order_no": kis_order_no,
            }
        except Exception as exc:
            order_id = self._save_order(
                trade_date=today,
                signal_id="",
                symbol=safe_symbol,
                name=safe_name,
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

    def _calc_budget_qty(
        self,
        baseline: float | None,
        budget_rate: float,
        max_positions: int,
        price: float,
        available_cash: float,
    ) -> int:
        """예산 균등배분 수량 = floor(min(baseline*budget_rate/max_positions, available_cash) / price).

        baseline 결손/비정상 입력이면 0 반환(호출부가 기존 로직으로 폴백).
        """
        if not baseline or baseline <= 0 or budget_rate <= 0 or max_positions <= 0 or price <= 0:
            return 0
        per_slot = baseline * budget_rate / max_positions
        spend = min(per_slot, available_cash if available_cash > 0 else per_slot)
        return int(spend // price)

    def _calc_profile_qty(
        self,
        total_eval: float,
        profile_rate: float,
        deployable_cash: float,
        price: float,
    ) -> int:
        """Profile 비중 사이징 수량 = floor(min(total_eval*profile_rate, deployable_cash) / price).

        total_eval: 총자산(원), profile_rate: Risk Profile 비중(0~1),
        deployable_cash: 95% 한도 내 추가 투입 가능 현금. 어느 하나라도 비정상이면 0.
        """
        if total_eval <= 0 or profile_rate <= 0 or deployable_cash <= 0 or price <= 0:
            return 0
        target = total_eval * profile_rate
        spend = min(target, deployable_cash)
        return int(spend // price)

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

    def _extract_total_eval(self, data: dict[str, Any]) -> float:
        """KIS balance에서 총평가금액(tot_evlu_amt)을 추출. 없으면 0."""
        summary_rows = _as_list(data.get("output2"))
        summary = summary_rows[0] if summary_rows else {}
        for key in ("tot_evlu_amt", "nass_amt", "dnca_tot_amt"):
            value = _to_float(summary.get(key))
            if value > 0:
                return value
        return 0.0

    def _position_size_pct(self, final_rule: dict[str, Any]) -> float:
        """Return position size percent from flat final_rule keys.

        Args:
            final_rule: Resolved symbol rule from rule_cache.get_rule().
        """
        if "position_size_pct" in final_rule:
            return _to_float(final_rule.get("position_size_pct"), POSITION_SIZE_PCT_DEFAULT)
        max_position_rate = _to_float(final_rule.get("max_position_rate"), 0.0)
        if 0 < max_position_rate <= 1:
            return max_position_rate * 100
        if max_position_rate > 1:
            return max_position_rate
        legacy_rate = _to_float(final_rule.get("max_position_size_rate"), 0.0)
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
            resolved_name = str(name or "").strip()
            if symbol and not resolved_name:
                row = conn.execute(
                    "SELECT name FROM symbols WHERE symbol = ? LIMIT 1",
                    (symbol,),
                ).fetchone()
                resolved_name = str(row["name"] or "").strip() if row else ""
            if symbol and not resolved_name:
                row = conn.execute(
                    """
                    SELECT name
                    FROM trading_orders
                    WHERE trade_date = ?
                      AND symbol = ?
                      AND name IS NOT NULL
                      AND name != ''
                    ORDER BY CASE WHEN side = 'buy' THEN 0 ELSE 1 END, created_at DESC
                    LIMIT 1
                    """,
                    (trade_date, symbol),
                ).fetchone()
                resolved_name = str(row["name"] or "").strip() if row else ""
            if symbol and not resolved_name:
                row = conn.execute(
                    """
                    SELECT name
                    FROM trading_signals
                    WHERE symbol = ?
                      AND name IS NOT NULL
                      AND name != ''
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (symbol,),
                ).fetchone()
                resolved_name = str(row["name"] or "").strip() if row else ""
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
                    resolved_name,
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
