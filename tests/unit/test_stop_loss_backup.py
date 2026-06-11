"""손절 REST 폴링 백업(check_exits_via_rest) 단위 테스트.

WS 단절 시 보유 포지션 손절이 멈추는 문제의 백업 경로를 검증한다.
- WS 정상(최근 틱)이면 REST를 호출하지 않는다 (rate-limit 보호)
- WS 정체(stale) 시 REST 현재가로 on_tick과 동일한 갱신·청산 판정을 수행한다
"""

from __future__ import annotations

import time
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo

from backend.services.engine.position_manager import PositionManager

_KST_10AM = datetime.fromisoformat("2026-06-10T10:00:00+09:00").replace(tzinfo=ZoneInfo("Asia/Seoul"))


def _make_position(symbol: str = "005930", entry: float = 100.0) -> dict:
    """on_tick/_process_price 가 기대하는 형태의 포지션 dict를 생성한다."""
    return {
        "position_id": f"{symbol}-test",
        "symbol": symbol,
        "name": "테스트종목",
        "qty": 5,
        "entry_price": entry,
        "entry_time": "2026-06-10T09:30:00+09:00",
        "entry_ts": datetime.fromisoformat("2026-06-10T09:30:00+09:00").timestamp(),
        "profile_assigned": "MID_VOL",
        "auto_imported": False,
        "initial_stop_price": entry * 0.97,
        "active_stop_price": entry * 0.97,
        "highest_price_since_entry": entry,
        "trough_price": entry,
        "trailing_active": False,
        "trailing_stop_price": entry * 0.97,
        "trailing_activate_profit": 0.025,
        "trailing_stop_rate": 0.03,
        "max_holding_minutes": 180,
        "force_exit_time": "15:20:00",
    }


def _settings(enabled: bool = True, stale_sec: int = 90):
    """get_setting monkeypatch용 — 백업 관련 키만 응답한다."""
    table = {
        "risk.stop_loss_backup_enabled": enabled,
        "risk.stop_loss_backup_stale_sec": stale_sec,
    }

    def _get(key: str, default=None):
        return table.get(key, default)

    return _get


class StopLossBackupTest(unittest.IsolatedAsyncioTestCase):
    """check_exits_via_rest 의 가드/판정/예외 처리 검증."""

    def setUp(self) -> None:
        self.manager = PositionManager()
        self.manager._get_today_tone = Mock(return_value="fallback")

    async def test_skips_rest_when_ws_alive(self) -> None:
        """최근 틱이 있으면(WS 정상) REST를 호출하지 않고 skip 한다."""
        self.manager._positions["005930"] = _make_position()
        self.manager._last_tick_monotonic = time.monotonic()

        rest = AsyncMock()
        with patch("backend.services.engine.position_manager.get_setting", side_effect=_settings()), \
             patch("backend.services.kis.domestic.service.get_current_price", rest):
            result = await self.manager.check_exits_via_rest()

        self.assertTrue(result["ok"])
        self.assertEqual(result.get("skipped"), "ws_alive")
        rest.assert_not_awaited()

    async def test_stale_ws_triggers_sell_below_stop(self) -> None:
        """WS 정체 90s+ 상태에서 손절선 이탈 가격이면 execute_sell 을 호출한다."""
        self.manager._positions["005930"] = _make_position()
        self.manager._last_tick_monotonic = time.monotonic() - 300

        rest = AsyncMock(return_value={"output": {"stck_prpr": "96"}})
        sell = AsyncMock(return_value={"ok": True})
        with patch("backend.services.engine.position_manager.get_setting", side_effect=_settings()), \
             patch("backend.services.kis.domestic.service.get_current_price", rest), \
             patch("backend.services.engine.order_executor.order_executor.execute_sell", sell), \
             patch("backend.services.engine.position_manager._upsert_stop_state"), \
             patch("backend.services.engine.position_manager._now_kst", return_value=_KST_10AM):
            result = await self.manager.check_exits_via_rest()

        sell.assert_awaited_once_with(symbol="005930", qty=5, price=0, reason="INITIAL_STOP_LOSS")
        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["triggered"], ["005930"])
        self.assertEqual(result["errors"], [])

    async def test_no_tick_ever_is_treated_as_stale(self) -> None:
        """_last_tick_monotonic 이 None(틱 수신 전)이면 stale 로 간주하고 REST 검사한다."""
        self.manager._positions["005930"] = _make_position()
        self.assertIsNone(self.manager._last_tick_monotonic)

        rest = AsyncMock(return_value={"output": {"stck_prpr": "96"}})
        sell = AsyncMock(return_value={"ok": True})
        with patch("backend.services.engine.position_manager.get_setting", side_effect=_settings()), \
             patch("backend.services.kis.domestic.service.get_current_price", rest), \
             patch("backend.services.engine.order_executor.order_executor.execute_sell", sell), \
             patch("backend.services.engine.position_manager._upsert_stop_state"), \
             patch("backend.services.engine.position_manager._now_kst", return_value=_KST_10AM):
            result = await self.manager.check_exits_via_rest()

        sell.assert_awaited_once()
        self.assertEqual(result["triggered"], ["005930"])

    async def test_price_above_stop_updates_peak_and_trough_without_sell(self) -> None:
        """손절선 위 가격이면 청산하지 않고 peak/trough(MFE·MAE)만 갱신한다."""
        pos_high = _make_position(symbol="005930")
        pos_dip = _make_position(symbol="000660")
        self.manager._positions["005930"] = pos_high
        self.manager._positions["000660"] = pos_dip
        self.manager._last_tick_monotonic = time.monotonic() - 300

        async def _rest(symbol: str):
            return {"output": {"stck_prpr": "105" if symbol == "005930" else "98"}}

        sell = AsyncMock()
        with patch("backend.services.engine.position_manager.get_setting", side_effect=_settings()), \
             patch("backend.services.kis.domestic.service.get_current_price", side_effect=_rest), \
             patch("backend.services.engine.order_executor.order_executor.execute_sell", sell), \
             patch("backend.services.engine.position_manager._upsert_stop_state"), \
             patch("backend.services.engine.position_manager._now_kst", return_value=_KST_10AM):
            result = await self.manager.check_exits_via_rest()

        sell.assert_not_awaited()
        self.assertEqual(result["checked"], 2)
        self.assertEqual(result["triggered"], [])
        # on_tick과 동일하게 peak(MFE)·trough(MAE)가 갱신되어야 한다
        self.assertEqual(pos_high["highest_price_since_entry"], 105.0)
        self.assertEqual(pos_dip["trough_price"], 98.0)

    async def test_returns_immediately_when_no_positions(self) -> None:
        """보유 포지션 0이면 설정/REST 조회 없이 즉시 반환한다."""
        rest = AsyncMock()
        with patch("backend.services.kis.domestic.service.get_current_price", rest), \
             patch("backend.services.engine.position_manager.get_setting", side_effect=_settings()):
            result = await self.manager.check_exits_via_rest()

        self.assertEqual(result, {"ok": True, "checked": 0})
        rest.assert_not_awaited()

    async def test_disabled_setting_is_noop(self) -> None:
        """risk.stop_loss_backup_enabled=False 면 no-op."""
        self.manager._positions["005930"] = _make_position()
        self.manager._last_tick_monotonic = time.monotonic() - 300

        rest = AsyncMock()
        with patch("backend.services.engine.position_manager.get_setting", side_effect=_settings(enabled=False)), \
             patch("backend.services.kis.domestic.service.get_current_price", rest):
            result = await self.manager.check_exits_via_rest()

        self.assertTrue(result["ok"])
        self.assertEqual(result.get("skipped"), "disabled")
        rest.assert_not_awaited()

    async def test_one_symbol_rest_error_does_not_block_others(self) -> None:
        """심볼 1개 REST 조회 예외 시 해당 심볼만 skip 하고 나머지는 계속 검사한다."""
        self.manager._positions["005930"] = _make_position(symbol="005930")
        self.manager._positions["000660"] = _make_position(symbol="000660")
        self.manager._last_tick_monotonic = time.monotonic() - 300

        async def _rest(symbol: str):
            if symbol == "005930":
                raise RuntimeError("rest down")
            return {"output": {"stck_prpr": "96"}}

        sell = AsyncMock(return_value={"ok": True})
        with patch("backend.services.engine.position_manager.get_setting", side_effect=_settings()), \
             patch("backend.services.kis.domestic.service.get_current_price", side_effect=_rest), \
             patch("backend.services.engine.order_executor.order_executor.execute_sell", sell), \
             patch("backend.services.engine.position_manager._upsert_stop_state"), \
             patch("backend.services.engine.position_manager._now_kst", return_value=_KST_10AM):
            result = await self.manager.check_exits_via_rest()

        sell.assert_awaited_once_with(symbol="000660", qty=5, price=0, reason="INITIAL_STOP_LOSS")
        self.assertEqual(result["errors"], ["005930"])
        self.assertEqual(result["triggered"], ["000660"])

    async def test_on_tick_refreshes_last_tick_monotonic(self) -> None:
        """on_tick 진입 시 _last_tick_monotonic 이 갱신되어야 WS 생존 판정이 가능하다."""
        before = time.monotonic()
        await self.manager.on_tick({"symbol": "999999", "price": "100"})
        self.assertIsNotNone(self.manager._last_tick_monotonic)
        self.assertGreaterEqual(self.manager._last_tick_monotonic, before)


if __name__ == "__main__":
    unittest.main()
