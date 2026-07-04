"""Phase 1 스케일아웃 수확(scale-out harvest) 회귀 테스트 — S8 PositionManager.

PM 목표(하루 +2% 확정 + 트레일링 상승 보너스)를 스케일아웃으로 구현한다:
+목표수익률 도달 시 물량 일부를 확정 매도하고 잔량을 트레일링 러너로 전환한다.
harvest_mode OFF면 기존 탐색모드 동작(익절 없음)을 100% 보존한다.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from backend.services.engine.position_manager import PositionManager


def _make_position(qty: int = 100, entry: float = 100.0) -> dict:
    return {
        "position_id": "005930-test",
        "symbol": "005930",
        "name": "삼성전자",
        "qty": qty,
        "entry_price": entry,
        "entry_time": "2026-07-04T09:00:00+09:00",
        "entry_ts": 0.0,
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
        "harvested": False,
    }


def _settings(overrides: dict | None = None):
    base = {
        "engine.harvest_mode": True,
        "engine.scaleout_ratio": 0.6,
        "engine.scaleout_target_rate": 0.02,
    }
    if overrides:
        base.update(overrides)

    def _get(key, default=None):
        return base.get(key, default)

    return _get


class ScaleoutHarvestTest(unittest.IsolatedAsyncioTestCase):
    async def _run(self, position, price, settings_over=None, sell_ok=True):
        mgr = PositionManager()
        mgr._positions[position["symbol"]] = position
        sell = AsyncMock(return_value={"ok": sell_ok, "symbol": position["symbol"]})
        with patch("backend.services.engine.position_manager.get_setting", side_effect=_settings(settings_over)), \
             patch("backend.services.engine.position_manager._upsert_stop_state"), \
             patch("backend.services.engine.order_executor.order_executor.execute_sell", sell):
            reason = await mgr._process_price(position, price)
        return mgr, sell, reason

    async def test_partial_scaleout_at_target(self):
        """+2% 도달 시 60%(60주) 확정 매도, 잔량 40주는 트레일링 러너로 전환."""
        pos = _make_position(qty=100, entry=100.0)
        mgr, sell, reason = await self._run(pos, 102.0)  # +2%
        sell.assert_awaited_once()
        kwargs = sell.call_args.kwargs
        self.assertEqual(kwargs["qty"], 60)
        self.assertEqual(kwargs["reason"], "take_profit_scaleout")
        self.assertEqual(reason, "")  # 부분 확정 — 포지션 계속 관리
        self.assertEqual(pos["qty"], 40)
        self.assertTrue(pos["harvested"])
        self.assertTrue(pos["trailing_active"])
        self.assertAlmostEqual(pos["active_stop_price"], 98.94, places=2)  # 102*0.97

    async def test_no_scaleout_below_target(self):
        """+2% 미달(+1%)이면 스케일아웃 없음."""
        pos = _make_position(qty=100, entry=100.0)
        _, sell, reason = await self._run(pos, 101.0)
        sell.assert_not_awaited()
        self.assertEqual(pos["qty"], 100)
        self.assertFalse(pos["harvested"])
        self.assertEqual(reason, "")

    async def test_scaleout_once_only(self):
        """스케일아웃은 포지션당 1회 — 이후 상승 틱에 재확정하지 않는다."""
        pos = _make_position(qty=100, entry=100.0)
        mgr, sell, _ = await self._run(pos, 102.0)
        sell.assert_awaited_once()
        sell2 = AsyncMock(return_value={"ok": True})
        with patch("backend.services.engine.position_manager.get_setting", side_effect=_settings()), \
             patch("backend.services.engine.position_manager._upsert_stop_state"), \
             patch("backend.services.engine.order_executor.order_executor.execute_sell", sell2):
            await mgr._process_price(pos, 103.0)
        sell2.assert_not_awaited()

    async def test_harvest_mode_off_preserves_old_behavior(self):
        """harvest_mode OFF면 +10%여도 익절하지 않는다(후퇴 안전)."""
        pos = _make_position(qty=100, entry=100.0)
        _, sell, reason = await self._run(pos, 110.0, settings_over={"engine.harvest_mode": False})
        sell.assert_not_awaited()
        self.assertFalse(pos["harvested"])
        self.assertEqual(pos["qty"], 100)
        self.assertEqual(reason, "")

    async def test_full_exit_when_ratio_one(self):
        """scaleout_ratio=1.0이면 전량 확정 매도 + 포지션 제거."""
        pos = _make_position(qty=100, entry=100.0)
        mgr, sell, reason = await self._run(pos, 102.0, settings_over={"engine.scaleout_ratio": 1.0})
        sell.assert_awaited_once()
        self.assertEqual(sell.call_args.kwargs["qty"], 100)
        self.assertEqual(reason, "take_profit_scaleout")
        self.assertNotIn("005930", mgr._positions)

    async def test_single_share_not_scaled(self):
        """1주 포지션은 부분 확정 불가 — 손절/트레일링/EOD에 맡긴다."""
        pos = _make_position(qty=1, entry=100.0)
        _, sell, reason = await self._run(pos, 102.0)
        sell.assert_not_awaited()
        self.assertEqual(pos["qty"], 1)
        self.assertEqual(reason, "")

    async def test_sell_failure_reverts_harvested(self):
        """확정 매도가 실패하면 harvested·qty를 원복해 다음 틱에 재시도 가능."""
        pos = _make_position(qty=100, entry=100.0)
        _, sell, reason = await self._run(pos, 102.0, sell_ok=False)
        sell.assert_awaited_once()
        self.assertFalse(pos["harvested"])
        self.assertEqual(pos["qty"], 100)
        self.assertEqual(reason, "")

    async def test_stop_loss_takes_priority_over_scaleout(self):
        """풀청산 사유(손절)가 있으면 스케일아웃보다 우선 — 전량 매도된다."""
        pos = _make_position(qty=100, entry=100.0)
        pos["active_stop_price"] = 103.0  # 현재가보다 높은 손절선(이탈 상태 강제)
        _, sell, reason = await self._run(pos, 102.0)
        # 손절 우선: 전량(100) 매도, 사유는 스케일아웃이 아니어야 한다
        sell.assert_awaited_once()
        self.assertEqual(sell.call_args.kwargs["qty"], 100)
        self.assertNotEqual(sell.call_args.kwargs["reason"], "take_profit_scaleout")


if __name__ == "__main__":
    unittest.main()
