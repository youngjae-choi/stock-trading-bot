"""E6 강세요건 게이트(상승장 전용) — decision_engine._emit_signal의 강세 필터.

상승장(+uptrend_entry_mode!=off)에서 build_playbook이 entry_require_strength=True로 켜면,
_emit_signal이 시가대비 오른 종목(cfo>0)만 진입시키고 약세(cfo<=0)는 차단한다.
보합/하락/off는 entry_require_strength=False라 이 게이트가 아예 안 켜진다(불변).

이 테스트는 게이트가 실제로 소비하는 두 실물 의존성을 그대로 구동한다:
  - resolve_buy_gates(regime)["entry_require_strength"]  (레짐별 활성 여부)
  - _day_open_from_bars(symbol)                          (cfo 계산 입력)
그리고 _emit_signal이 구현한 판정(entry_require_strength & cfo<=0 → 차단)을 검증한다.
"""
from __future__ import annotations

import backend.services.engine.decision_engine_utils as u
import backend.services.settings_store as ss
from backend.config import settings
from backend.services import db as db_mod
from backend.services.engine.buy_engine import resolve_buy_gates


def _iso(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "APP_DB_PATH", str(tmp_path / "e6strength.sqlite3"))


def _seed_open(conn, symbol, trade_date, first_open):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS intraday_bars(id INTEGER PRIMARY KEY, trade_date TEXT, "
        "symbol TEXT, bar_ts TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL, "
        "shnu_rate REAL, created_at TEXT)"
    )
    conn.execute(
        "INSERT INTO intraday_bars(trade_date,symbol,bar_ts,open) VALUES(?,?,?,?)",
        (trade_date, symbol, "090000", first_open),
    )
    conn.commit()


def _gate_blocks(gates: dict, price: float, day_open: float | None) -> bool:
    """_emit_signal의 강세요건 판정을 그대로 미러(차단=True)."""
    if not bool(gates.get("entry_require_strength")):
        return False
    if not (day_open and day_open > 0 and price > 0):
        return False   # 시가 미상 → fail-open(진입 허용)
    cfo = (price / day_open - 1) * 100
    return cfo <= 0    # 시가 이하(약세) = 차단


# ── 레짐별 게이트 활성 여부(build_playbook 경유) ──

def test_up_regime_strength_gate_active_default():
    """E6 enforce 기본: 상승장은 강세요건 게이트 ON."""
    monkey_cfg = {}  # 코드기본(enforce)
    for rg in ("up", "surge", "risk_on"):
        g = resolve_buy_gates(rg, getter=lambda k, d=None: monkey_cfg.get(k, d))
        assert g["entry_require_strength"] is True, rg


def test_defensive_regime_strength_gate_off():
    """보합/하락은 강세요건 게이트 OFF(불변)."""
    for rg in ("flat", "neutral", "down", "risk_off", "volatile", "crash"):
        g = resolve_buy_gates(rg, getter=lambda k, d=None: {}.get(k, d))
        assert g["entry_require_strength"] is False, rg


def test_off_mode_strength_gate_off():
    """uptrend_entry_mode=off → 상승장도 강세요건 OFF(구동작)."""
    cfg = {"engine.uptrend_entry_mode": "off"}
    g = resolve_buy_gates("risk_on", getter=lambda k, d=None: cfg.get(k, d))
    assert g["entry_require_strength"] is False


# ── 게이트 판정(cfo) — 실물 _day_open_from_bars 구동 ──

def test_up_regime_blocks_weak_stock(tmp_path, monkeypatch):
    """상승장 + 시가 이하(약세, cfo<=0) → 차단."""
    _iso(tmp_path, monkeypatch)
    with db_mod.get_connection() as conn:
        _seed_open(conn, "005930", "2026-09-18", first_open=100.0)
    day_open = u._day_open_from_bars("005930", today="2026-09-18")
    gates = resolve_buy_gates("risk_on", getter=lambda k, d=None: {}.get(k, d))
    assert _gate_blocks(gates, price=99.0, day_open=day_open) is True    # -1% 약세
    assert _gate_blocks(gates, price=100.0, day_open=day_open) is True   # 시가 동일(cfo=0)


def test_up_regime_allows_strong_stock(tmp_path, monkeypatch):
    """상승장 + 시가 위(강세, cfo>0) → 통과."""
    _iso(tmp_path, monkeypatch)
    with db_mod.get_connection() as conn:
        _seed_open(conn, "005930", "2026-09-18", first_open=100.0)
    day_open = u._day_open_from_bars("005930", today="2026-09-18")
    gates = resolve_buy_gates("risk_on", getter=lambda k, d=None: {}.get(k, d))
    assert _gate_blocks(gates, price=100.5, day_open=day_open) is False  # +0.5% 강세


def test_defensive_regime_never_blocks_on_strength(tmp_path, monkeypatch):
    """보합/하락은 강세요건 게이트 OFF라 약세여도 이 게이트로는 차단 안 함(불변)."""
    _iso(tmp_path, monkeypatch)
    with db_mod.get_connection() as conn:
        _seed_open(conn, "005930", "2026-09-18", first_open=100.0)
    day_open = u._day_open_from_bars("005930", today="2026-09-18")
    for rg in ("flat", "down", "risk_off"):
        gates = resolve_buy_gates(rg, getter=lambda k, d=None: {}.get(k, d))
        assert _gate_blocks(gates, price=90.0, day_open=day_open) is False, rg


def test_missing_day_open_fail_open(tmp_path, monkeypatch):
    """시가 미상(봉 없음) → fail-open(차단 안 함)."""
    _iso(tmp_path, monkeypatch)
    with db_mod.get_connection() as conn:
        _seed_open(conn, "005930", "2026-09-18", first_open=100.0)
    day_open = u._day_open_from_bars("999999", today="2026-09-18")  # None
    gates = resolve_buy_gates("risk_on", getter=lambda k, d=None: {}.get(k, d))
    assert _gate_blocks(gates, price=90.0, day_open=day_open) is False
