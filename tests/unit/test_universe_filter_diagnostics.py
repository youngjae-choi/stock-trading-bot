"""Regression tests for S3 universe diagnostics and schedule safety."""

from __future__ import annotations

import unittest

from backend.services import scheduler
from backend.services.engine import universe_filter
from backend.services.kis.domestic import universe_service


class KISUniverseParsingTest(unittest.TestCase):
    """Verify KIS ranking parsers accept alternate field names."""

    def test_pick_int_accepts_alternate_trade_amount_field(self) -> None:
        """Alternate KIS amount keys must not normalize to zero."""
        row = {"acc_trdval": "1,234,567"}

        self.assertEqual(universe_service._pick_int(row, universe_service._TRADE_AMOUNT_KEYS), 1234567)

    def test_pick_float_accepts_alternate_change_rate_field(self) -> None:
        """Alternate KIS rate keys must preserve decimal values."""
        row = {"prdy_vrss_rate": "3.45"}

        self.assertEqual(universe_service._pick_float(row, universe_service._CHANGE_RATE_KEYS), 3.45)


class UniverseFilterDiagnosticsTest(unittest.TestCase):
    """Verify S3 explains empty candidate causes without forcing trades."""

    def test_liquidity_not_ready_status_when_all_rows_have_no_liquidity(self) -> None:
        """Rows with price but no volume/trade amount are classified as not ready."""
        counts = universe_filter._count_filter_rejections([
            {"symbol": "005930", "price": 70000, "change_rate": 1.0, "volume": 0, "trade_amount": 0},
            {"symbol": "000660", "price": 150000, "change_rate": -1.0, "volume": 0, "trade_amount": 0},
        ])

        self.assertEqual(counts["empty_liquidity"], 2)
        self.assertEqual(universe_filter._market_data_readiness_status(2, counts), "liquidity_not_ready")

    def test_volume_ranked_rows_survive_filters(self) -> None:
        """Volume-ranked momentum rows remain candidates and carry volume_surge.

        단타 모멘텀 전환: 거래대금 소스 제거. 거래량 순위 행은 volume>0 으로
        유동성 floor 를 통과하며 volume_surge(전일대비 거래량증가율%)를 carry 한다.
        """
        merged = universe_filter._merge_and_deduplicate(
            [{"symbol": "005930", "name": "삼성전자", "price": 70000,
              "change_rate": 1.0, "volume": 5_000_000, "volume_surge": 180.0}],
        )

        filtered = universe_filter._apply_filters(merged)

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["symbol"], "005930")
        self.assertEqual(filtered[0]["volume_surge"], 180.0)


class SchedulerMarketOpenGuardTest(unittest.TestCase):
    """Verify unsafe early scheduler settings are corrected at runtime."""

    def test_market_open_guard_delays_trade_prep_and_s6(self) -> None:
        """08:25/08:59 settings are too early for S3 ranking data and are guarded."""
        guarded = scheduler._apply_market_open_schedule_guards({
            "trade_prep": "08:25",
            "s6": "08:59",
            "postprocess": "15:20",
            "s11": "22:00",
            "backup": "18:00",
        })

        self.assertEqual(guarded["trade_prep"], "09:01")
        self.assertEqual(guarded["s6"], "09:10")


if __name__ == "__main__":
    unittest.main()
