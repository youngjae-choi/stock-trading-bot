"""모멘텀 진입(실전) — 리더 돌파 감지 + 눌림게이트 우회 (2026-09-07).

momentum_backtest 발견(강세4 돌파=승률83%·순+1.36%, 전 레짐)의 실전 경로. 모멘텀은 mean-reversion
게이트(VWAP 눌림·시가대비·conviction)를 우회하되 안전게이트는 통과. 무손실 검증:
 ①_detect_breakout 감지 로직 ②_emit_signal momentum=True가 VWAP 추격차단 우회 ③disabled no-op.
"""
from __future__ import annotations

import asyncio
import tempfile

import pytest

from backend.services.engine.momentum_entry import _detect_breakout, run_momentum_entries


# ── 감지 로직 ─────────────────────────────────────────────────────────────────

def _bars(rows):
    return [{"bar_ts": t, "open": o, "high": h, "low": lo, "close": c, "volume": v} for (t, o, h, lo, c, v) in rows]


def test_detect_breakout_fires():
    bars = _bars([("090000", 100, 105, 99, 103, 10), ("093500", 103, 107, 103, 106, 50)])
    sig = _detect_breakout(bars, "093000", "093000", 4.0)
    assert sig is not None and sig[0] == "093500" and sig[3] == 6.0  # 시가대비 +6%


def test_detect_no_breakout_when_below_or_high():
    bars = _bars([("090000", 100, 108, 99, 103, 10), ("093500", 103, 106, 103, 105, 50)])  # OR고 108, 이후 최고 106<108
    assert _detect_breakout(bars, "093000", "093000", 0.0) is None


def test_detect_blocked_by_rs_min():
    bars = _bars([("090000", 100, 105, 99, 103, 10), ("093500", 103, 107, 103, 106, 50)])  # +6%
    assert _detect_breakout(bars, "093000", "093000", 8.0) is None  # +8% 요구 → 미달


def test_detect_requires_above_vwap():
    # 돌파는 했으나 종가가 VWAP 아래면 미발동
    bars = _bars([("090000", 100, 105, 99, 104, 1000), ("093500", 104, 106, 100, 101, 5)])  # vwap≈104, close101<vwap
    assert _detect_breakout(bars, "093000", "093000", 0.0) is None


# ── _emit_signal momentum 우회 (핵심 안전 검증) ───────────────────────────────

@pytest.fixture()
def engine_env(monkeypatch):
    from backend.config import settings as cfg
    from backend.services.db import initialize_database
    import backend.services.engine.decision_engine as de_mod
    import backend.services.engine.order_executor as oe_mod
    import backend.services.engine.technical_indicators as ti_mod

    monkeypatch.setattr(cfg, "APP_DB_PATH", tempfile.mktemp(suffix=".sqlite3"))
    initialize_database()

    async def _noop_exec(*a, **k):
        return {"ok": True}
    monkeypatch.setattr(oe_mod.order_executor, "execute_signal", _noop_exec)
    monkeypatch.setattr(ti_mod, "save_signal_indicators", lambda *a, **k: None)

    from datetime import datetime
    from zoneinfo import ZoneInfo
    monkeypatch.setattr(de_mod, "_now_kst",
                        lambda: datetime(2026, 8, 20, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")))
    # 게이트: 레버리지·confidence off, VWAP는 enforce로 활성(추격 차단 확인용)
    monkeypatch.setattr(de_mod, "get_setting", lambda k, d=None: {
        "engine.leverage_restriction_mode": "off",
        "engine.confidence_gate_mode": "off",
        "engine.entry_vwap_pullback_mode": "enforce",
        "engine.entry_change_from_open_mode": "off",
        "engine.conviction_gate_min": 0.0,
    }.get(k, d))
    monkeypatch.setattr(de_mod, "_entry_gate_block_reason", lambda *a, **k: "")

    eng = de_mod.DecisionEngine()
    monkeypatch.setattr(eng, "_record_exploration_tag", lambda *a, **k: None)
    eng._bar_engine.get_vwap = lambda s: 10000.0  # 실시간 VWAP 고정
    return de_mod, eng


def _signal_count(symbol):
    from backend.services.db import get_connection
    with get_connection() as c:
        try:
            return c.execute("SELECT COUNT(*) FROM trading_signals WHERE symbol=?", (symbol,)).fetchone()[0]
        except Exception:
            return 0


def test_normal_entry_blocked_by_vwap_chase(engine_env):
    de_mod, eng = engine_env
    # price 10000 = VWAP 정확히(=0% 이격) > 천장(-1) → 추격 차단(눌림전략)
    asyncio.run(eng._emit_signal("005930", {"name": "삼성전자", "confidence": 0.7}, 10000.0, {}))
    assert _signal_count("005930") == 0  # VWAP 추격 게이트가 차단


def test_momentum_entry_bypasses_vwap_chase(engine_env):
    de_mod, eng = engine_env
    # 같은 조건(VWAP 위)인데 momentum=True → 눌림게이트 우회 → 발행됨
    asyncio.run(eng._emit_signal("005930", {"name": "삼성전자", "confidence": 0.7}, 10000.0, {"momentum": True}))
    assert _signal_count("005930") == 1  # 모멘텀은 우회 → 강세 매수 신호 발행


# ── run_momentum_entries 토글 ─────────────────────────────────────────────────

def test_run_disabled_is_noop(monkeypatch):
    import backend.services.engine.momentum_entry as m
    r = asyncio.run(run_momentum_entries("2026-09-07", getter=lambda k, d=None: False if k == "momentum.enabled" else d))
    assert r["enabled"] is False and r["entered"] == 0
