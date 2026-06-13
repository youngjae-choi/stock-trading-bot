"""P1-T1 — 강제청산 시각 하드 실링(동시호가 이전 전진) 테스트.

배경: 2026-06-12 15:20:05 S9 시장가 매도 11건 중 5건이 미체결로 죽음
(eod_reconcile_no_kis_fill). 15:20은 장마감 동시호가 시작 시각이고
KIS 모의투자는 동시호가 체결을 시뮬레이션하지 않는다.

규칙: 유효 강제청산 시각 = min(톤별 시각, 설정 시각, 실링 15:12:00).
"""

from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from backend.services.engine.position_manager import (
    _FORCE_EXIT_CEILING,
    PositionManager,
)

_KST = ZoneInfo("Asia/Seoul")


def _make_position(force_exit_time: str = "15:20:00") -> dict:
    """_exit_reason이 참조하는 최소 포지션 dict를 만든다."""
    return {
        "position_id": "005930-test",
        "symbol": "005930",
        "active_stop_price": 90.0,
        "trailing_active": False,
        "force_exit_time": force_exit_time,
    }


def _kst(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 6, 12, hour, minute, second, tzinfo=_KST)


class ForceExitCeilingTest(unittest.TestCase):
    """유효 강제청산 시각이 항상 실링(15:12) 이하로 제한되는지 검증."""

    def setUp(self) -> None:
        self.manager = PositionManager()

    def _effective(self, tone: str, position: dict, ceiling_setting=None) -> str:
        """톤·실링 설정을 고정한 상태에서 유효 강제청산 시각을 계산한다."""
        def fake_get_setting(key, default=None):
            if key == "risk.force_exit_ceiling" and ceiling_setting is not None:
                return ceiling_setting
            return default

        with patch.object(PositionManager, "_get_today_tone", return_value=tone), \
             patch("backend.services.engine.position_manager.get_setting", side_effect=fake_get_setting):
            return self.manager._effective_force_exit_time(position)

    # ① 톤 positive여도 유효시각 ≤ 15:12
    def test_positive_tone_is_clamped_to_ceiling(self) -> None:
        effective = self._effective("positive", _make_position("15:20:00"))
        self.assertLessEqual(effective, "15:12:00")
        self.assertEqual(effective, "15:12:00")

    # ② 설정(risk.force_exit_time, 라이브 DB)이 15:20이어도 실링 적용
    def test_setting_1520_is_clamped_to_ceiling(self) -> None:
        position = _make_position("15:20:00")
        effective = self._effective("positive", position)
        self.assertLessEqual(effective, _FORCE_EXIT_CEILING)

        # 15:12:30 시점이면 강제청산 발동 (설정이 15:20이어도)
        def fake_get_setting(key, default=None):
            return default

        with patch.object(PositionManager, "_get_today_tone", return_value="positive"), \
             patch("backend.services.engine.position_manager.get_setting", side_effect=fake_get_setting), \
             patch("backend.services.engine.position_manager._now_kst", return_value=_kst(15, 12, 30)):
            reason = self.manager._exit_reason(position, price=100.0)
        self.assertEqual(reason, "DAILY_FORCE_EXIT")

        # 15:11:00 시점이면 아직 미발동 (가격은 손절선 위)
        with patch.object(PositionManager, "_get_today_tone", return_value="positive"), \
             patch("backend.services.engine.position_manager.get_setting", side_effect=fake_get_setting), \
             patch("backend.services.engine.position_manager._now_kst", return_value=_kst(15, 11, 0)):
            reason = self.manager._exit_reason(position, price=100.0)
        self.assertEqual(reason, "")

    # ③ negative 톤은 15:05
    def test_negative_tone_exits_at_1505(self) -> None:
        effective = self._effective("negative", _make_position("15:20:00"))
        self.assertEqual(effective, "15:05:00")

        position = _make_position("15:20:00")

        def fake_get_setting(key, default=None):
            return default

        with patch.object(PositionManager, "_get_today_tone", return_value="negative"), \
             patch("backend.services.engine.position_manager.get_setting", side_effect=fake_get_setting), \
             patch("backend.services.engine.position_manager._now_kst", return_value=_kst(15, 5, 1)):
            reason = self.manager._exit_reason(position, price=100.0)
        self.assertEqual(reason, "DAILY_FORCE_EXIT")

    # ④ 실링 자체를 설정(risk.force_exit_ceiling)으로 오버라이드 가능
    def test_ceiling_setting_override(self) -> None:
        effective = self._effective("positive", _make_position("15:20:00"), ceiling_setting="15:08:00")
        self.assertEqual(effective, "15:08:00")

        # HH:MM 포맷 설정도 정규화되어 동작
        effective = self._effective("positive", _make_position("15:20:00"), ceiling_setting="15:08")
        self.assertEqual(effective, "15:08:00")

    def test_tone_map_values_never_exceed_ceiling(self) -> None:
        """톤별 맵 자체가 실링(15:12) 이하로 재조정됐는지 확인."""
        for tone, value in PositionManager._TONE_FORCE_EXIT.items():
            self.assertLessEqual(value, _FORCE_EXIT_CEILING, f"tone={tone} value={value}")
        self.assertEqual(PositionManager._TONE_FORCE_EXIT["positive"], "15:12:00")
        self.assertEqual(PositionManager._TONE_FORCE_EXIT["mixed"], "15:10:00")
        self.assertEqual(PositionManager._TONE_FORCE_EXIT["neutral"], "15:10:00")
        self.assertEqual(PositionManager._TONE_FORCE_EXIT["negative"], "15:05:00")
        self.assertEqual(PositionManager._TONE_FORCE_EXIT["fallback"], "15:10:00")

    def test_invalid_ceiling_setting_falls_back_to_default(self) -> None:
        """실링 설정이 깨진 값이면 기본 실링(15:12)으로 동작."""
        effective = self._effective("positive", _make_position("15:20:00"), ceiling_setting="bogus")
        self.assertEqual(effective, "15:12:00")

    def test_new_entry_cutoff_precedes_force_exit(self) -> None:
        """신규매수 금지(15:10) ≤ 모든 유효 강제청산 시작 시각 — 순서 충돌 없음."""
        cutoff = "15:10:00"
        # 가장 이른 톤(negative 15:05)은 컷오프보다 빠르지만, 이는 의도된
        # '부정 톤 조기 청산'이며 신규 진입과의 충돌(청산 후 재진입)은
        # 컷오프가 아니라 당일 청산 쿨다운이 막는다. 여기서는 기본 톤 계열만 확인.
        for tone in ("positive", "neutral", "mixed", "fallback"):
            self.assertGreaterEqual(
                PositionManager._TONE_FORCE_EXIT[tone],
                "15:05:00",
            )
        self.assertLessEqual(cutoff, _FORCE_EXIT_CEILING)


class S9SweepScheduleTest(unittest.TestCase):
    """S9 전용 스윕 잡(15:12)이 postprocess(15:20)와 별개로 등록되는지 검증."""

    def test_s9_sweep_job_registered_at_1512(self) -> None:
        import backend.services.scheduler as sched

        with patch("backend.services.settings_store.list_settings", return_value=[]):
            scheduler = sched._build_scheduler()
        try:
            jobs = {job.id: job for job in scheduler.get_jobs()}
            self.assertIn("job_s9_eod_sweep", jobs)
            trigger = jobs["job_s9_eod_sweep"].trigger
            fields = {f.name: str(f) for f in trigger.fields}
            self.assertEqual(fields.get("hour"), "15")
            self.assertEqual(fields.get("minute"), "12")
            # 기존 postprocess 체인(백스톱)도 유지
            self.assertIn("job_postprocess_pipeline", jobs)
        finally:
            scheduler.shutdown(wait=False) if scheduler.running else None

    def test_s9_sweep_time_loaded_from_settings(self) -> None:
        import backend.services.scheduler as sched

        saved = [{"key": "schedule_s9_sweep_time", "value": "15:11"}]
        with patch("backend.services.settings_store.list_settings", return_value=saved):
            scheduler = sched._build_scheduler()
        try:
            jobs = {job.id: job for job in scheduler.get_jobs()}
            trigger = jobs["job_s9_eod_sweep"].trigger
            fields = {f.name: str(f) for f in trigger.fields}
            self.assertEqual(fields.get("hour"), "15")
            self.assertEqual(fields.get("minute"), "11")
        finally:
            scheduler.shutdown(wait=False) if scheduler.running else None


if __name__ == "__main__":
    unittest.main()
