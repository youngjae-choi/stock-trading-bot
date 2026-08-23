"""SET 전환 모니터의 index-board regime/VIX 연동 테스트 (시황 단일출처 후속).

- _get_index_board_regime: morning_context 최신 regime
- _get_index_board_vix: market_tone_results.parsed_numbers 최신 VIX
- check_intraday_regime: index-board regime 우선(미가용 시 _judge_regime 폴백),
  VIX는 index-board 우선, 실시간 KOSPI는 KIS 유지.
"""
import json
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from backend.config import settings
from backend.services import settings_store as _settings_store
from backend.services.engine import intraday_regime_monitor as m

# set_source 기본이 5tier(활성 2026-08-23)로 바뀌어, judge/index-board 경로를 검증하는
# legacy 테스트는 set_source=judge를 강제해야 한다(그 외 설정은 원본 위임).
_orig_get_setting = _settings_store.get_setting


def _force_judge_source(key, default=None):
    if key == "regime.set_source":
        return "judge"
    return _orig_get_setting(key, default)


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
    async def test_legacy_prefers_index_board_when_live_driver_off(self):
        """롤백(intraday_live_driver_enabled=false) 시 기존 동작 — index-board regime 우선."""
        captured = {}

        def fake_preview(regime, vix, kospi, trade_date):
            captured["regime"] = regime
            captured["vix"] = vix
            return {"set_id": "S1"}  # 현재 SET과 동일 → no_change

        with patch("backend.services.settings_store.get_setting", side_effect=_force_judge_source), \
             patch.object(m, "get_today_application", return_value={"set_id": "S1", "regime_label": "neutral", "set_name": "n"}), \
             patch.object(m, "_should_skip_transition", return_value=False), \
             patch.object(m, "_intraday_live_driver_enabled", return_value=False), \
             patch.object(m, "_get_index_board_vix", return_value=18.84), \
             patch.object(m, "_fetch_kospi_change", new=AsyncMock(return_value=0.5)), \
             patch.object(m, "_get_index_board_regime", return_value="risk_off"), \
             patch.object(m, "get_match_preview", side_effect=fake_preview):
            res = await m.check_intraday_regime(slot="test")
        self.assertEqual(captured["regime"], "risk_off")  # 롤백(judge): index-board 우선
        self.assertEqual(captured["vix"], 18.84)
        self.assertEqual(res["action"], "no_change")

    async def test_live_driver_uses_judge_over_frozen_index_board(self):
        """기본(live_driver ON) — 동결된 index-board risk_off 대신 실시간 KIS KOSPI로 판단.

        오늘 8/11 버그: ib_regime=risk_off 동결(09:01 이후 미갱신) → 종일 방어 → 매수 0.
        수정 후: 실시간 KOSPI +0.6% + VIX 15 → _judge_regime=risk_on 으로 장중 전환 가능.
        """
        captured = {}

        def fake_preview(regime, vix, kospi, trade_date):
            captured["regime"] = regime
            captured["kospi"] = kospi
            return {"set_id": "S1"}

        with patch("backend.services.settings_store.get_setting", side_effect=_force_judge_source), \
             patch.object(m, "get_today_application", return_value={"set_id": "S1", "regime_label": "risk_off", "set_name": "방어"}), \
             patch.object(m, "_should_skip_transition", return_value=False), \
             patch.object(m, "_get_index_board_vix", return_value=15.0), \
             patch.object(m, "_fetch_kospi_change", new=AsyncMock(return_value=0.6)), \
             patch.object(m, "_get_index_board_regime", return_value="risk_off"), \
             patch.object(m, "get_match_preview", side_effect=fake_preview):
            await m.check_intraday_regime(slot="test")
        # 동결 risk_off 무시하고 실시간 _judge_regime(15.0, 0.6)=risk_on 사용
        self.assertEqual(captured["regime"], "risk_on")
        self.assertEqual(captured["kospi"], 0.6)


class FetchKospiChangeTest(unittest.IsolatedAsyncioTestCase):
    async def test_uses_kis_index_when_available(self):
        with patch("backend.services.kis.domestic.universe_service.get_market_index",
                   new=AsyncMock(return_value={"change_rate": 0.73})):
            change = await m._fetch_kospi_change()
        self.assertEqual(change, 0.73)

    async def test_falls_back_to_snapshot_on_kis_failure(self):
        async def _boom(_code):
            raise RuntimeError("KIS index down")

        with patch("backend.services.kis.domestic.universe_service.get_market_index", new=_boom), \
             patch.object(m, "_get_current_kospi_change", return_value=-0.4):
            change = await m._fetch_kospi_change()
        self.assertEqual(change, -0.4)  # market_snapshots 폴백


if __name__ == "__main__":
    unittest.main()
