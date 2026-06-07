"""S11 Learning Memory 만료 처리 TDD 테스트.

운영 DB를 건드리지 않도록 settings.APP_DB_PATH 를 tmp_path 로 monkeypatch 한 뒤
스키마를 초기화해 격리된 SQLite 파일에서만 검증한다.
"""

from __future__ import annotations

import uuid

import pytest

import backend.services.engine.learning_memory as lm
from backend.config import settings
from backend.services.db import get_connection, initialize_database


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    """격리된 임시 SQLite DB로 APP_DB_PATH 를 교체하고 스키마를 초기화."""
    db_file = tmp_path / "test_learning_memory.sqlite3"
    monkeypatch.setattr(settings, "APP_DB_PATH", str(db_file))
    initialize_database()
    yield db_file


def _insert_memory(
    *,
    expires_at: str | None,
    status: str = "active",
    scope: str = "S3",
    created_at: str = "2026-06-01T00:00:00",
) -> str:
    """learning_memories 에 1행 삽입하고 memory_id 반환."""
    memory_id = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO learning_memories
                (memory_id, trade_date, scope, category, summary, evidence,
                 recommendation, auto_apply_allowed, requires_approval, status,
                 expires_at, created_at)
            VALUES (?, ?, ?, 'test', 'test summary', '{}', '{}', 0, 0, ?, ?, ?)
            """,
            (memory_id, "2026-06-01", scope, status, expires_at, created_at),
        )
    return memory_id


def _ids(memories: list[dict]) -> set[str]:
    return {m["memory_id"] for m in memories}


def test_expired_memory_excluded_from_active(isolated_db):
    """(a) active 이면서 expires_at < 오늘 인 메모리는 get_active_memories 에서 제외."""
    expired_id = _insert_memory(expires_at="2026-06-01")  # 오늘(2026-06-07) 이전
    result_all = lm.get_active_memories(today="2026-06-07")
    result_scoped = lm.get_active_memories(scope="S3", today="2026-06-07")
    assert expired_id not in _ids(result_all)
    assert expired_id not in _ids(result_scoped)


def test_valid_and_null_memory_included_in_active(isolated_db):
    """(b) expires_at >= 오늘 또는 NULL 인 메모리는 포함."""
    future_id = _insert_memory(expires_at="2026-06-30")
    today_id = _insert_memory(expires_at="2026-06-07")  # 오늘과 동일 → 포함
    null_id = _insert_memory(expires_at=None)
    result = lm.get_active_memories(today="2026-06-07")
    ids = _ids(result)
    assert future_id in ids
    assert today_id in ids
    assert null_id in ids


def test_expire_stale_memories_updates_and_counts(isolated_db):
    """(c) expire_stale_memories 가 만료분을 'expired' 로 바꾸고 건수를 반환."""
    stale1 = _insert_memory(expires_at="2026-06-01")
    stale2 = _insert_memory(expires_at="2026-06-06")
    valid = _insert_memory(expires_at="2026-06-30")
    null_keep = _insert_memory(expires_at=None)

    changed = lm.expire_stale_memories(today="2026-06-07")
    assert changed == 2

    with get_connection() as conn:
        rows = {
            r["memory_id"]: r["status"]
            for r in conn.execute(
                "SELECT memory_id, status FROM learning_memories"
            ).fetchall()
        }
    assert rows[stale1] == "expired"
    assert rows[stale2] == "expired"
    assert rows[valid] == "active"
    assert rows[null_keep] == "active"


def test_expire_stale_memories_idempotent(isolated_db):
    """이미 expired 된 행은 다시 세지 않는다 (active 만 대상)."""
    _insert_memory(expires_at="2026-06-01")
    first = lm.expire_stale_memories(today="2026-06-07")
    second = lm.expire_stale_memories(today="2026-06-07")
    assert first == 1
    assert second == 0
