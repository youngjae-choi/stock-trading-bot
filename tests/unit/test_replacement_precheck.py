"""교체매매 매도 전 진입게이트 선검증 (2026-09-05).

사고: 상승장 09-04 알트→300120 교체가 알트를 손절 매도했으나 대상(300120)이 추격상태라
진입게이트에 막혀 매수 실패 → 현금 3.5h 유휴 + 알트 손실확정. floor 배포 후엔 붕괴한 대상도
차단돼 현금 종일 유휴 위험. 해법: 약체 매도 전에 대상(또는 게이트 통과 대안)을 선검증.

검증: ①entry_precheck 밴드/ETN 판정 ②_resolve_swap_target 원대상/대안/보류 ③execute_replacements
target None이면 매도조차 안 함(약체 유지).
"""
from __future__ import annotations

import asyncio
import time

import backend.services.engine.buy_engine as be_mod
import backend.services.engine.decision_engine as de_mod
import backend.services.engine.replacement_executor as rx


# ── entry_precheck (부수효과 없는 게이트 판정) ─────────────────────────────────

class _StubBar:
    def __init__(self, vwap: float):
        self._v = vwap

    def get_vwap(self, _s: str):
        return self._v


def _mk_engine(monkeypatch, vwap: float, regime: str = "risk_on"):
    eng = de_mod.DecisionEngine.__new__(de_mod.DecisionEngine)
    eng._bar_engine = _StubBar(vwap)
    eng._regime_cache = (time.monotonic(), regime)  # _current_regime → regime (캐시 신선)
    monkeypatch.setattr(de_mod, "get_setting", lambda k, d=None: d)   # 전부 코드기본
    monkeypatch.setattr(be_mod, "get_setting", lambda k, d=None: d)
    monkeypatch.setattr(de_mod, "_entry_gate_block_reason", lambda *a, **k: "")  # 선별게이트 통과로 격리
    return eng


def test_precheck_pullback_passes(monkeypatch):
    """보합장 눌림(-1% VWAP 아래, 천장 -1.0 이내)은 통과 — E6는 상승장 전용이라 무영향."""
    eng = _mk_engine(monkeypatch, vwap=10000.0, regime="neutral")
    ok, r = eng.entry_precheck("005930", {"name": "삼성전자"}, 9900.0)  # -1% (보합 밴드 내)
    assert ok, r


def test_precheck_chase_blocked(monkeypatch):
    eng = _mk_engine(monkeypatch, vwap=10000.0, regime="neutral")  # 천장 -1.0
    ok, r = eng.entry_precheck("005930", {"name": "삼성전자"}, 10000.0)  # 0% > -1 = 추격
    assert not ok and r == "vwap_chase"


def test_precheck_falling_knife_blocked(monkeypatch):
    """보합장 딥눌림(-10% < 바닥 -5) 차단 — E6 상승장 밖이라 기존 falling knife 그대로."""
    eng = _mk_engine(monkeypatch, vwap=10000.0, regime="neutral")
    ok, r = eng.entry_precheck("005930", {"name": "삼성전자"}, 9000.0)  # -10% < 바닥 -5
    assert not ok and r == "falling_knife"


def test_precheck_etn_blocked(monkeypatch):
    eng = _mk_engine(monkeypatch, vwap=10000.0, regime="risk_on")
    ok, r = eng.entry_precheck("570097", {"name": "한투 엔달러선물 ETN(H)"}, 9900.0)
    assert not ok and r == "excluded_product"


def test_precheck_riskon_e6_requires_at_or_above_vwap(monkeypatch):
    """E6 enforce 상승장: 바닥 0.0 — VWAP 아래(-0.5%)는 falling_knife 차단(laggard 배제)."""
    eng = _mk_engine(monkeypatch, vwap=10000.0, regime="risk_on")
    # E6 강세요건도 켜지므로 시가는 강세(price 위)로 격리 — VWAP 밴드만 검증
    monkeypatch.setattr(de_mod, "_day_open_from_bars", lambda s, today=None: 9000.0)
    ok, r = eng.entry_precheck("005930", {"name": "삼성전자"}, 9950.0)  # -0.5% (VWAP 아래)
    assert not ok and r == "falling_knife"


def test_precheck_riskon_e6_allows_just_above_vwap(monkeypatch):
    """E6 enforce 상승장: 천장 +1.0 — VWAP 바로 위(+0.5%)는 통과(강세근접 매수구간)."""
    eng = _mk_engine(monkeypatch, vwap=10000.0, regime="risk_on")
    monkeypatch.setattr(de_mod, "_day_open_from_bars", lambda s, today=None: 9000.0)  # 강세(시가 위)
    assert eng.entry_precheck("005930", {"name": "삼성전자"}, 10050.0)[0] is True  # +0.5% VWAP 위
    # 보합장이면 VWAP 위(+0.5%)는 추격 차단
    eng2 = _mk_engine(monkeypatch, vwap=10000.0, regime="neutral")
    assert eng2.entry_precheck("005930", {"name": "삼성전자"}, 10050.0)[1] == "vwap_chase"


def test_precheck_e6_strength_blocks_weak_in_uptrend(monkeypatch):
    """E6 enforce 상승장: 시가 이하(약세 cfo<=0) 후보는 weak_not_strong 차단."""
    eng = _mk_engine(monkeypatch, vwap=10000.0, regime="risk_on")
    monkeypatch.setattr(de_mod, "_day_open_from_bars", lambda s, today=None: 10100.0)  # 시가 위=현재가 아래=약세
    ok, r = eng.entry_precheck("005930", {"name": "삼성전자"}, 10050.0)  # VWAP +0.5%(밴드 내)지만 시가 -0.5%(약세)
    assert not ok and r == "weak_not_strong"


def test_precheck_e6_off_reverts_riskon_band(monkeypatch):
    """롤백: uptrend_entry_mode=off면 상승장도 구동작(VWAP 아래 -0.5% 통과·강세요건 없음)."""
    eng = _mk_engine(monkeypatch, vwap=10000.0, regime="risk_on")
    monkeypatch.setattr(de_mod, "get_setting",
        lambda k, d=None: "off" if k == "engine.uptrend_entry_mode" else d)
    monkeypatch.setattr(be_mod, "get_setting",
        lambda k, d=None: "off" if k == "engine.uptrend_entry_mode" else d)
    assert eng.entry_precheck("005930", {"name": "삼성전자"}, 9950.0)[0] is True  # -0.5% 통과(구 천장 0.0)


def test_precheck_open_chase_blocked_in_enforce(monkeypatch):
    """시가대비 추격 게이트 — enforce 모드면 시가 대비 +임계 초과 진입 차단(2026-09-05 엣지).

    보합장(neutral)으로 E6 밴드/강세요건 격리. VWAP 밴드는 -1.5%(천장 -1 이내·바닥 -5 이내)로 통과시킨 뒤
    시가대비만 검증한다.
    """
    eng = _mk_engine(monkeypatch, vwap=10000.0, regime="neutral")
    # enforce + 시가 9860 → price 9850은 시가대비 -0.1%(추격 아님) & VWAP -1.5%(보합 밴드 내) → 통과
    monkeypatch.setattr(de_mod, "get_setting",
        lambda k, d=None: {"engine.entry_change_from_open_mode": "enforce",
                           "engine.entry_max_change_from_open_pct": 2.0}.get(k, d))
    monkeypatch.setattr(de_mod, "_day_open_from_bars", lambda s, today=None: 9860.0)
    assert eng.entry_precheck("005930", {"name": "삼성전자"}, 9850.0)[0] is True
    # 시가 9000 → price 9850은 시가대비 +9.4% 추격 → open_chase 차단
    monkeypatch.setattr(de_mod, "_day_open_from_bars", lambda s, today=None: 9000.0)
    ok, r = eng.entry_precheck("005930", {"name": "삼성전자"}, 9850.0)
    assert not ok and r == "open_chase"


def test_precheck_open_chase_ignored_in_shadow(monkeypatch):
    """shadow(기본)면 시가대비 추격도 통과 — _emit_signal이 로그만 남기므로. 보합장으로 E6 격리."""
    eng = _mk_engine(monkeypatch, vwap=10000.0, regime="neutral")  # get_setting→기본(shadow)
    monkeypatch.setattr(de_mod, "_day_open_from_bars", lambda s, today=None: 9000.0)
    assert eng.entry_precheck("005930", {"name": "삼성전자"}, 9850.0)[0] is True  # VWAP -1.5% 보합 밴드 내


# ── _resolve_swap_target (원 대상 / 대안 / 보류) ───────────────────────────────

class _FakeDE:
    def __init__(self, passes: dict):
        self._passes = passes

    def entry_precheck(self, symbol, candidate, price):
        p = self._passes.get(symbol, False)
        return (p, "" if p else "blocked")


def _patch_de(monkeypatch, passes: dict):
    monkeypatch.setattr(de_mod, "decision_engine", _FakeDE(passes))
    # 대안 탐색이 쓰는 현 종목 score는 0으로(threshold 체크 스킵)
    import backend.services.engine.replacement_signal as rs
    monkeypatch.setattr(rs, "_current_score", lambda p, td: 0.0)


def test_resolve_target_original_passes(monkeypatch):
    _patch_de(monkeypatch, {"AAA": True})
    cmap = {"AAA": {"symbol": "AAA", "name": "a", "price": 100, "score": 0.9}}
    r = asyncio.run(rx._resolve_swap_target("CUR", "AAA", {"new_symbol": "AAA"}, cmap))
    assert r is not None and r[0] == "AAA"


def test_resolve_target_falls_back_to_passing_alt(monkeypatch):
    # 원대상 AAA 막힘(추격) → 게이트 통과 대안 BBB로 보정
    _patch_de(monkeypatch, {"AAA": False, "BBB": True})
    cmap = {
        "AAA": {"symbol": "AAA", "name": "a", "price": 100, "score": 0.9},
        "BBB": {"symbol": "BBB", "name": "b", "price": 50, "score": 0.5},
    }
    r = asyncio.run(rx._resolve_swap_target("CUR", "AAA", {"new_symbol": "AAA"}, cmap))
    assert r is not None and r[0] == "BBB"


def test_resolve_target_none_when_all_blocked(monkeypatch):
    _patch_de(monkeypatch, {"AAA": False, "BBB": False})
    cmap = {
        "AAA": {"symbol": "AAA", "name": "a", "price": 100, "score": 0.9},
        "BBB": {"symbol": "BBB", "name": "b", "price": 50, "score": 0.5},
    }
    r = asyncio.run(rx._resolve_swap_target("CUR", "AAA", {"new_symbol": "AAA"}, cmap))
    assert r is None


# ── execute_replacements 안전(핵심): 대상 미통과면 매도조차 안 함 ──────────────

def _stub_exec(monkeypatch):
    sold: list = []
    bought: list = []

    async def _fake_sell(symbol, reason):
        sold.append(symbol)
        return {"ok": True}

    async def _fake_buy(symbol, cand, price):
        bought.append(symbol)
        return {"ok": True}

    monkeypatch.setattr(rx, "_sell_position", _fake_sell)
    monkeypatch.setattr(rx, "_buy_candidate", _fake_buy)
    monkeypatch.setattr(rx, "_setting_bool", lambda k, d: True)
    monkeypatch.setattr(rx, "_setting_int", lambda k, d: 30)
    return sold, bought


def test_execute_holds_weak_when_target_blocked(monkeypatch):
    sold, bought = _stub_exec(monkeypatch)

    async def _none(cur, new, sig, cmap):
        return None
    monkeypatch.setattr(rx, "_resolve_swap_target", _none)
    res = asyncio.run(rx.execute_replacements(
        [{"current_symbol": "CUR", "new_symbol": "AAA"}], {"AAA": {"symbol": "AAA", "price": 100}}))
    assert res["executed"] == 0
    assert sold == [] and bought == []  # 매도 안 함 = 약체 유지(현금 유휴 방지)


def test_execute_swaps_when_target_passes(monkeypatch):
    sold, bought = _stub_exec(monkeypatch)

    async def _ok(cur, new, sig, cmap):
        return (new, {"symbol": new}, 100.0)
    monkeypatch.setattr(rx, "_resolve_swap_target", _ok)
    res = asyncio.run(rx.execute_replacements(
        [{"current_symbol": "CUR", "new_symbol": "AAA"}], {"AAA": {"symbol": "AAA", "price": 100}}))
    assert res["executed"] == 1 and sold == ["CUR"] and bought == ["AAA"]
