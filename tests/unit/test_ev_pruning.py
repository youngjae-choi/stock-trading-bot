import backend.services.engine.buy_condition_framework as bcf
import backend.services.engine.ev_pruning as evp
from backend.services.db import get_connection


def _seed_group(name: str, weight: float, enabled: int = 1) -> str:
    """테스트용 그룹 1개를 condition_groups 에 직접 삽입하고 id 반환."""
    import uuid
    from datetime import datetime, timezone
    bcf._ensure_tables()
    gid = f"test_grp_{uuid.uuid4().hex[:8]}"
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO condition_groups (id, name, condition_ids_json, enabled, weight, assigned_to, created_at) "
            "VALUES (?, ?, '[]', ?, ?, '', ?)",
            (gid, name, enabled, weight, datetime.now(timezone.utc).isoformat()),
        )
    return gid


def _weight_enabled(gid: str) -> tuple[float, int]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT weight, enabled FROM condition_groups WHERE id = ?", (gid,)
        ).fetchone()
    return float(row["weight"]), int(row["enabled"])


def _cleanup(gid: str) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM condition_groups WHERE id = ?", (gid,))


def test_apply_auto_weight_downweight_halves_with_floor():
    gid = _seed_group("EVTEST_다운", weight=1.0)
    try:
        result = evp.apply_auto_weight([
            {"target": "EVTEST_다운", "action": "downweight", "reason": "r", "n": 40, "ev": -500.0},
        ])
        w, en = _weight_enabled(gid)
        assert w == 0.5            # 1.0 * 0.5
        assert en == 1            # downweight 는 비활성화 안 함
        assert result["adjusted"] == 1
    finally:
        _cleanup(gid)


def test_apply_auto_weight_downweight_respects_floor():
    gid = _seed_group("EVTEST_플로어", weight=0.15)
    try:
        evp.apply_auto_weight([
            {"target": "EVTEST_플로어", "action": "downweight", "reason": "r", "n": 40, "ev": -500.0},
        ])
        w, _ = _weight_enabled(gid)
        assert w == 0.1            # 0.075 → floor 0.1 (하드제로 금지)
    finally:
        _cleanup(gid)


def test_apply_auto_weight_disable_sets_floor_and_disabled():
    gid = _seed_group("EVTEST_디스", weight=0.8)
    try:
        evp.apply_auto_weight([
            {"target": "EVTEST_디스", "action": "disable", "reason": "r", "n": 120, "ev": -900.0},
        ])
        w, en = _weight_enabled(gid)
        assert w == 0.1            # 완전 0 아님 — floor 까지만
        assert en == 0            # disable 은 enabled=0
    finally:
        _cleanup(gid)


def test_apply_auto_weight_skips_non_group_targets():
    # selection_source/regime 추천(그룹 아님)은 weight 조정 대상 아님
    result = evp.apply_auto_weight([
        {"target": "등락률순위#3", "action": "downweight", "reason": "r", "n": 40, "ev": -300.0},
    ])
    assert result["adjusted"] == 0
    assert "등락률순위#3" in result["skipped"]


def test_apply_auto_weight_empty_is_noop():
    result = evp.apply_auto_weight([])
    assert result["adjusted"] == 0
    assert result["skipped"] == []
