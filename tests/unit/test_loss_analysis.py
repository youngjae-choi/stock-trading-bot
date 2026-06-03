import sqlite3
import unittest
from unittest.mock import patch

from backend.services.engine import loss_analysis


def _db(rows):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE false_positive_cases
        (id TEXT, trade_date TEXT, symbol TEXT, symbol_name TEXT, exit_reason TEXT,
         assigned_profile TEXT, pnl_pct REAL, pnl_amount REAL, reviewed_at TEXT)""")
    for r in rows:
        conn.execute(
            "INSERT INTO false_positive_cases (id,trade_date,symbol,exit_reason,assigned_profile,pnl_pct,reviewed_at) "
            "VALUES (?,?,?,?,?,?,?)",
            r,
        )
    return conn


class GlobalGateTest(unittest.TestCase):
    def test_refuse_when_fewer_than_three(self):
        conn = _db([
            ("1", "2026-06-02", "A", "INITIAL_STOP_LOSS", "MID_VOL", -0.01, None),
            ("2", "2026-06-02", "B", "INITIAL_STOP_LOSS", "MID_VOL", -0.01, None),
        ])
        with patch.object(loss_analysis, "get_connection", return_value=conn):
            res = loss_analysis.collect_unreviewed_losses("2026-05-01", "2026-06-03")
        self.assertEqual(len(res), 2)
        self.assertTrue(loss_analysis.is_sample_insufficient(res))

    def test_sufficient_at_three(self):
        rows = [(str(i), "2026-06-02", f"S{i}", "INITIAL_STOP_LOSS", "MID_VOL", -0.01, None) for i in range(3)]
        conn = _db(rows)
        with patch.object(loss_analysis, "get_connection", return_value=conn):
            res = loss_analysis.collect_unreviewed_losses("2026-05-01", "2026-06-03")
        self.assertFalse(loss_analysis.is_sample_insufficient(res))


class ApplyTest(unittest.TestCase):
    def test_apply_calls_upsert_and_marks_reviewed(self):
        applied = [{"setting_key": "engine.min_price_change_pct", "new_value": 3.5,
                    "reason": "x", "pattern": "INITIAL_STOP_LOSS", "sample": 3}]
        cases = [{"id": "1"}, {"id": "2"}, {"id": "3"}]
        calls = {"upsert": [], "reviewed": []}
        with patch.object(loss_analysis, "upsert_setting", lambda *a, **k: calls["upsert"].append((a, k))), \
             patch.object(loss_analysis, "_mark_reviewed", lambda ids: calls["reviewed"].extend(ids)):
            loss_analysis.apply_strategies(applied, cases)
        self.assertEqual(len(calls["upsert"]), 1)
        self.assertEqual(set(calls["reviewed"]), {"1", "2", "3"})


class AnalyzeTest(unittest.TestCase):
    def test_refused_when_insufficient(self):
        with patch.object(loss_analysis, "collect_unreviewed_losses", return_value=[{"id": "1"}]):
            res = loss_analysis.analyze("2026-05-01", "2026-06-03")
        self.assertTrue(res["refused"])
        self.assertEqual(res["needed"], 3)

    def test_success_returns_proposals_without_applying(self):
        cases = [
            {"id": str(i), "symbol": f"S{i}", "exit_reason": "INITIAL_STOP_LOSS",
             "assigned_profile": "MID_VOL", "pnl_pct": -0.01}
            for i in range(3)
        ]
        with patch.object(loss_analysis, "collect_unreviewed_losses", return_value=cases), \
             patch.object(loss_analysis, "apply_strategies") as apply_mock:
            res = loss_analysis.analyze("2026-05-01", "2026-06-03")
        self.assertFalse(res["refused"])
        self.assertGreaterEqual(len(res["proposed"]), 1)
        apply_mock.assert_not_called()


class MergeTest(unittest.TestCase):
    def test_conflict_keeps_conservative_value(self):
        # 같은 설정 키에 두 제안 → 더 보수적(손실 방어적)인 값 채택.
        # min_price_change_pct는 높을수록 보수적(추격 진입 축소).
        false_p = [{"setting_key":"engine.min_price_change_pct","new_value":3.5,"reason":"F","pattern":"INITIAL_STOP_LOSS","sample":3}]
        missed_p = [{"setting_key":"engine.min_price_change_pct","new_value":4.0,"reason":"M","pattern":"x","sample":3}]
        merged = loss_analysis._merge_proposals(false_p, missed_p)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["new_value"], 4.0)
