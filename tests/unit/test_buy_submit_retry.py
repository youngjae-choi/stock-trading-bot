"""매수 접수 신뢰성 — 접수 실패 재시도(Mode1) + ODNO 누락 복구 재조회(Mode2) (2026-09-05).

배경: 매수 체결률 ~50%, 미체결의 89%가 지정가 문제가 아닌 **KIS 접수 실패**(ODNO 없음→
submit_uncertain→EOD 취소)로 배포 손실. 매도엔 있던 재시도가 매수엔 없던 비대칭 해소 +
ODNO 복구를 즉시 1회→지연 재조회로 강화. 롤백: engine.buy_submit_retry_enabled=false.
"""
from __future__ import annotations

import asyncio

import pytest

import backend.services.engine.order_executor as oe_mod
import backend.services.kis.domestic.service as ksvc
import backend.services.settings_store as ss_mod
from backend.services.engine.order_executor import OrderExecutor


async def _noop_sleep(*_a, **_k):
    return None


def _fast(monkeypatch, retry_enabled: bool = True):
    monkeypatch.setattr(oe_mod.asyncio, "sleep", _noop_sleep)  # 재시도 지연 제거(빠른 테스트)
    monkeypatch.setattr(
        ss_mod, "get_setting",
        lambda k, d=None: retry_enabled if k == "engine.buy_submit_retry_enabled" else d,
    )


def _oe():
    return OrderExecutor.__new__(OrderExecutor)


# ── Mode 1: 접수 예외 재시도 ──────────────────────────────────────────────────

def test_buy_retries_on_exception_then_succeeds(monkeypatch):
    _fast(monkeypatch)
    calls = {"n": 0}

    async def _oc(**_kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("EGW00201 rate limit")
        return {"output": {"ODNO": "0001234"}}
    monkeypatch.setattr(oe_mod, "order_cash", _oc)

    _resp, odno = asyncio.run(_oe()._submit_buy("005930", 10, 70000.0, "2026-09-05"))
    assert calls["n"] == 2 and odno == "0001234"  # 1차 실패 → 재시도 성공


def test_buy_no_retry_when_disabled(monkeypatch):
    _fast(monkeypatch, retry_enabled=False)
    calls = {"n": 0}

    async def _oc(**_kw):
        calls["n"] += 1
        raise RuntimeError("fail")
    monkeypatch.setattr(oe_mod, "order_cash", _oc)

    with pytest.raises(RuntimeError):
        asyncio.run(_oe()._submit_buy("005930", 10, 70000.0, "2026-09-05"))
    assert calls["n"] == 1  # 롤백 스위치 off → 재시도 안 함(구동작)


def test_buy_retry_exhausted_raises(monkeypatch):
    _fast(monkeypatch)
    calls = {"n": 0}

    async def _oc(**_kw):
        calls["n"] += 1
        raise RuntimeError("persistent")
    monkeypatch.setattr(oe_mod, "order_cash", _oc)

    with pytest.raises(RuntimeError):
        asyncio.run(_oe()._submit_buy("005930", 10, 70000.0, "2026-09-05"))
    assert calls["n"] == 3  # 최초 1 + 재시도 2


# ── Mode 2: ODNO 누락 복구 재조회 ─────────────────────────────────────────────

def test_odno_recovery_retries_via_ccld(monkeypatch):
    _fast(monkeypatch)

    async def _oc(**_kw):
        return {"output": {}}  # 200이지만 ODNO 없음
    monkeypatch.setattr(oe_mod, "order_cash", _oc)

    rec = {"n": 0}

    async def _ccld(_date_str, side=None):
        rec["n"] += 1
        if rec["n"] == 1:
            return {"output1": []}  # 아직 전파 안 됨
        return {"output1": [{"pdno": "005930", "odno": "0009999"}]}
    monkeypatch.setattr(ksvc, "get_daily_order_inquiry", _ccld)

    _resp, odno = asyncio.run(_oe()._submit_buy("005930", 10, 70000.0, "2026-09-05"))
    assert rec["n"] == 2 and odno == "0009999"  # 재조회로 복구(재제출 아님)


def test_odno_recovery_none_stays_uncertain(monkeypatch):
    _fast(monkeypatch)

    async def _oc(**_kw):
        return {"output": {}}
    monkeypatch.setattr(oe_mod, "order_cash", _oc)

    async def _ccld(_date_str, side=None):
        return {"output1": []}
    monkeypatch.setattr(ksvc, "get_daily_order_inquiry", _ccld)

    _resp, odno = asyncio.run(_oe()._submit_buy("005930", 10, 70000.0, "2026-09-05"))
    assert odno == ""  # 복구 실패 → 호출부가 submit_uncertain 기록(재제출 안 함=중복매수 방지)
