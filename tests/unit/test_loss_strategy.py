# tests/unit/test_loss_strategy.py
import unittest
from backend.services.engine import loss_strategy


class ClampTest(unittest.TestCase):
    def test_clamp_within_bounds_returns_value(self):
        self.assertEqual(loss_strategy.clamp_setting("engine.min_volume_ratio", 3.0), 3.0)

    def test_clamp_above_max_returns_max(self):
        self.assertEqual(loss_strategy.clamp_setting("risk.max_position_rate_per_stock", 0.9), 0.30)

    def test_clamp_below_min_returns_min(self):
        self.assertEqual(loss_strategy.clamp_setting("engine.min_volume_ratio", 0.1), 1.0)

    def test_non_whitelisted_key_returns_none(self):
        self.assertIsNone(loss_strategy.clamp_setting("schedule_s6_time", "09:00"))

    def test_is_tunable(self):
        self.assertTrue(loss_strategy.is_tunable("engine.max_price_change_pct"))
        self.assertFalse(loss_strategy.is_tunable("risk.emergency_halt_enabled"))


if __name__ == "__main__":
    unittest.main()
