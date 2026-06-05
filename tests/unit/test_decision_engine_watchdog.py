"""매수 엔진 자동복구 워치독 안전 로직 테스트.

워치독은 "활성이어야 하는데 꺼진" 엔진만 재활성화하고, 다음은 절대 건드리지 않는다:
- should_be_active=False (EOD 이후/미개시)
- 수동 긴급정지 활성 (운영자 의도 존중)
- 이미 활성 (무동작)
"""

import unittest
from unittest.mock import AsyncMock, patch

from backend.services import scheduler


class DecisionEngineWatchdogTest(unittest.IsolatedAsyncioTestCase):
    """job_decision_engine_watchdog 의 재활성화 게이트를 검증한다."""

    async def _run(self, *, should_be_active: bool, halt: bool, is_active: bool) -> bool:
        """주어진 상태로 워치독을 실행하고 재활성화(job_decision_engine_start) 호출 여부를 반환."""
        fake_engine = type("E", (), {"is_active": staticmethod(lambda: is_active)})
        # 늦은-플랜 자가활성화 분기(별도 test_late_plan_activation.py에서 검증)는
        # 여기서 발동하지 않도록 안전 기본값으로 mock — 본 파일은 should_be_active 경로만 검증.
        with patch.object(scheduler, "_get_engine_should_be_active", return_value=should_be_active), patch.object(
            scheduler, "_is_emergency_halt_active", return_value=halt
        ), patch.object(scheduler, "job_decision_engine_start", new=AsyncMock()) as start_mock, patch.object(
            scheduler, "_within_late_plan_window", return_value=False
        ), patch.object(scheduler, "_s6_activated_today", return_value=False), patch.object(
            scheduler, "_get_active_daily_plan_for_s6", return_value=None
        ), patch(
            "backend.services.engine.decision_engine.decision_engine", fake_engine
        ):
            await scheduler.job_decision_engine_watchdog()
        return start_mock.await_count > 0

    async def test_reactivates_when_should_be_active_and_inactive_and_not_halted(self) -> None:
        """켜져 있어야 하는데 꺼졌고 긴급정지가 아니면 재활성화한다."""
        self.assertTrue(await self._run(should_be_active=True, halt=False, is_active=False))

    async def test_skips_when_should_be_active_false(self) -> None:
        """EOD 이후(should_be_active=False)에는 재활성화하지 않는다."""
        self.assertFalse(await self._run(should_be_active=False, halt=False, is_active=False))

    async def test_respects_manual_emergency_halt(self) -> None:
        """수동 긴급정지 중에는 재활성화하지 않는다."""
        self.assertFalse(await self._run(should_be_active=True, halt=True, is_active=False))

    async def test_noop_when_already_active(self) -> None:
        """이미 활성이면 아무 것도 하지 않는다."""
        self.assertFalse(await self._run(should_be_active=True, halt=False, is_active=True))


if __name__ == "__main__":
    unittest.main()
