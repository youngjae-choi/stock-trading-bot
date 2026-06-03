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


class DeriveStrategyTest(unittest.TestCase):
    def _cases(self, n, exit_reason="INITIAL_STOP_LOSS", profile="MID_VOL", pnl=-0.018):
        return [
            {"symbol": f"00{i}", "exit_reason": exit_reason,
             "assigned_profile": profile, "pnl_pct": pnl}
            for i in range(n)
        ]

    def test_stop_loss_pattern_3plus_yields_apply(self):
        applied, observing = loss_strategy.derive_strategies(self._cases(3))
        self.assertTrue(any(s["setting_key"] == "engine.min_price_change_pct" for s in applied))
        self.assertEqual(observing, [])

    def test_pattern_below_3_goes_observing(self):
        applied, observing = loss_strategy.derive_strategies(self._cases(2))
        self.assertEqual(applied, [])
        self.assertEqual(len(observing), 1)


if __name__ == "__main__":
    unittest.main()
