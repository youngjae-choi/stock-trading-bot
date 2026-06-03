import unittest
from backend.services.engine import tsi


class TsiTest(unittest.TestCase):
    def test_uptrend_positive(self):
        closes = [100 + i for i in range(40)]
        v = tsi.compute_tsi(closes)
        self.assertIsNotNone(v)
        self.assertGreater(v, 0)

    def test_downtrend_negative(self):
        closes = [100 - i for i in range(40)]
        v = tsi.compute_tsi(closes)
        self.assertLess(v, 0)

    def test_insufficient_data_returns_none(self):
        self.assertIsNone(tsi.compute_tsi([100, 101, 102]))

    def test_bounded_range(self):
        closes = [100 + (i % 3) for i in range(50)]
        v = tsi.compute_tsi(closes)
        self.assertGreaterEqual(v, -100.0)
        self.assertLessEqual(v, 100.0)
