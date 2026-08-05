"""손실 스트릭 하드 차단(결정론 안전망) — symbol_entry_blocks 테이블 단위 테스트.

add_symbol_block / get_active_blocked_symbols 가:
  · 만료되지 않은 차단 심볼을 반환하고
  · expires_at < 오늘 인 심볼은 제외하며
  · 같은 심볼 재등록 시 최신 사유·만료로 upsert 되는지
확인한다. 라이브 DB는 건드리지 않고 임시 sqlite 파일을 사용한다.
"""

from __future__ import annotations

import tempfile

import pytest


@pytest.fixture()
def db(monkeypatch):
    """임시 sqlite 로 APP_DB_PATH 를 격리 — 라이브 DB 미접촉."""
    from backend.config import settings as cfg

    tmp = tempfile.mktemp(suffix=".sqlite3")
    monkeypatch.setattr(cfg, "APP_DB_PATH", tmp)
    # symbol_entry_blocks 는 _ensure_block_table() 이 CREATE IF NOT EXISTS 로 만든다.
    return tmp


def test_active_block_returned(db):
    """만료 전 차단 심볼은 조회 집합에 포함된다."""
    from backend.services.engine.loss_streak_guard import (
        add_symbol_block,
        get_active_blocked_symbols,
    )

    add_symbol_block(
        symbol="005930",
        reason="3회 손실 (2026-08-05)",
        source="loss_streak",
        loss_count=3,
        expires_at="2999-12-31",
    )
    blocked = get_active_blocked_symbols("2026-08-05")
    assert "005930" in blocked


def test_expired_block_excluded(db):
    """expires_at < 오늘 인 심볼은 조회에서 제외된다."""
    from backend.services.engine.loss_streak_guard import (
        add_symbol_block,
        get_active_blocked_symbols,
    )

    add_symbol_block(
        symbol="000660",
        reason="3회 손실 (2026-08-01)",
        source="loss_streak",
        loss_count=3,
        expires_at="2026-08-04",  # 오늘(2026-08-05)보다 과거
    )
    blocked = get_active_blocked_symbols("2026-08-05")
    assert "000660" not in blocked


def test_mixed_active_and_expired(db):
    """활성/만료 혼재 시 활성 심볼만 반환한다."""
    from backend.services.engine.loss_streak_guard import (
        add_symbol_block,
        get_active_blocked_symbols,
    )

    add_symbol_block("111111", "활성", "loss_streak", 3, "2026-08-10")
    add_symbol_block("222222", "만료", "loss_streak", 4, "2026-07-30")
    blocked = get_active_blocked_symbols("2026-08-05")
    assert blocked == {"111111"}


def test_upsert_refreshes_reason_and_expiry(db):
    """같은 심볼 재등록 시 사유·만료·손실수가 최신값으로 갱신된다(중복행 없음)."""
    from backend.services.db import get_connection
    from backend.services.engine.loss_streak_guard import (
        add_symbol_block,
        get_active_blocked_symbols,
    )

    add_symbol_block("333333", "3회 손실", "loss_streak", 3, "2026-08-04")
    # 만료 지났으므로 조회 제외 상태
    assert "333333" not in get_active_blocked_symbols("2026-08-05")

    # 재등록 — 만료를 미래로 갱신
    add_symbol_block("333333", "5회 손실", "loss_streak", 5, "2026-08-20")
    assert "333333" in get_active_blocked_symbols("2026-08-05")

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT COUNT(*), MAX(loss_count), MAX(expires_at) FROM symbol_entry_blocks WHERE symbol='333333'"
        ).fetchone()
    assert rows[0] == 1  # PRIMARY KEY 로 upsert — 중복행 없음
    assert rows[1] == 5
    assert rows[2] == "2026-08-20"
