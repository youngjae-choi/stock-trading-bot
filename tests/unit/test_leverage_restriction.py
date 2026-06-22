"""레버리지/인버스 2X 진입 차단 — 매매기법 보정 (2026-06-22).

데이터 판단: 레버리지/인버스 2X는 거래당 기대값 구조적 음(-)(R:R 0.89·승률 12%·-40만/건).
_emit_signal(모든 진입 단일 길목)에서 차단. engine.leverage_restriction_mode=off면 구동작.
"""

import asyncio
import tempfile

import pytest


# ── 분류 헬퍼 ─────────────────────────────────────────────────────────────────

def test_is_leverage_product():
    from backend.services.engine.intraday_profile import is_leverage_product
    assert is_leverage_product("KODEX SK하이닉스단일종목레버리지")
    assert is_leverage_product("PLUS 삼성전자선물단일종목인버스2X")
    assert is_leverage_product("TIGER 200선물인버스2X")
    assert not is_leverage_product("현대약품")
    assert not is_leverage_product("삼성전자")
    assert not is_leverage_product("")
    assert not is_leverage_product(None)


# ── _emit_signal 진입 게이트 ──────────────────────────────────────────────────

@pytest.fixture()
def engine_env(monkeypatch):
    """임시 DB + 무거운 부수효과(주문실행·태깅·지표저장) 무력화."""
    from backend.config import settings as cfg
    from backend.services.db import initialize_database
    import backend.services.engine.decision_engine as de_mod
    import backend.services.engine.order_executor as oe_mod
    import backend.services.engine.technical_indicators as ti_mod

    tmp = tempfile.mktemp(suffix=".sqlite3")
    monkeypatch.setattr(cfg, "APP_DB_PATH", tmp)
    initialize_database()

    async def _noop_exec(*a, **k):
        return {"ok": True}
    monkeypatch.setattr(oe_mod.order_executor, "execute_signal", _noop_exec)
    monkeypatch.setattr(ti_mod, "save_signal_indicators", lambda *a, **k: None)

    eng = de_mod.DecisionEngine()
    monkeypatch.setattr(eng, "_record_exploration_tag", lambda *a, **k: None)
    return de_mod, eng


def _signal_count(symbol):
    from backend.services.db import get_connection
    with get_connection() as c:
        try:
            return c.execute("SELECT COUNT(*) n FROM trading_signals WHERE symbol=?", (symbol,)).fetchone()[0]
        except Exception:
            return 0


def _emit(eng, symbol, name):
    asyncio.run(eng._emit_signal(symbol, {"name": name, "confidence": 0.7}, 1000.0, {}))


def test_leverage_blocked_in_exclude_mode(engine_env, monkeypatch):
    de_mod, eng = engine_env
    monkeypatch.setattr(de_mod, "get_setting", lambda k, d=None: "exclude" if k == "engine.leverage_restriction_mode" else d)
    _emit(eng, "0193T0", "KODEX SK하이닉스단일종목레버리지")
    assert _signal_count("0193T0") == 0  # 진입 차단 — 신호 미발행


def test_leverage_allowed_in_off_mode(engine_env, monkeypatch):
    de_mod, eng = engine_env
    monkeypatch.setattr(de_mod, "get_setting", lambda k, d=None: "off" if k == "engine.leverage_restriction_mode" else d)
    _emit(eng, "0193T0", "KODEX SK하이닉스단일종목레버리지")
    assert _signal_count("0193T0") == 1  # off면 구동작(발행)


def test_normal_stock_unaffected_in_exclude_mode(engine_env, monkeypatch):
    de_mod, eng = engine_env
    monkeypatch.setattr(de_mod, "get_setting", lambda k, d=None: "exclude" if k == "engine.leverage_restriction_mode" else d)
    _emit(eng, "004310", "현대약품")
    assert _signal_count("004310") == 1  # 일반종목은 어느 모드든 정상 발행


def test_default_mode_is_exclude(engine_env, monkeypatch):
    """설정 미존재 시 기본 exclude(차단)."""
    de_mod, eng = engine_env
    monkeypatch.setattr(de_mod, "get_setting", lambda k, d=None: d)  # 항상 default 반환
    _emit(eng, "0193T0", "KODEX SK하이닉스단일종목레버리지")
    assert _signal_count("0193T0") == 0
