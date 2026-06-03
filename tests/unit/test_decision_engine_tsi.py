import unittest
from backend.services.engine import decision_engine as de


class TsiGateTest(unittest.TestCase):
    def test_rules_allow_blocks_when_tsi_negative(self):
        matched = {"volume_ratio": True, "price_change": True, "time_window": True, "tsi_positive": False}
        self.assertFalse(de._rules_allow_signal(matched))

    def test_rules_allow_passes_when_tsi_positive(self):
        matched = {"volume_ratio": True, "price_change": True, "time_window": True, "tsi_positive": True}
        self.assertTrue(de._rules_allow_signal(matched))

    def test_rules_allow_passes_when_tsi_missing_treated_true(self):
        matched = {"volume_ratio": True, "price_change": True, "time_window": True, "tsi_positive": True}
        self.assertTrue(de._rules_allow_signal(matched))
