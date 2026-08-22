"""S10 equity 스냅샷 — KIS EOD 잔고조회 실패 시 baseline 폴백 검증.

8/20·21 결과 유실(KIS rate-limit) 대응(2026-08-22). equity NULL="-" 방지.
"""
from __future__ import annotations

import asyncio

import backend.services.engine.review_audit as ra


def test_equity_falls_back_to_baseline_on_kis_fail(monkeypatch):
    async def _no_kis():
        return None
    monkeypatch.setattr(ra, "_fetch_eod_total_eval", _no_kis)
    monkeypatch.setattr("backend.services.engine.daily_capital.get_total_eval_baseline",
                        lambda d: 88_000_000.0)
    snap = asyncio.run(ra._compute_equity_snapshot("2026-08-20"))
    assert snap["equity_eod_total_eval"] == 88_000_000.0   # NULL 아님(폴백)
    assert snap.get("equity_source") == "baseline_fallback"


def test_equity_uses_kis_when_available(monkeypatch):
    async def _kis():
        return 90_000_000.0
    monkeypatch.setattr(ra, "_fetch_eod_total_eval", _kis)
    monkeypatch.setattr("backend.services.engine.daily_capital.get_total_eval_baseline",
                        lambda d: 88_000_000.0)
    snap = asyncio.run(ra._compute_equity_snapshot("2026-08-20"))
    assert snap["equity_eod_total_eval"] == 90_000_000.0   # KIS 우선
    assert snap["equity_pnl"] == 2_000_000.0               # 90M - 88M


def test_equity_none_when_both_missing(monkeypatch):
    async def _no_kis():
        return None
    monkeypatch.setattr(ra, "_fetch_eod_total_eval", _no_kis)
    monkeypatch.setattr("backend.services.engine.daily_capital.get_total_eval_baseline",
                        lambda d: None)
    snap = asyncio.run(ra._compute_equity_snapshot("2026-08-20"))
    assert snap["equity_eod_total_eval"] is None           # 둘 다 없으면 None(차단 안 함)
