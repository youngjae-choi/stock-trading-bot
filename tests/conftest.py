"""전역 테스트 픽스처.

(A) KIS 실보유 상한 clamp(order_executor._cached_kis_held_qty)가 테스트 중 실제 KIS
get_balance를 호출하지 않도록 기본 무력화한다. 목적:
  1) 서버 가동 중 KIS 토큰 경합(1분 1회 발급 제약) 방지 — 별도 프로세스 KIS 호출 금지 원칙.
  2) 결정성 — 매도 경로 테스트가 KIS 응답에 흔들리지 않게 한다.
clamp 자체를 검증하는 테스트(test_sell_kis_clamp)는 _cached_kis_held_qty를 실제 구현으로
복원해(_REAL_CACHED_HELD) 사용한다. `_cached_kis_held_qty`는 clamp에서만 참조되므로
이 스텁의 부수효과는 없다.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _stub_kis_held_qty_for_clamp(monkeypatch):
    import backend.services.engine.order_executor as oe

    async def _noop_held(_symbol):
        return 10 ** 9  # 충분히 큰 실보유 → clamp 무개입(기본)

    monkeypatch.setattr(oe, "_cached_kis_held_qty", _noop_held, raising=False)


@pytest.fixture(autouse=True)
def _stub_shadow_sensing_live_db_write(monkeypatch):
    """(B) check_intraday_regime → _persist_and_shadow_sensing이 **라이브 DB**에 가짜 KOSPI 시계열·
    전환상태·매수중단 래치를 쓰지 않게 막는다(2026-10-01 사고: pytest가 장전 07:18에
    regime.current_transition=down_transition·entry_suspended_at을 라이브에 기록).
    이 함수를 직접 검증하는 테스트는 없다 — 필요하면 격리 tmp DB에서 원본을 복원해 쓴다.
    """
    import backend.services.engine.intraday_regime_monitor as irm

    monkeypatch.setattr(irm, "_persist_and_shadow_sensing", lambda *a, **k: None, raising=False)


@pytest.fixture(autouse=True)
def _neutralize_live_timing_gates(monkeypatch):
    """(C) 되찾기 매수 게이트·본전보호는 **라이브 DB 설정**(enforce)을 직접 읽는다. 기존 테스트가
    라이브 설정에 따라 흔들리지 않게 기본 무력화(통과·무영향). 전용 테스트(test_timing_gates)는
    import 시점에 잡은 원본 함수를 복원해 검증한다.
    """
    import backend.services.engine.decision_engine as de
    import backend.services.engine.position_manager as pm

    monkeypatch.setattr(de, "_reclaim_gate", lambda *a, **k: (True, "test-bypass"), raising=False)
    monkeypatch.setattr(pm, "_breakeven_stop_price", lambda *a, **k: 0.0, raising=False)
