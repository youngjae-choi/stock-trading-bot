"""통합 시나리오 — 폭락장 방어 + 인버스 1x 플레이북 (Phase 2·3 완료 기준 검증).

시나리오 A (야간 급락 → 개장 방어): 봇은 EOD 전량청산으로 flat 시작.
  ① flash crash 감지 → 방어 모드 활성화
  ② 일반 종목 신규진입 차단 (게이트 + preflight 이중)
  ③ 인버스 1x 플레이북만 진입 허용
  ④ 인버스 포지션이 KOSPI -3.5% 하락을 수익으로 전환:
     방어 레짐 스케일아웃(+1.5%에서 80% 확정) + 잔량 트레일링 러너
  ⑤ 실현손익 합계 ≥ 당일 시작 계좌 잔고(1억)의 +0.5% — PM 목표(예수금 대비)

시나리오 B (장중 급락, 보유 중): 손절이 종목당 손실을 레짐 손절선 부근으로 제한.

주의: 이 시뮬레이션은 '엔진 로직이 폭락장에서 +0.5% 경로를 실행할 수 있다'를
검증한다. 실제 수익은 시장 조건(인버스 유동성·체결)에 의존한다.
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from backend.config import settings

_KST = ZoneInfo("Asia/Seoul")
SOD_EQUITY = 100_000_000  # 당일 시작 계좌 잔고(예수금) 1억


def _today() -> str:
    return datetime.now(_KST).strftime("%Y-%m-%d")


def _risk_off_rule() -> dict:
    """risk_off 레짐 SET 수준의 방어 규칙 (손절 -1.2%, 트레일링 1%)."""
    return {
        "profile_assigned": "MID_VOL",
        "initial_stop_loss": -0.012,
        "trailing_activate_profit": 0.015,
        "trailing_stop_rate": 0.01,
        "max_holding_minutes": 300,
        "force_exit_time": "15:20:00",
    }


class _SellRecorder:
    """execute_sell 대역 — 호출 시점의 시세로 실현손익을 계산한다."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self._current_price = 0.0

    def set_price(self, price: float) -> None:
        self._current_price = price

    async def __call__(self, *, symbol: str, qty: int, price: float = 0,
                       reason: str = "", name: str = "", partial: bool = False):
        self.calls.append({
            "symbol": symbol, "qty": int(qty), "fill_price": self._current_price,
            "reason": reason, "partial": partial,
        })
        return {"ok": True, "symbol": symbol, "qty": qty}


def test_crash_day_defense_and_inverse_playbook_yields_half_percent(monkeypatch):
    """시나리오 A — 방어 발동 → 일반 차단 → 인버스 수확 → 실현손익 ≥ +0.5%."""
    with tempfile.TemporaryDirectory() as tmp_dir, \
         patch.object(settings, "APP_DB_PATH", tmp_dir + "/crash.sqlite3"):
        from backend.services.db import initialize_database
        initialize_database()

        import backend.services.engine.decision_engine as de
        import backend.services.engine.intraday_regime_monitor as irm
        import backend.services.engine.order_preflight as pf
        import backend.services.regime_set_service as rss
        from backend.services.engine.position_manager import PositionManager

        today = _today()

        # ① flash crash 감지 → 방어 모드 (실제 활성화 함수 사용, 설정은 tmp DB 시드값)
        assert irm._flash_crash_detected(-3.5, 34.0) is True
        irm._activate_flash_crash_defense(today, -3.5, 34.0)
        assert irm.is_flash_crash_defense_active(today) is True

        # ② 일반 종목 진입 차단 — 게이트(신호)와 preflight(주문) 이중 방어
        gate_reason = de._entry_gate_block_reason("005930", 0.85, name="삼성전자")
        assert "flash_crash_defense" in gate_reason

        pre_regular = pf.run_preflight(
            signal={"id": "s1", "symbol": "005930", "name": "삼성전자", "trigger_price": 50000},
            final_rule=_risk_off_rule(),
        )
        assert pre_regular["checks"]["flash_crash_defense"] == pf.PREFLIGHT_BLOCK

        # ③ 인버스 1x 플레이북은 통과
        assert de._entry_gate_block_reason("114800", 0.85, name="KODEX 인버스") == ""
        pre_inverse = pf.run_preflight(
            signal={"id": "s2", "symbol": "114800", "name": "KODEX 인버스", "trigger_price": 10000},
            final_rule=_risk_off_rule(),
        )
        assert pre_inverse["checks"]["flash_crash_defense"] == pf.PREFLIGHT_OK

        # ④ 인버스 포지션 (플레이북 예산 30% = 3,000만) — KOSPI -3.5% 흐름을 탄다
        monkeypatch.setattr(
            rss, "get_today_application",
            lambda d: {"regime_label": "risk_off", "applied_settings": {"new_entry_allowed": False}},
        )
        import backend.services.engine.position_manager as pmod
        pmod._SCALEOUT_OVERRIDE_CACHE["at"] = 0.0  # 캐시 리셋 (risk_off 기본 0.015/0.8)

        mgr = PositionManager()
        sell = _SellRecorder()
        with patch("backend.services.engine.order_executor.order_executor.execute_sell", sell), \
             patch.object(PositionManager, "_account_daily_target_reached",
                          new=AsyncMock(return_value=False)):
            mgr.add_position(symbol="114800", name="KODEX 인버스", qty=3000,
                             entry_price=10000.0, final_rule=_risk_off_rule())
            pos = mgr._positions["114800"]

            async def _drive():
                # +1.5% — 방어 레짐 스케일아웃 발동선(전역 +2%보다 빠름)
                sell.set_price(10150.0)
                await mgr._process_price(pos, 10150.0)
                # 시장 추가 하락 → 인버스 고점 +3.5%
                sell.set_price(10350.0)
                await mgr._process_price(pos, 10350.0)
                # 고점 대비 1% 트레일링 이탈 → 러너 청산
                sell.set_price(10245.0)
                await mgr._process_price(pos, 10245.0)

            asyncio.run(_drive())

        # 스케일아웃(80% = 2,400주) + 트레일링 러너(600주) 두 번의 매도
        assert len(sell.calls) == 2
        harvest, runner = sell.calls
        assert harvest["reason"] == "take_profit_scaleout" and harvest["qty"] == 2400
        assert harvest["partial"] is True          # P0: 부분매도 — 포지션 보존
        assert runner["reason"] == "TRAILING_STOP" and runner["qty"] == 600

        # ⑤ 실현손익 ≥ 시작 잔고의 +0.5% (PM 목표: 예수금 대비)
        entry = 10000.0
        realized = sum((c["fill_price"] - entry) * c["qty"] for c in sell.calls)
        # (10150-10000)*2400 + (10245-10000)*600 = 360,000 + 147,000 = 507,000
        assert realized >= SOD_EQUITY * 0.005, f"realized={realized:,.0f}"


def test_crash_day_intraday_stop_bounds_losses(monkeypatch):
    """시나리오 B — 장중 급락 시 보유 롱은 초기 손절선 부근에서 전량 청산(손실 제한)."""
    with tempfile.TemporaryDirectory() as tmp_dir, \
         patch.object(settings, "APP_DB_PATH", tmp_dir + "/crash2.sqlite3"):
        from backend.services.db import initialize_database
        initialize_database()
        import backend.services.regime_set_service as rss
        from backend.services.engine.position_manager import PositionManager
        monkeypatch.setattr(rss, "get_today_application", lambda d: None)

        mgr = PositionManager()
        sell = _SellRecorder()
        with patch("backend.services.engine.order_executor.order_executor.execute_sell", sell):
            mgr.add_position(symbol="005930", name="삼성전자", qty=1000,
                             entry_price=10000.0, final_rule=_risk_off_rule())
            pos = mgr._positions["005930"]

            async def _drive():
                sell.set_price(9830.0)  # 갭 하락 — 손절선(9,880) 이탈
                await mgr._process_price(pos, 9830.0)

            asyncio.run(_drive())

        assert len(sell.calls) == 1
        exit_call = sell.calls[0]
        assert exit_call["reason"] == "INITIAL_STOP_LOSS"
        assert exit_call["qty"] == 1000            # 전량 청산 — 잔여 포지션 없음
        loss = (exit_call["fill_price"] - 10000.0) * exit_call["qty"]
        # 손실이 포지션의 -2% 이내로 제한 (손절 -1.2% + 갭 슬리피지 여유)
        assert loss >= -(10000.0 * 1000) * 0.02
