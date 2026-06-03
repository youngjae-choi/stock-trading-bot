"""거래일/휴장일 판정(trading_calendar) 테스트."""

import unittest

from backend.services.engine import trading_calendar as tc


class TradingCalendarTest(unittest.TestCase):
    def test_weekday_trading_day(self):
        self.assertTrue(tc.is_trading_day("2026-06-02"))  # 화요일
        self.assertIsNone(tc.non_trading_reason("2026-06-02"))

    def test_weekend_closed(self):
        self.assertFalse(tc.is_trading_day("2026-05-30"))  # 토
        self.assertEqual(tc.non_trading_reason("2026-05-31"), "weekend")  # 일

    def test_weekday_holiday_closed(self):
        # 어린이날(5/5)·현충일(6/6) 등 평일 공휴일도 휴장으로 잡아야 한다 (핵심 버그)
        self.assertFalse(tc.is_trading_day("2026-05-05"))
        self.assertIsNotNone(tc.non_trading_reason("2026-05-05"))

    def test_accepts_compact_and_dash_formats(self):
        self.assertEqual(tc.is_trading_day("20260602"), tc.is_trading_day("2026-06-02"))


if __name__ == "__main__":
    unittest.main()
