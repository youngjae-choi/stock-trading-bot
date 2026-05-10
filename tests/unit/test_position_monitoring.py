"""Regression tests for S8 position monitoring protection."""

from __future__ import annotations

import sqlite3
import unittest
from unittest.mock import AsyncMock, Mock, patch

from backend.api.routes import trading_monitor
from backend.services.engine import decision_engine, eod_liquidation
from backend.services.engine.position_manager import PositionManager


class PositionMonitoringStatusTest(unittest.TestCase):
    """Verify Trading Monitor separates real holdings from active S8 protection."""

    def test_monitoring_status_detects_unprotected_holding(self) -> None:
        """KIS holdings outside PositionManager and WS subscription must be marked unprotected."""
        status = trading_monitor._monitoring_status("005930", {}, set(), "fallback")

        self.assertFalse(status["auto_monitoring"])
        self.assertEqual(status["monitoring_status"], "미감시")
        self.assertFalse(status["ws_subscribed"])
        self.assertFalse(status["position_manager_registered"])

    def test_monitoring_status_detects_active_protection(self) -> None:
        """A symbol in both PositionManager and WS subscriptions is actively protected."""
        status = trading_monitor._monitoring_status("005930", {"005930": {"symbol": "005930"}}, {"005930"}, "persisted")

        self.assertTrue(status["auto_monitoring"])
        self.assertEqual(status["monitoring_status"], "자동감시중")
        self.assertTrue(status["ws_subscribed"])
        self.assertTrue(status["position_manager_registered"])

    def test_monitoring_status_detects_subscription_mismatch(self) -> None:
        """A PositionManager symbol without realtime subscription is a mismatch, not protected."""
        status = trading_monitor._monitoring_status("005930", {"005930": {"symbol": "005930"}}, set(), "persisted")

        self.assertFalse(status["auto_monitoring"])
        self.assertEqual(status["monitoring_status"], "상태불일치")


class PositionManagerTrailingPersistenceTest(unittest.TestCase):
    """Verify trailing activation is persisted even when no new high is made."""

    def test_trailing_activation_persists_without_new_high(self) -> None:
        """Crossing the trailing threshold at the existing high must update stop state storage."""
        manager = PositionManager()
        manager._positions["005930"] = {
            "position_id": "005930-test",
            "symbol": "005930",
            "name": "삼성전자",
            "qty": 1,
            "entry_price": 100.0,
            "entry_time": "2026-05-09T09:00:00+09:00",
            "profile_assigned": "MID_VOL",
            "initial_stop_price": 97.0,
            "active_stop_price": 97.0,
            "highest_price_since_entry": 105.0,
            "trailing_active": False,
            "trailing_stop_price": 97.0,
            "trailing_activate_profit": 0.05,
            "trailing_stop_rate": 0.03,
            "max_holding_minutes": 180,
            "force_exit_time": "15:20:00",
        }

        with patch("backend.services.engine.position_manager._upsert_stop_state") as upsert:
            manager._update_trailing(manager._positions["005930"], 105.0)

        self.assertTrue(manager._positions["005930"]["trailing_active"])
        upsert.assert_called_once()
        saved = upsert.call_args.args[1]
        self.assertTrue(saved["trailing_active"])
        self.assertEqual(saved["highest_price_since_entry"], 105.0)


class DecisionEngineAccountSyncTest(unittest.TestCase):
    """Verify KIS holdings sync only already managed S8 positions."""

    def test_sync_managed_positions_updates_quantity_without_adding_unmanaged_holding(self) -> None:
        """KIS-only holdings must not become automatic sell targets without strategy ownership."""
        fake_manager = Mock()
        fake_manager.get_positions.return_value = [{"symbol": "005930", "qty": 10}]
        fake_manager.update_position_quantity = Mock(return_value=True)
        fake_manager.remove_position = Mock()
        account_positions = [
            {"symbol": "005930", "name": "삼성전자", "qty": 6, "avg_price": 70000},
            {"symbol": "000660", "name": "SK하이닉스", "qty": 2, "avg_price": 120000},
        ]

        with patch("backend.services.engine.position_manager.position_manager", fake_manager):
            symbols = decision_engine._sync_managed_positions_with_account(account_positions)

        self.assertEqual(symbols, ["005930"])
        fake_manager.update_position_quantity.assert_called_once_with("005930", 6)
        fake_manager.remove_position.assert_not_called()
        self.assertFalse(fake_manager.add_position.called)

    def test_sync_managed_positions_removes_position_missing_from_kis_holdings(self) -> None:
        """A managed symbol absent from KIS holdings must be removed to prevent oversell."""
        fake_manager = Mock()
        fake_manager.get_positions.return_value = [{"symbol": "005930", "qty": 10}]
        fake_manager.update_position_quantity = Mock(return_value=True)
        fake_manager.remove_position = Mock()

        with patch("backend.services.engine.position_manager.position_manager", fake_manager):
            symbols = decision_engine._sync_managed_positions_with_account([])

        self.assertEqual(symbols, [])
        fake_manager.update_position_quantity.assert_not_called()
        fake_manager.remove_position.assert_called_once_with("005930")


class EODLiquidationPolicyTest(unittest.IsolatedAsyncioTestCase):
    """Verify administrator timed liquidation uses all KIS holdings."""

    async def test_eod_liquidation_sells_all_kis_account_holdings(self) -> None:
        """Timed liquidation must target KIS holdings regardless of PositionManager ownership."""
        account_positions = [
            {"symbol": "005930", "qty": 3, "source": "kis_account"},
            {"symbol": "000660", "qty": 2, "source": "kis_account"},
        ]
        sell = AsyncMock(side_effect=[
            {"ok": True, "kis_order_no": "KIS-1", "symbol": "005930", "qty": 3},
            {"ok": True, "kis_order_no": "KIS-2", "symbol": "000660", "qty": 2},
        ])

        with patch("backend.services.engine.eod_liquidation._record_legacy_residual_alert", return_value=[]), \
             patch("backend.services.engine.eod_liquidation._get_open_positions_from_account", new=AsyncMock(return_value=account_positions)), \
             patch("backend.services.engine.eod_liquidation.find_active_sell_order", return_value=None), \
             patch("backend.services.engine.eod_liquidation.order_executor.execute_sell", sell):
            result = await eod_liquidation.run_eod_liquidation()

        self.assertEqual(result["liquidated"], 2)
        self.assertEqual(result["summary"]["submitted"], 2)
        sell.assert_any_await(symbol="005930", qty=3, price=0, reason="eod")
        sell.assert_any_await(symbol="000660", qty=2, price=0, reason="eod")



class TradingMonitorStopStateTest(unittest.TestCase):
    """Verify stop-state date filtering follows stored KST date strings."""

    def test_latest_stop_states_uses_stored_kst_date_prefix(self) -> None:
        """A +09:00 early-morning ISO timestamp must remain on its KST calendar date."""
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.execute(
            """
            CREATE TABLE position_stop_states (
                position_id TEXT PRIMARY KEY,
                symbol_code TEXT NOT NULL,
                entry_price REAL NOT NULL DEFAULT 0.0,
                highest_price_since_entry REAL NOT NULL DEFAULT 0.0,
                initial_stop_price REAL NOT NULL DEFAULT 0.0,
                trailing_stop_price REAL NOT NULL DEFAULT 0.0,
                active_stop_price REAL NOT NULL DEFAULT 0.0,
                trailing_active INTEGER NOT NULL DEFAULT 0,
                profile_assigned TEXT NOT NULL DEFAULT 'MID_VOL',
                last_updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO position_stop_states
                (position_id, symbol_code, entry_price, highest_price_since_entry, initial_stop_price,
                 trailing_stop_price, active_stop_price, trailing_active, profile_assigned, last_updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("p1", "005930", 100.0, 128.0, 97.0, 124.0, 124.0, 1, "MID_VOL", "2026-05-09T00:30:00+09:00"),
        )

        with patch("backend.api.routes.trading_monitor.get_connection", return_value=connection), \
             patch("backend.api.routes.trading_monitor._today_kst", return_value="2026-05-09"):
            states = trading_monitor._latest_stop_states()

        self.assertIn("005930", states)
        self.assertEqual(states["005930"]["position_id"], "p1")



if __name__ == "__main__":
    unittest.main()
