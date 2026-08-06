"""index-board 장중 브리핑 폴링 잡(job_intraday_briefing_poll) 테스트.

핵심: generatedAt이 바뀔 때만 regime 재평가(run_market_tone_analysis) 호출.
- 같은 generatedAt 반복 폴링 → 재호출 안 함(중복 방지)
- 새 generatedAt → 재호출
- 브리핑 없음 → no-op, 예외 없음
- 비거래일 → 스킵
"""
import unittest
from unittest.mock import AsyncMock, patch

from backend.services import scheduler


class IntradayBriefingPollTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        # 모듈 레벨 last-seen 초기화(테스트 격리)
        scheduler._LAST_INTRADAY_BRIEFING["generated_at"] = None

    async def _run(self, scrape_return, *, non_trading=False) -> AsyncMock:
        # 폴링 잡은 snapshot_briefing_to_db(스크랩+DB저장)를 호출하고 그 intraday로 regime 재평가한다.
        snap_return = {"ok": bool(scrape_return), "morning": None, "evening": None, "intraday": scrape_return}
        snap_mock = AsyncMock(return_value=snap_return)
        run_mock = AsyncMock()
        with patch.object(scheduler, "_non_trading_day_today", return_value=("휴장" if non_trading else None)), \
             patch("backend.services.engine.index_board_scraper.snapshot_briefing_to_db", snap_mock), \
             patch.object(scheduler, "run_market_tone_analysis", run_mock):
            await scheduler.job_intraday_briefing_poll()
        return run_mock

    async def test_new_briefing_triggers_reeval(self) -> None:
        run = await self._run({"text": "장중", "generated_at": "2026-06-26T02:31:00Z"})
        self.assertEqual(run.await_count, 1)
        self.assertEqual(scheduler._LAST_INTRADAY_BRIEFING["generated_at"], "2026-06-26T02:31:00Z")

    async def test_same_generated_at_no_reeval(self) -> None:
        scheduler._LAST_INTRADAY_BRIEFING["generated_at"] = "2026-06-26T02:31:00Z"
        run = await self._run({"text": "장중", "generated_at": "2026-06-26T02:31:00Z"})
        self.assertEqual(run.await_count, 0)

    async def test_changed_generated_at_reeval(self) -> None:
        scheduler._LAST_INTRADAY_BRIEFING["generated_at"] = "2026-06-26T02:31:00Z"
        run = await self._run({"text": "장중2", "generated_at": "2026-06-26T03:10:00Z"})
        self.assertEqual(run.await_count, 1)
        self.assertEqual(scheduler._LAST_INTRADAY_BRIEFING["generated_at"], "2026-06-26T03:10:00Z")

    async def test_none_briefing_noop(self) -> None:
        run = await self._run(None)
        self.assertEqual(run.await_count, 0)
        self.assertIsNone(scheduler._LAST_INTRADAY_BRIEFING["generated_at"])

    async def test_empty_generated_at_noop(self) -> None:
        run = await self._run({"text": "x", "generated_at": ""})
        self.assertEqual(run.await_count, 0)

    async def test_non_trading_day_skips(self) -> None:
        run = await self._run({"text": "장중", "generated_at": "2026-06-26T02:31:00Z"}, non_trading=True)
        self.assertEqual(run.await_count, 0)


if __name__ == "__main__":
    unittest.main()
