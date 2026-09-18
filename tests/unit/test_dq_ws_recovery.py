"""WS 재연결 시 DQ BLOCK 자동 해제 — 종일 매매차단 사고 재발방지 (2026-09-18).

사고: WS가 3연속 끊김→BLOCK_NEW_ENTRY 이벤트 기록. 이후 재연결돼 틱이 다시 흐르는데도 이벤트가
영구 미해결로 남아 preflight가 종일 신규매수 차단(11신호 0주문). resolve_ws_disconnect_events가
재연결 시 ws 차단 이벤트만 해제 → DQ가 실제 WS 상태를 추종.
"""
from __future__ import annotations

import backend.services.engine.data_quality_guard as dq
from backend.config import settings as cfg
from backend.services.db import initialize_database


def _setup(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "APP_DB_PATH", str(tmp_path / "dq.sqlite3"))
    initialize_database()
    return dq._today_kst()


def test_resolve_ws_clears_block(monkeypatch, tmp_path):
    td = _setup(monkeypatch, tmp_path)
    dq.record_dq_event("ws_consecutive_disconnect", "BLOCK_NEW_ENTRY", detail="[realtime_ws]")
    assert dq.get_current_status() == "BLOCK_NEW_ENTRY"
    assert dq.resolve_ws_disconnect_events(td) == 1
    assert dq.get_current_status() == "NORMAL"  # WS 재연결 → 차단 해제


def test_resolve_ws_preserves_other_dq(monkeypatch, tmp_path):
    td = _setup(monkeypatch, tmp_path)
    dq.record_dq_event("ws_consecutive_disconnect", "BLOCK_NEW_ENTRY", detail="[realtime_ws]")
    dq.record_dq_event("price_zero_or_negative", "BLOCK_NEW_ENTRY", detail="[other]")
    assert dq.resolve_ws_disconnect_events(td) == 1  # ws만 해제
    assert dq.get_current_status() == "BLOCK_NEW_ENTRY"  # 다른 BLOCK 이벤트는 보존


def test_resolve_ws_noop_when_none(monkeypatch, tmp_path):
    td = _setup(monkeypatch, tmp_path)
    assert dq.resolve_ws_disconnect_events(td) == 0  # 미해결 없으면 no-op(매 연결 호출 안전)
