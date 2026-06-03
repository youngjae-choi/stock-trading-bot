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
