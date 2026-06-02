"""재생성 보존 가드 테스트.

빈/검증실패 재생성이 기존 active 데일리플랜을 덮어쓰지 않도록 보존하는지 검증한다.
(장중 재선별이 후보 0종목인 빈 플랜을 만들어 아침 active 플랜을 클로버링하던 버그 방지)
"""

import sqlite3
import unittest
from unittest.mock import patch

from backend.services.engine import daily_plan


def _make_db(active_status: str | None) -> sqlite3.Connection:
    """daily_trading_plans 최소 스키마 + 선택적으로 active 플랜 1건 시드."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE daily_trading_plans (id TEXT, trade_date TEXT, status TEXT, created_at TEXT)"
    )
    if active_status is not None:
        conn.execute(
            "INSERT INTO daily_trading_plans (id, trade_date, status, created_at) VALUES (?, ?, ?, ?)",
            ("daily-2026-06-02", "2026-06-02", active_status, "2026-06-02T00:00:00Z"),
        )
    return conn


class PreserveActivePlanGuardTest(unittest.TestCase):
    """_preserved_active_plan_id 의 보존 판단을 검증한다."""

    def _call(self, *, db_status, creation_mode, failed_count):
        conn = _make_db(db_status)
        with patch.object(daily_plan, "get_connection", return_value=conn):
            return daily_plan._preserved_active_plan_id(
                "2026-06-02", creation_mode, {"failed_count": failed_count}
            )

    def test_preserve_when_failed_and_active_exists(self):
        """검증 실패 + 기존 active 존재 → 보존(active id 반환)."""
        self.assertEqual(
            self._call(db_status="active", creation_mode="auto", failed_count=1),
            "daily-2026-06-02",
        )

    def test_no_preserve_when_validation_passed(self):
        """검증 통과(failed_count=0)면 정상 덮어쓰기 진행 → None."""
        self.assertIsNone(
            self._call(db_status="active", creation_mode="auto", failed_count=0)
        )

    def test_no_preserve_when_no_active_plan(self):
        """기존 active 플랜이 없으면(아침 최초 생성 등) 보존 대상 없음 → None."""
        self.assertIsNone(
            self._call(db_status="validation_failed", creation_mode="auto", failed_count=1)
        )

    def test_no_preserve_for_dry_run(self):
        """dry_run 생성은 저장 안 하므로 보존 판단 제외 → None."""
        self.assertIsNone(
            self._call(db_status="active", creation_mode="dry_run", failed_count=1)
        )


if __name__ == "__main__":
    unittest.main()
