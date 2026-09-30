"""매수·매도 타이밍 게이트 (2026-10-01, exit 재시뮬 검증).

① 되찾기(reclaim) 매수: 조건 통과 즉시 사지 않고 arm → -dip 추가 하락 → arm가 회복 시 매수.
② 본전 보호: 고점이 진입가+1% 이상 가면 손절선을 진입가+0.23%(왕복비용)로 상향, 사유 BREAKEVEN_STOP.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import backend.services.engine.decision_engine as de
import backend.services.engine.position_manager as pm
from backend.services.engine.decision_engine import _reclaim_gate as REAL_RECLAIM
from backend.services.engine.position_manager import _breakeven_stop_price as REAL_BE

KST = ZoneInfo("Asia/Seoul")
T0 = datetime(2026, 10, 1, 10, 0, 0, tzinfo=KST)


def _reclaim_env(monkeypatch, bars_low=None, **cfg):
    conf = {"engine.entry_reclaim_cutoff": "14:30", "engine.entry_reclaim_dip_pct": "0.2",
            "engine.entry_reclaim_window_min": "30", **cfg}
    monkeypatch.setattr(de, "_get_setting_str", lambda k, d: conf.get(k, d))
    monkeypatch.setattr(de, "_reclaim_bars_low", lambda *a: bars_low)
    de._RECLAIM_ARMS.clear()


def test_first_pass_arms_not_buys(monkeypatch):
    _reclaim_env(monkeypatch)
    ok, st = REAL_RECLAIM("A", 10000, T0)
    assert (ok, st) == (False, "armed") and "A" in de._RECLAIM_ARMS


def test_no_buy_without_dip(monkeypatch):
    _reclaim_env(monkeypatch)
    REAL_RECLAIM("A", 10000, T0)
    ok, st = REAL_RECLAIM("A", 10010, T0 + timedelta(minutes=1))  # 밀림 없이 위로 = 추격 아님, 대기
    assert not ok and st == "waiting_dip"


def test_dip_then_reclaim_buys(monkeypatch):
    _reclaim_env(monkeypatch)
    REAL_RECLAIM("A", 10000, T0)
    ok, st = REAL_RECLAIM("A", 9970, T0 + timedelta(minutes=2))   # -0.3% 밀림
    assert not ok and st.startswith("dipped")
    ok, _ = REAL_RECLAIM("A", 10000, T0 + timedelta(minutes=4))    # arm가 되찾음 → 매수
    assert ok and "A" not in de._RECLAIM_ARMS                       # arm 소비


def test_bar_low_counts_as_dip(monkeypatch):
    """게이트 쿨다운으로 틱이 안 들어온 구간의 하락도 저장 봉 저가로 인식."""
    _reclaim_env(monkeypatch, bars_low=9950.0)
    REAL_RECLAIM("A", 10000, T0)
    ok, _ = REAL_RECLAIM("A", 10000, T0 + timedelta(minutes=3))
    assert ok


def test_shallow_dip_not_enough(monkeypatch):
    _reclaim_env(monkeypatch)
    REAL_RECLAIM("A", 10000, T0)
    REAL_RECLAIM("A", 9990, T0 + timedelta(minutes=1))  # -0.1% < 0.2%
    ok, _ = REAL_RECLAIM("A", 10000, T0 + timedelta(minutes=2))
    assert not ok


def test_arm_expires_after_window(monkeypatch):
    _reclaim_env(monkeypatch)
    REAL_RECLAIM("A", 10000, T0)
    REAL_RECLAIM("A", 9950, T0 + timedelta(minutes=5))
    ok, st = REAL_RECLAIM("A", 10000, T0 + timedelta(minutes=31))  # 만료 → 재arm
    assert not ok and st == "armed"


def test_cutoff_blocks_and_clears(monkeypatch):
    _reclaim_env(monkeypatch)
    REAL_RECLAIM("A", 10000, T0)
    ok, st = REAL_RECLAIM("A", 10000, T0.replace(hour=14, minute=31))
    assert (ok, st) == (False, "cutoff") and "A" not in de._RECLAIM_ARMS


# ── 본전 보호 ──
def _be_env(monkeypatch, mode="enforce"):
    conf = {"engine.breakeven_mode": mode, "engine.breakeven_trigger_rate": 0.01,
            "engine.breakeven_lock_rate": 0.0023}
    import backend.services.settings_store as ss
    monkeypatch.setattr(ss, "get_setting", lambda k, d=None: conf.get(k, d))
    monkeypatch.setattr(pm, "_breakeven_stop_price", REAL_BE)


def test_breakeven_price_trigger(monkeypatch):
    _be_env(monkeypatch)
    assert REAL_BE(10000, 10099) == 0.0                      # +0.99% 미발동
    assert abs(REAL_BE(10000, 10100) - 10023) < 1e-6          # +1% 발동 → 본전+비용


def test_breakeven_off(monkeypatch):
    _be_env(monkeypatch, mode="off")
    assert REAL_BE(10000, 10500) == 0.0


def _position():
    return {"position_id": "p", "symbol": "A", "entry_price": 10000.0, "initial_stop_price": 9600.0,
            "active_stop_price": 9600.0, "highest_price_since_entry": 10000.0, "trailing_active": False,
            "trailing_stop_price": 9600.0, "trailing_activate_profit": 0.035, "trailing_stop_rate": 0.025,
            "force_exit_time": "23:59:00", "profile_assigned": "MID_VOL"}


def test_update_trailing_raises_stop_and_exit_reason(monkeypatch):
    _be_env(monkeypatch)
    monkeypatch.setattr(pm, "_upsert_stop_state", lambda *a, **k: None)
    mgr = pm.PositionManager()
    pos = _position()
    mgr._update_trailing(pos, 10150)                       # +1.5% 고점(트레일 발동 +3.5% 전)
    assert abs(pos["active_stop_price"] - 10023) < 1e-6 and not pos["trailing_active"]
    monkeypatch.setattr(mgr, "_effective_force_exit_time", lambda p: "23:59:59")
    assert mgr._exit_reason(pos, 10020) == "BREAKEVEN_STOP"
    assert mgr._exit_reason(pos, 10030) == ""


def test_initial_stop_label_unchanged_without_breakeven(monkeypatch):
    _be_env(monkeypatch)
    monkeypatch.setattr(pm, "_upsert_stop_state", lambda *a, **k: None)
    mgr = pm.PositionManager()
    pos = _position()
    mgr._update_trailing(pos, 10050)                        # +0.5% — 미발동
    monkeypatch.setattr(mgr, "_effective_force_exit_time", lambda p: "23:59:59")
    assert mgr._exit_reason(pos, 9590) == "INITIAL_STOP_LOSS"
