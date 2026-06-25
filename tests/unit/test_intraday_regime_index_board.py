"""SET 전환 모니터의 index-board regime/VIX 연동 테스트 (시황 단일출처 후속).

- _get_index_board_regime: morning_context 최신 regime
- _get_index_board_vix: market_tone_results.parsed_numbers 최신 VIX
- check_intraday_regime: index-board regime 우선(미가용 시 _judge_regime 폴백),
  VIX는 index-board 우선, 실시간 KOSPI는 KIS 유지.
"""
import json
import tempfile
import unittest
from unittest.mock import patch

from backend.config import settings
from backend.services.engine import intraday_regime_monitor as m


class IndexBoardRegimeHelpersTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._p = f"{self._tmp.name}/t.sqlite3"
        self._patch = patch.object(settings, "APP_DB_PATH", self._p)
        self._patch.start()
        from backend.services.db import get_connection
        with get_connection() as c:
            c.execute("CREATE TABLE morning_context (id TEXT, trade_date TEXT, regime TEXT, created_at TEXT)")
            c.execute("CREATE TABLE market_tone_results (id TEXT, trade_date TEXT, parsed_numbers TEXT, created_at TEXT)")

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmp.cleanup()

    def _ins_ctx(self, regime, created_at, td="2026-06-26"):
        from backend.services.db import get_connection
        with get_connection() as c:
            c.execute("INSERT INTO morning_context VALUES (?,?,?,?)", ("x", td, regime, created_at))

    def _ins_tone(self, numbers, created_at, td="2026-06-26"):
        from backend.services.db import get_connection
        with get_connection() as c:
            c.execute("INSERT INTO market_tone_results VALUES (?,?,?,?)", ("x", td, json.dumps(numbers), created_at))

    def test_regime_latest_by_created_at(self):
        self._ins_ctx("neutral", "2026-06-26T00:01:00Z")
        self._ins_ctx("risk_off", "2026-06-26T05:00:00Z")
        self.assertEqual(m._get_index_board_regime("2026-06-26"), "risk_off")

    def test_regime_none_when_absent(self):
        self.assertIsNone(m._get_index_board_regime("2026-06-26"))

    def test_regime_none_when_empty_string(self):
        self._ins_ctx("", "2026-06-26T05:00:00Z")
        self.assertIsNone(m._get_index_board_regime("2026-06-26"))

    def test_vix_latest(self):
        self._ins_tone({"vix": 17.0}, "2026-06-26T00:01:00Z")
        self._ins_tone({"vix": 18.84}, "2026-06-26T02:31:00Z")
        self.assertEqual(m._get_index_board_vix("2026-06-26"), 18.84)

    def test_vix_none_when_empty(self):
        self._ins_tone({}, "2026-06-26T02:31:00Z")
        self.assertIsNone(m._get_index_board_vix("2026-06-26"))


class CheckIntradayRegimeWiringTest(unittest.IsolatedAsyncioTestCase):
    async def test_prefers_index_board_regime_over_judge(self):
        captured = {}

        def fake_preview(regime, vix, kospi, trade_date):
            captured["regime"] = regime
            captured["vix"] = vix
            return {"set_id": "S1"}  # 현재 SET과 동일 → no_change(전환/기록 회피)

        with patch.object(m, "get_today_application", return_value={"set_id": "S1", "regime_label": "neutral", "set_name": "n"}), \
             patch.object(m, "_should_skip_transition", return_value=False), \
             patch.object(m, "_get_index_board_vix", return_value=18.84), \
             patch.object(m, "_get_current_kospi_change", return_value=0.5), \
             patch.object(m, "_get_index_board_regime", return_value="risk_off"), \
             patch.object(m, "get_match_preview", side_effect=fake_preview):
            res = await m.check_intraday_regime(slot="test")
        # _judge_regime(18.84, 0.5)=neutral 이지만 index-board regime(risk_off)이 우선돼야 함
        self.assertEqual(captured["regime"], "risk_off")
        self.assertEqual(captured["vix"], 18.84)  # index-board VIX 사용
        self.assertEqual(res["action"], "no_change")

    async def test_falls_back_to_judge_when_no_index_board(self):
        captured = {}

        def fake_preview(regime, vix, kospi, trade_date):
            captured["regime"] = regime
            return {"set_id": "S1"}

        with patch.object(m, "get_today_application", return_value={"set_id": "S1", "regime_label": "neutral", "set_name": "n"}), \
             patch.object(m, "_should_skip_transition", return_value=False), \
             patch.object(m, "_get_index_board_vix", return_value=None), \
             patch.object(m, "_get_morning_vix", return_value=30.0), \
             patch.object(m, "_get_current_kospi_change", return_value=-2.0), \
             patch.object(m, "_get_index_board_regime", return_value=None), \
             patch.object(m, "get_match_preview", side_effect=fake_preview):
            await m.check_intraday_regime(slot="test")
        # index-board 미가용 → _judge_regime(30.0, -2.0)=volatile 폴백
        self.assertEqual(captured["regime"], "volatile")


if __name__ == "__main__":
    unittest.main()
