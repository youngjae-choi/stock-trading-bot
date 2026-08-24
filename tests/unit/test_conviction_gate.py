"""④ 품질 게이트(conviction) — suitability sparse 대체. engine.conviction_gate_min 스위치.

conviction = resolve_conviction(regime, vwap_dist): 레짐점수×0.5 + 눌림점수×0.5.
gate_min=0(기본)이면 OFF(무영향), >0이면 그 미만 차단.
"""
import asyncio
import tempfile

import pytest

from backend.services.engine.strategy_playbook import resolve_conviction


# ── conviction 지표 자체 검증 (스케일·레짐차등) ──
def test_conviction_scale_by_regime():
    g = lambda k, d=None: d  # 코드기본(regime_weight 0.5, full -3.0, regime_scores 기본)
    # 깊은 눌림(-2.9%, 만점근처) — 레짐별
    on = resolve_conviction("risk_on", -2.9, getter=g)
    neu = resolve_conviction("neutral", -2.9, getter=g)
    off = resolve_conviction("risk_off", -2.9, getter=g)
    assert on > neu > off  # 좋은 레짐일수록 conviction↑
    # 추격(VWAP 위)은 눌림점수 0
    chase = resolve_conviction("risk_on", 1.0, getter=g)
    assert chase < on


# ── _emit_signal 게이트 동작 ──
@pytest.fixture()
def eng_env(monkeypatch):
    from backend.config import settings as cfg
    from backend.services.db import initialize_database
    import backend.services.engine.decision_engine as de
    import backend.services.engine.order_executor as oe
    import backend.services.engine.technical_indicators as ti
    from datetime import datetime
    from zoneinfo import ZoneInfo

    tmp = tempfile.mktemp(suffix=".sqlite3")
    monkeypatch.setattr(cfg, "APP_DB_PATH", tmp)
    initialize_database()

    async def _noop(*a, **k):
        return {"ok": True}
    monkeypatch.setattr(oe.order_executor, "execute_signal", _noop)
    monkeypatch.setattr(ti, "save_signal_indicators", lambda *a, **k: None)
    monkeypatch.setattr(de, "_now_kst",
                        lambda: datetime(2026, 8, 20, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")))
    eng = de.DecisionEngine()
    monkeypatch.setattr(eng, "_record_exploration_tag", lambda *a, **k: None)
    monkeypatch.setattr(eng, "_current_regime", lambda: "neutral")
    # VWAP 1030, price 1000 → vwap_dist -2.9%(깊은 눌림) → conviction≈0.74(neutral)
    monkeypatch.setattr(eng._bar_engine, "get_vwap", lambda s: 1030.0)
    return de, eng


def _count(sym):
    from backend.services.db import get_connection
    with get_connection() as c:
        try:
            return c.execute("SELECT COUNT(*) FROM trading_signals WHERE symbol=?", (sym,)).fetchone()[0]
        except Exception:
            return 0


def _emit(eng, sym="005930"):
    asyncio.run(eng._emit_signal(sym, {"name": "삼성전자", "confidence": 0.2}, 1000.0, {}))


def _settings(monkeypatch, de, conv_min):
    cfg = {"engine.conviction_gate_min": conv_min, "engine.leverage_restriction_mode": "off",
           "engine.entry_execute_start_time": "09:30", "engine.entry_vwap_pullback_mode": "off"}
    monkeypatch.setattr(de, "get_setting", lambda k, d=None: cfg.get(k, d))


def test_gate_off_by_default_emits(eng_env, monkeypatch):
    de, eng = eng_env
    _settings(monkeypatch, de, 0.0)  # OFF
    _emit(eng)
    assert _count("005930") == 1  # 무영향 발행


def test_gate_blocks_below_threshold(eng_env, monkeypatch):
    de, eng = eng_env
    _settings(monkeypatch, de, 0.9)  # conv≈0.74 < 0.9 → 차단
    _emit(eng)
    assert _count("005930") == 0


def test_gate_passes_above_threshold(eng_env, monkeypatch):
    de, eng = eng_env
    _settings(monkeypatch, de, 0.5)  # conv≈0.74 > 0.5 → 통과
    _emit(eng)
    assert _count("005930") == 1
