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


import backend.services.engine.trade_tagging as tt
import json


def _record_settled(trade_date, order_id, fired, sources, regime, pnl, win):
    """정산 완료 태그 1행을 실제 trade_entry_tags 에 기록한다(테스트 데이터)."""
    tt.record_entry_tag(
        order_id=order_id, symbol="005930", trade_date=trade_date,
        selection_reason={"sources": list(sources), "scores": {}, "llm_note": ""},
        fired_groups=list(fired),
        condition_states={"체결강도": 0.6},
        market_context={"regime": regime, "market_tone": "neutral",
                        "time_bucket": "10:30", "vix": 18.0},
    )
    tt.set_outcome(order_id=order_id,
                   outcome={"realized_pnl": pnl, "win": win, "hold_sec": 600,
                            "exit_reason": "x"})


def _clear_memory(trade_date):
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM learning_memories WHERE trade_date = ? AND category = 'ev_pruning'",
            (trade_date,),
        )


def test_run_ev_pruning_aggregates_and_writes_memory_without_apply():
    d = "2099-07-01"
    tt._delete_for_test(d)
    _clear_memory(d)
    gid = _seed_group("EVRUN_음수그룹", weight=1.0)
    try:
        # 음수 EV 그룹 31표본: 8승(+200) 23패(-1000) → EV 음수
        for i in range(8):
            _record_settled(d, f"w{i}", ["EVRUN_음수그룹"], ["등락률순위#3"], "neutral", 200, True)
        for i in range(23):
            _record_settled(d, f"l{i}", ["EVRUN_음수그룹"], ["등락률순위#3"], "neutral", -1000, False)

        result = evp.run_ev_pruning(d, lookback_days=5, min_sample=30, apply=False)

        # 집계: fired_group EV 결과에 음수그룹 존재
        assert result["sample_size"] == 31
        fg = result["ev_results"]["fired_group"]["EVRUN_음수그룹"]
        assert fg["n"] == 31
        assert fg["ev"] < 0
        # 추천: negative-first 로 음수그룹 downweight
        targets = [r["target"] for r in result["recommendations"]]
        assert "EVRUN_음수그룹" in targets
        # apply=False → weight 미변경
        w, _ = _weight_enabled(gid)
        assert w == 1.0
        assert result["applied"]["adjusted"] == 0
        # learning_memories 에 negative-knowledge 1행 기록됨
        with get_connection() as conn:
            mem = conn.execute(
                "SELECT scope, category, summary, recommendation FROM learning_memories "
                "WHERE trade_date = ? AND category = 'ev_pruning'", (d,)
            ).fetchone()
        assert mem is not None
        assert mem["category"] == "ev_pruning"
        rec = json.loads(mem["recommendation"])
        assert any(r["target"] == "EVRUN_음수그룹" for r in rec["pruning"])
    finally:
        _cleanup(gid)
        tt._delete_for_test(d)
        _clear_memory(d)


def test_run_ev_pruning_apply_adjusts_weight():
    d = "2099-07-02"
    tt._delete_for_test(d)
    _clear_memory(d)
    gid = _seed_group("EVRUN_적용그룹", weight=1.0)
    try:
        for i in range(8):
            _record_settled(d, f"aw{i}", ["EVRUN_적용그룹"], [], "neutral", 200, True)
        for i in range(23):
            _record_settled(d, f"al{i}", ["EVRUN_적용그룹"], [], "neutral", -1000, False)

        result = evp.run_ev_pruning(d, lookback_days=5, min_sample=30, apply=True)
        assert result["applied"]["adjusted"] == 1
        w, _ = _weight_enabled(gid)
        assert w == 0.5            # downweight 적용됨
    finally:
        _cleanup(gid)
        tt._delete_for_test(d)
        _clear_memory(d)


def test_run_ev_pruning_insufficient_sample_no_recommendation():
    d = "2099-07-03"
    tt._delete_for_test(d)
    _clear_memory(d)
    gid = _seed_group("EVRUN_소표본", weight=1.0)
    try:
        # 표본 5건만 (min_sample=30 미달) → 추천 없음, weight 불변
        for i in range(5):
            _record_settled(d, f"s{i}", ["EVRUN_소표본"], [], "neutral", -1000, False)
        result = evp.run_ev_pruning(d, lookback_days=5, min_sample=30, apply=True)
        assert result["recommendations"] == []
        w, _ = _weight_enabled(gid)
        assert w == 1.0
    finally:
        _cleanup(gid)
        tt._delete_for_test(d)
        _clear_memory(d)
