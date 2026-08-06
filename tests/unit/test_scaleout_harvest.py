"""Phase 1 스케일아웃 수확(scale-out harvest) 회귀 테스트 — S8 PositionManager.

PM 목표(하루 +2% 확정 + 트레일링 상승 보너스)를 스케일아웃으로 구현한다:
+목표수익률 도달 시 물량 일부를 확정 매도하고 잔량을 트레일링 러너로 전환한다.
harvest_mode OFF면 기존 탐색모드 동작(익절 없음)을 100% 보존한다.
"""

from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from backend.services.engine.position_manager import PositionManager

# 시각 독립 테스트: 장중(15:20 강제청산 이전)으로 시간을 고정한다.
# (실행 시각이 15:20 이후면 DAILY_FORCE_EXIT가, entry_ts=0이면 TIME_EXIT가 먼저 발동해
#  스케일아웃 경로를 못 타던 flaky 문제 해결 — _now_kst를 고정하고 진입을 '1분 전'으로 둔다.)
_FIXED_NOW = datetime(2026, 8, 6, 10, 0, 0, tzinfo=ZoneInfo("Asia/Seoul"))


def _make_position(qty: int = 100, entry: float = 100.0) -> dict:
    return {
        "position_id": "005930-test",
        "symbol": "005930",
        "name": "삼성전자",
        "qty": qty,
        "entry_price": entry,
        "entry_time": "2026-08-06T09:59:00+09:00",
        "entry_ts": _FIXED_NOW.timestamp() - 60.0,  # 1분 전 진입(TIME_EXIT 미발동)
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
    async def _run(self, position, price, settings_over=None, sell_ok=True, regime_override=None):
        mgr = PositionManager()
        mgr._positions[position["symbol"]] = position
        sell = AsyncMock(return_value={"ok": sell_ok, "symbol": position["symbol"]})
        with patch("backend.services.engine.position_manager._now_kst", return_value=_FIXED_NOW), \
             patch("backend.services.engine.position_manager.get_setting", side_effect=_settings(settings_over)), \
             patch("backend.services.engine.position_manager._upsert_stop_state"), \
             patch("backend.services.engine.position_manager._regime_scaleout_overrides", return_value=regime_override), \
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
        self.assertTrue(kwargs.get("partial"))  # P0: 부분매도 플래그 — 포지션 제거 방지
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
        with patch("backend.services.engine.position_manager._now_kst", return_value=_FIXED_NOW), \
             patch("backend.services.engine.position_manager.get_setting", side_effect=_settings()), \
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
        self.assertFalse(sell.call_args.kwargs.get("partial"))  # 전량 청산은 partial 아님
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

    # ── Gap B: 계좌 단위 일일 목표(+2%, 총자산 대비) 도달 시 부분 수확 강화 ──

    async def test_scaleout_ratio_boosted_after_account_target(self):
        """계좌 일일 목표(+2%) 도달 후에는 확정 비중 0.8로 상향 — 80주 확정, 잔량 20주 러너."""
        pos = _make_position(qty=100, entry=100.0)
        with patch.object(PositionManager, "_account_daily_target_reached",
                          new=AsyncMock(return_value=True)):
            mgr, sell, reason = await self._run(pos, 102.0)
        sell.assert_awaited_once()
        self.assertEqual(sell.call_args.kwargs["qty"], 80)   # 0.6 → 0.8 상향
        self.assertEqual(pos["qty"], 20)                     # 잔량 20주 트레일링 러너
        self.assertTrue(pos["trailing_active"])
        self.assertEqual(reason, "")

    async def test_scaleout_ratio_normal_when_target_not_reached(self):
        """계좌 목표 미도달이면 기본 비중(0.6) 유지 — 60주 확정."""
        pos = _make_position(qty=100, entry=100.0)
        with patch.object(PositionManager, "_account_daily_target_reached",
                          new=AsyncMock(return_value=False)):
            _, sell, _ = await self._run(pos, 102.0)
        self.assertEqual(sell.call_args.kwargs["qty"], 60)
        self.assertEqual(pos["qty"], 40)

    async def test_account_target_reached_latches_after_first_hit(self):
        """총자산이 baseline 대비 +2% 도달 → True, 이후 재확인은 캐시 잔고를 다시 부르지 않는다(래치)."""
        mgr = PositionManager()
        bal = AsyncMock(return_value={"output2": [{"tot_evlu_amt": "102000000"}]})
        with patch("backend.services.engine.position_manager.get_setting", side_effect=_settings()), \
             patch("backend.services.engine.daily_capital.get_total_eval_baseline", return_value=100000000), \
             patch("backend.services.engine.order_executor.order_executor._get_cached_balance", new=bal):
            self.assertTrue(await mgr._account_daily_target_reached())
            self.assertTrue(await mgr._account_daily_target_reached())
        self.assertEqual(bal.await_count, 1)  # 래치되어 2회차는 잔고 재조회 없음

    async def test_account_target_not_reached_does_not_latch(self):
        """미도달(+1%)이면 False이고 래치하지 않아 매번 재확인한다."""
        mgr = PositionManager()
        bal = AsyncMock(return_value={"output2": [{"tot_evlu_amt": "101000000"}]})
        with patch("backend.services.engine.position_manager.get_setting", side_effect=_settings()), \
             patch("backend.services.engine.daily_capital.get_total_eval_baseline", return_value=100000000), \
             patch("backend.services.engine.order_executor.order_executor._get_cached_balance", new=bal):
            self.assertFalse(await mgr._account_daily_target_reached())
            self.assertFalse(await mgr._account_daily_target_reached())
        self.assertEqual(bal.await_count, 2)  # 미도달은 래치 안 함 → 재확인

    async def test_account_target_false_when_no_baseline(self):
        """baseline 미캡처(장전/비거래일)면 KIS 잔고 조회 전에 False로 빠진다(안전)."""
        mgr = PositionManager()
        bal = AsyncMock(return_value={"output2": [{"tot_evlu_amt": "999999999"}]})
        with patch("backend.services.engine.position_manager.get_setting", side_effect=_settings()), \
             patch("backend.services.engine.daily_capital.get_total_eval_baseline", return_value=None), \
             patch("backend.services.engine.order_executor.order_executor._get_cached_balance", new=bal):
            self.assertFalse(await mgr._account_daily_target_reached())
        bal.assert_not_awaited()  # baseline 없으면 잔고 조회 자체를 하지 않는다


if __name__ == "__main__":
    unittest.main()
