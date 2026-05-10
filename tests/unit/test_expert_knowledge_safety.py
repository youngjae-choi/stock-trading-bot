"""Regression tests for Knowledge/Settings PDF strategy safety boundaries."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import unittest
from unittest.mock import Mock, patch

from backend.api.routes import expert_knowledge as expert_knowledge_api
from backend.services.engine import expert_knowledge


def _init_knowledge_schema(conn: sqlite3.Connection) -> None:
    """Create the minimal Knowledge tables required by the service tests."""
    _ = conn.execute(
        """
        CREATE TABLE strategy_knowledge_items (
            id TEXT PRIMARY KEY,
            source_id TEXT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            scope TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'general',
            status TEXT NOT NULL DEFAULT 'pending',
            auto_inject INTEGER NOT NULL DEFAULT 0,
            priority INTEGER NOT NULL DEFAULT 5,
            created_at TEXT NOT NULL,
            approved_at TEXT,
            expires_at TEXT
        )
        """
    )
    _ = conn.execute(
        """
        CREATE TABLE knowledge_approval_logs (
            id TEXT PRIMARY KEY,
            knowledge_id TEXT NOT NULL,
            action TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
        """
    )


class StrategySafetyClassificationTest(unittest.TestCase):
    """Verify LLM strategy candidates are split by safe Settings vs PM approval."""

    def test_normalize_marks_risky_mapped_settings_as_pm_approval_required(self) -> None:
        """Risk keys remain mapped but are not auto-applicable."""
        normalized = expert_knowledge._normalize_strategy_analysis(
            {
                "strategy_candidates": [
                    {
                        "label": "손실 한도",
                        "value": "3",
                        "setting_key": "risk.daily_loss_limit_percent",
                        "reason": "PDF 손실 제한",
                    },
                    {
                        "label": "AI 신뢰도",
                        "value": "0.7",
                        "setting_key": "engine.min_confidence_floor",
                        "reason": "PDF 신뢰도 조건",
                    },
                ],
                "unmappable": [{"label": "뉴스 감성", "description": "Settings 없음", "raw_text": "뉴스"}],
            }
        )

        risky, safe = normalized["strategy_candidates"]
        self.assertEqual(risky["safety_status"], "pm_approval_required")
        self.assertFalse(risky["auto_applicable"])
        self.assertTrue(risky["approval_required"])
        self.assertEqual(safe["safety_status"], "safe_auto_apply")
        self.assertTrue(safe["auto_applicable"])
        self.assertEqual(normalized["unmappable"][0]["status"], "dev_required")


class DevRequiredKnowledgePersistenceTest(unittest.TestCase):
    """Verify unmappable strategy items become non-active dev_required Knowledge rows."""

    conn: sqlite3.Connection

    def __init__(self, methodName: str = "runTest") -> None:
        """Initialize the connection attribute for strict diagnostics before setUp replaces it."""
        super().__init__(methodName)
        self.conn = sqlite3.connect(":memory:")
        self.conn.close()

    def setUp(self) -> None:
        """Prepare an isolated in-memory Knowledge database."""
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        _init_knowledge_schema(self.conn)

    def tearDown(self) -> None:
        """Close the isolated database after each test."""
        self.conn.close()

    def test_dev_required_items_are_persisted_but_not_active(self) -> None:
        """개발필요 rows must be operator-visible but excluded from active prompt injection."""
        with patch.object(expert_knowledge, "get_connection", return_value=self.conn):
            created = expert_knowledge.persist_unmappable_strategy_items(
                [{"label": "뉴스 감성", "description": "Settings 없음", "raw_text": "뉴스 점수"}],
                "strategy.pdf",
                "analysis-1",
            )
            listed = expert_knowledge.list_knowledge_items(status="dev_required")
            active = expert_knowledge.get_active_knowledge("S5_DAILY_PLAN")

        self.assertEqual(len(created), 1)
        self.assertEqual(listed[0]["status"], "dev_required")
        self.assertIn("[개발필요] 뉴스 감성", listed[0]["title"])
        self.assertEqual(active, [])


class ApplyStrategySafetyTest(unittest.TestCase):
    """Verify apply-strategy writes only safe Settings values."""

    conn: sqlite3.Connection

    def __init__(self, methodName: str = "runTest") -> None:
        """Initialize the connection attribute for strict diagnostics before setUp replaces it."""
        super().__init__(methodName)
        self.conn = sqlite3.connect(":memory:")
        self.conn.close()

    def setUp(self) -> None:
        """Prepare an isolated in-memory pdf_analyses table."""
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        _ = self.conn.execute(
            """
            CREATE TABLE pdf_analyses (
                analysis_id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                extracted_text TEXT NOT NULL,
                candidates TEXT NOT NULL DEFAULT '[]',
                unmappable TEXT NOT NULL DEFAULT '[]',
                summary TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                applied_at TEXT
            )
            """
        )

    def tearDown(self) -> None:
        """Close the isolated database after each test."""
        self.conn.close()

    def test_apply_strategy_skips_risky_selected_keys(self) -> None:
        """Selected risk keys are returned as approval-required and never passed to upsert_setting."""
        candidates = [
            {"setting_key": "engine.min_confidence_floor", "value": "0.7"},
            {"setting_key": "risk.daily_loss_limit_percent", "value": "3"},
        ]
        _ = self.conn.execute(
            """
            INSERT INTO pdf_analyses
                (analysis_id, filename, extracted_text, candidates, unmappable, summary, status, created_at, applied_at)
            VALUES (?, 'strategy.pdf', '', ?, '[]', '', 'pending', '2026-05-10T00:00:00.000Z', NULL)
            """,
            ("analysis-1", json.dumps(candidates)),
        )
        upsert_mock = Mock()

        with patch.object(expert_knowledge_api, "get_connection", return_value=self.conn), patch.object(
            expert_knowledge_api, "upsert_setting", upsert_mock
        ):
            result = asyncio.run(
                expert_knowledge_api.apply_strategy(
                    "analysis-1",
                    expert_knowledge_api.StrategyApplyRequest(
                        approved_keys=["engine.min_confidence_floor", "risk.daily_loss_limit_percent"]
                    ),
                    user={"username": "tester"},
                )
            )

        if not isinstance(result, dict):
            self.fail("apply_strategy unexpectedly returned an error response")
        self.assertTrue(result["ok"])
        self.assertEqual([item["setting_key"] for item in result["payload"]["applied"]], ["engine.min_confidence_floor"])
        self.assertEqual(
            [item["setting_key"] for item in result["payload"]["approval_required"]],
            ["risk.daily_loss_limit_percent"],
        )
        upsert_mock.assert_called_once()
        self.assertEqual(upsert_mock.call_args.args[0], "engine.min_confidence_floor")


if __name__ == "__main__":
    unittest.main()
