"""Unit tests for intraday reselection v2 backend helpers."""

from __future__ import annotations
import sqlite3
import unittest
from unittest.mock import AsyncMock, patch

from backend.services.engine import replacement_signal, sector_rotation


def _init_reselection_schema(conn: sqlite3.Connection) -> None:
    """Create the minimal tables used by reselection v2 service tests."""
    conn.execute(
        """
        CREATE TABLE symbols (
            symbol TEXT PRIMARY KEY,
            market TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL DEFAULT '',
            sector TEXT NOT NULL DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE trading_signals (
            id TEXT PRIMARY KEY,
            trade_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            signal_type TEXT NOT NULL DEFAULT 'BUY',
            trigger_price REAL NOT NULL DEFAULT 0.0,
            confidence REAL NOT NULL DEFAULT 0.0,
            rule_matched TEXT NOT NULL DEFAULT '{}',
            profile_assigned TEXT NOT NULL DEFAULT 'MID_VOL',
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL
        )
        """
    )


class SectorRotationDetectionTest(unittest.TestCase):
    """Verify sector rotation detection uses snapshot["sectors"] (KIS sector indices)."""

    def test_detect_sector_rotation_triggers_when_top_two_gap_exceeds_threshold(self) -> None:
        """Top sectors outperforming the rest by at least the configured gap must trigger.

        Input is snapshot["sectors"] — KIS sector-index change rates collected by
        fetch_intraday_kr_market_snapshot (no per-stock grouping / symbols lookup).
        """
        snapshot = {
            "sectors": [
                {"name": "반도체", "change_rate": 5.0},
                {"name": "바이오", "change_rate": 4.0},
                {"name": "통신", "change_rate": -1.0},
                {"name": "금융", "change_rate": -2.0},
            ]
        }

        with patch.object(
            sector_rotation, "get_setting", side_effect=lambda key, default=None: default
        ):
            result = sector_rotation.detect_sector_rotation(snapshot, trade_date="2026-05-25")

        self.assertTrue(result["triggered"])
        self.assertGreaterEqual(result["gap_pct"], 3.0)
        self.assertIn("반도체", result["reason"])

    def test_detect_sector_rotation_skips_when_fewer_than_three_sectors(self) -> None:
        """Insufficient sector sample (<3) must skip rather than trigger."""
        snapshot = {
            "sectors": [
                {"name": "반도체", "change_rate": 5.0},
                {"name": "바이오", "change_rate": -2.0},
            ]
        }

        with patch.object(
            sector_rotation, "get_setting", side_effect=lambda key, default=None: default
        ):
            result = sector_rotation.detect_sector_rotation(snapshot, trade_date="2026-05-25")

        self.assertFalse(result["triggered"])
        self.assertEqual(result["reason"], "sector_sample_insufficient")


class ReplacementSignalEvaluationTest(unittest.IsolatedAsyncioTestCase):
    """Verify replacement signal creation remains signal-only and deduplicated."""

    async def asyncSetUp(self) -> None:
        """Prepare an isolated DB for replacement signal tests."""
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        _init_reselection_schema(self.conn)
        self.conn.execute("INSERT INTO symbols (symbol, name, sector) VALUES ('005930', '삼성전자', '반도체')")
        self.conn.execute("INSERT INTO symbols (symbol, name, sector) VALUES ('035420', 'NAVER', '인터넷')")

    async def asyncTearDown(self) -> None:
        """Close the isolated DB."""
        self.conn.close()

    async def test_evaluate_replacement_signals_creates_signal_for_15_percent_gap(self) -> None:
        """A new candidate at least 15% better than the held score should be persisted."""
        settings = {
            "intraday_refresh.master_enabled": True,
            "intraday_refresh.replacement_signal_enabled": True,
            "intraday_refresh.replacement_score_gap": 0.15,
            "intraday_refresh.max_replacement_per_symbol": 1,
            "intraday_refresh.max_replacement_per_day": 5,
        }

        with patch.object(replacement_signal, "get_connection", return_value=self.conn), patch.object(
            replacement_signal, "get_setting", side_effect=lambda key, default=None: settings.get(key, default)
        ), patch.object(replacement_signal, "_notify_signal", new=AsyncMock()):
            result = await replacement_signal.evaluate_replacement_signals(
                new_candidates={"035420": {"symbol": "035420", "name": "NAVER", "score": 0.85}},
                current_positions=[{"symbol": "005930", "name": "삼성전자", "score": 0.65, "pnl_pct": -1.2}],
                slot="10:30",
                trade_date="2026-05-25",
            )

        self.assertEqual(result["created"], 1)
        rows = self.conn.execute("SELECT * FROM replacement_signals").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["current_symbol"], "005930")
        self.assertEqual(rows[0]["new_symbol"], "035420")
        self.assertGreaterEqual(rows[0]["score_gap"], 0.15)

    async def test_evaluate_replacement_signals_respects_symbol_daily_limit(self) -> None:
        """A held symbol should not receive more signals than the configured daily limit."""
        settings = {
            "intraday_refresh.master_enabled": True,
            "intraday_refresh.replacement_signal_enabled": True,
            "intraday_refresh.replacement_score_gap": 0.15,
            "intraday_refresh.max_replacement_per_symbol": 1,
            "intraday_refresh.max_replacement_per_day": 5,
        }

        with patch.object(replacement_signal, "get_connection", return_value=self.conn), patch.object(
            replacement_signal, "get_setting", side_effect=lambda key, default=None: settings.get(key, default)
        ), patch.object(replacement_signal, "_notify_signal", new=AsyncMock()):
            first = await replacement_signal.evaluate_replacement_signals(
                [{"symbol": "035420", "name": "NAVER", "score": 0.85}],
                [{"symbol": "005930", "name": "삼성전자", "score": 0.65}],
                slot="10:30",
                trade_date="2026-05-25",
            )
            second = await replacement_signal.evaluate_replacement_signals(
                [{"symbol": "035420", "name": "NAVER", "score": 0.90}],
                [{"symbol": "005930", "name": "삼성전자", "score": 0.65}],
                slot="11:30",
                trade_date="2026-05-25",
            )

        self.assertEqual(first["created"], 1)
        self.assertEqual(second["created"], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) AS count FROM replacement_signals").fetchone()["count"], 1)


if __name__ == "__main__":
    unittest.main()
