"""모멘텀 진입 시장가 주문 — 설정화면(momentum.order_style)으로 제어 (2026-09-18).

고질병: 상승장 리더(ORB 돌파·VWAP위·상대강도≥+4%)를 감지해도 지정가+프리미엄 접수가 미체결되어
상승 수익률을 못 따라감. 기본 시장가로 감지 즉시 체결 보장. 하드코딩 금지 — momentum.order_style
설정(market/limit)이 단일 소스이고 설정화면에서 수정한다. 눌림전략(order_style 미지정)은 지정가 유지.

검증: ①_submit_buy 시장가=ord_dvsn 01·ORD_UNPR 0 / 지정가=00·호가스냅 ②momentum_entry가 설정값을
matched로 전파(+시장가 시 프리미엄 제거) ③_emit_signal이 matched.order_style을 execute_signal에 전달.
"""
from __future__ import annotations

import asyncio
import tempfile

import backend.services.engine.order_executor as oe_mod
import backend.services.settings_store as ss_mod
from backend.services.engine.order_executor import OrderExecutor


async def _noop_sleep(*_a, **_k):
    return None


def _fast(monkeypatch):
    monkeypatch.setattr(oe_mod.asyncio, "sleep", _noop_sleep)
    monkeypatch.setattr(ss_mod, "get_setting",
                        lambda k, d=None: True if k == "engine.buy_submit_retry_enabled" else d)


def _oe():
    return OrderExecutor.__new__(OrderExecutor)


# ── ① _submit_buy 주문방식 (KIS 계약) ──────────────────────────────────────────

def test_submit_buy_market_uses_ord_dvsn_01_price_0(monkeypatch):
    """시장가: ord_dvsn=01·ORD_UNPR=0 (매도 시장가와 동일 패턴) — 감지 즉시 체결 보장."""
    _fast(monkeypatch)
    seen = {}

    async def _oc(**kw):
        seen.update(kw)
        return {"output": {"ODNO": "0001234"}}
    monkeypatch.setattr(oe_mod, "order_cash", _oc)

    _resp, odno = asyncio.run(_oe()._submit_buy("005930", 10, 70000.0, "2026-09-18", is_market=True))
    assert seen["ord_dvsn"] == "01" and seen["price"] == "0" and odno == "0001234"


def test_submit_buy_limit_default_ord_dvsn_00_snapped(monkeypatch):
    """지정가(기본·눌림전략): ord_dvsn=00·지정가 호가스냅 — 기존 동작 불변."""
    _fast(monkeypatch)
    seen = {}

    async def _oc(**kw):
        seen.update(kw)
        return {"output": {"ODNO": "0001234"}}
    monkeypatch.setattr(oe_mod, "order_cash", _oc)

    asyncio.run(_oe()._submit_buy("005930", 10, 70000.0, "2026-09-18"))  # is_market 생략=지정가
    assert seen["ord_dvsn"] == "00" and seen["price"] == "70000"


def test_submit_buy_market_retry_keeps_market(monkeypatch):
    """시장가 1차 실패 재시도도 시장가 유지(ord_dvsn 01 고정)."""
    _fast(monkeypatch)
    calls = []

    async def _oc(**kw):
        calls.append(kw["ord_dvsn"])
        if len(calls) == 1:
            raise RuntimeError("EGW00201 rate limit")
        return {"output": {"ODNO": "0007777"}}
    monkeypatch.setattr(oe_mod, "order_cash", _oc)

    _resp, odno = asyncio.run(_oe()._submit_buy("005930", 10, 70000.0, "2026-09-18", is_market=True))
    assert calls == ["01", "01"] and odno == "0007777"


# ── ② momentum_entry — 설정값 전파(+시장가 프리미엄 제거) ──────────────────────

def _mom_getter(**over):
    base = {"momentum.enabled": True, "momentum.exec_start": "000000", "momentum.rs_min": 4.0,
            "momentum.or_end": "093000", "momentum.min_vol": 1000, "momentum.min_bars": 1,
            "momentum.entry_premium_pct": 1.5, "momentum.buy_spacing_sec": 0.0,
            "momentum.max_attempts": 3, "momentum.max_late_chase_pct": 2.0,
            "momentum.order_style": "market"}
    base.update(over)
    return lambda k, d=None: base.get(k, d)


def _seed_bars(conn, td, sym, rows):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS intraday_bars(id INTEGER PRIMARY KEY, trade_date TEXT, symbol TEXT,"
        " bar_ts TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL, shnu_rate REAL, created_at TEXT)")
    for ts, o, h, lo, c, v in rows:
        conn.execute("INSERT INTO intraday_bars(trade_date,symbol,bar_ts,open,high,low,close,volume)"
                     " VALUES(?,?,?,?,?,?,?,?)", (td, sym, ts, o, h, lo, c, v))
    conn.commit()


def _mom_env(monkeypatch, tmp_path, rows):
    from backend.config import settings as cfg
    from backend.services.db import initialize_database, get_connection
    import backend.services.engine.momentum_entry as m
    import backend.services.engine.position_manager as pm_mod
    import backend.services.engine.decision_engine as de_mod
    monkeypatch.setattr(cfg, "APP_DB_PATH", str(tmp_path / "mom.sqlite3"))
    initialize_database()
    td = "2026-09-10"
    with get_connection() as c:
        _seed_bars(c, td, "005930", rows)
    monkeypatch.setattr(pm_mod.position_manager, "get_positions", lambda: [])
    captured = []

    async def _fake_emit(symbol, cand, price, matched):
        captured.append({"symbol": symbol, "price": price, "matched": matched})
    monkeypatch.setattr(de_mod.decision_engine, "_emit_signal", _fake_emit)
    return m, td, captured


# 돌파: OR고 10000(093000 전), 이후 10100 돌파(시가 9000 → +12%), last_close=10100(뒷북 아님)
_BREAKOUT_ROWS = [("090000", 9000, 10000, 9000, 9500, 100000),
                  ("093100", 9500, 10100, 9500, 10100, 200000)]


def test_momentum_market_propagates_and_drops_premium(monkeypatch, tmp_path):
    """시장가: matched.order_style=market + 사이징 기준가=현재가(프리미엄 없음)."""
    m, td, cap = _mom_env(monkeypatch, tmp_path, _BREAKOUT_ROWS)
    asyncio.run(m.run_momentum_entries(td, getter=_mom_getter(**{"momentum.order_style": "market"})))
    assert len(cap) == 1
    assert cap[0]["matched"].get("momentum") is True
    assert cap[0]["matched"].get("order_style") == "market"
    assert cap[0]["price"] == 10100.0  # 프리미엄 없이 현재가(last_close)


def test_momentum_limit_propagates_and_keeps_premium(monkeypatch, tmp_path):
    """지정가: matched.order_style=limit + 기준가에 프리미엄 유지(기존 동작)."""
    m, td, cap = _mom_env(monkeypatch, tmp_path, _BREAKOUT_ROWS)
    asyncio.run(m.run_momentum_entries(td, getter=_mom_getter(**{"momentum.order_style": "limit"})))
    assert len(cap) == 1
    assert cap[0]["matched"].get("order_style") == "limit"
    assert cap[0]["price"] > 10100.0  # max(or_high,last_close)*(1+premium) > 현재가


def test_momentum_invalid_order_style_defaults_market(monkeypatch, tmp_path):
    """오타·미지원 값이면 안전하게 시장가로 폴백(즉시체결 기본)."""
    m, td, cap = _mom_env(monkeypatch, tmp_path, _BREAKOUT_ROWS)
    asyncio.run(m.run_momentum_entries(td, getter=_mom_getter(**{"momentum.order_style": "weird"})))
    assert len(cap) == 1 and cap[0]["matched"].get("order_style") == "market"


# ── ③ _emit_signal 핸드오프 — matched.order_style → execute_signal ─────────────

def _engine(monkeypatch):
    from backend.config import settings as cfg
    from backend.services.db import initialize_database
    import backend.services.engine.decision_engine as de_mod
    import backend.services.engine.technical_indicators as ti_mod
    from datetime import datetime
    from zoneinfo import ZoneInfo

    monkeypatch.setattr(cfg, "APP_DB_PATH", tempfile.mktemp(suffix=".sqlite3"))
    initialize_database()
    monkeypatch.setattr(ti_mod, "save_signal_indicators", lambda *a, **k: None)
    monkeypatch.setattr(de_mod, "_now_kst",
                        lambda: datetime(2026, 8, 20, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")))
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
    eng._bar_engine.get_vwap = lambda s: 10000.0
    return de_mod, eng


def test_emit_signal_momentum_threads_order_style_market(monkeypatch):
    """모멘텀(order_style=market) → execute_signal이 받는 signal.order_style==market."""
    de_mod, eng = _engine(monkeypatch)

    async def _run():
        captured = {}
        ev = asyncio.Event()

        async def _cap(sig):
            captured["sig"] = sig
            ev.set()
            return {"ok": True}
        monkeypatch.setattr(oe_mod.order_executor, "execute_signal", _cap)
        await eng._emit_signal("005930", {"name": "삼성전자", "confidence": 0.7}, 10000.0,
                               {"momentum": True, "order_style": "market"})
        await asyncio.wait_for(ev.wait(), timeout=1.0)
        return captured
    cap = asyncio.run(_run())
    assert cap["sig"].get("order_style") == "market"


def test_emit_signal_pullback_defaults_limit(monkeypatch):
    """눌림전략(order_style 미지정) → signal.order_style==limit(기존 지정가 유지)."""
    de_mod, eng = _engine(monkeypatch)

    async def _run():
        captured = {}
        ev = asyncio.Event()

        async def _cap(sig):
            captured["sig"] = sig
            ev.set()
            return {"ok": True}
        monkeypatch.setattr(oe_mod.order_executor, "execute_signal", _cap)
        # momentum=True로 눌림게이트만 우회(핸드오프 검증 목적), order_style 미지정 → limit 기본
        await eng._emit_signal("005930", {"name": "삼성전자", "confidence": 0.7}, 10000.0,
                               {"momentum": True})
        await asyncio.wait_for(ev.wait(), timeout=1.0)
        return captured
    cap = asyncio.run(_run())
    assert cap["sig"].get("order_style") == "limit"
