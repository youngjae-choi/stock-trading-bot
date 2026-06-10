"""EV 분석 통계 보강 테스트 — 다중그룹 분할 가중(fractional) + 레짐×그룹 층화(stratified).

배경: 한 거래가 그룹 2개를 동시 발화하면 같은 PnL 이 두 버킷에 각 1건으로
중복 집계돼 표본이 과대평가된다(독립성 위반). 분할 가중(1/N)으로 보정하고,
레짐 교란("risk_on 에서만 좋은 전략"이 전체 평균으로 가지치기되는 문제)은
레짐×그룹 층화 EV 로 방어한다.
"""

import backend.services.engine.ev_analysis as ev


def _tag(*, fired, sources=(), regime="neutral", pnl, win):
    """합성 태그 dict — load_tags 반환 형태와 동일한 키만 사용."""
    return {
        "fired_groups": list(fired),
        "selection_reason": {"sources": list(sources), "scores": {}, "llm_note": ""},
        "market_context": {"regime": regime, "market_tone": "neutral",
                           "time_bucket": "10:30", "vix": 18.0},
        "outcome": {"realized_pnl": pnl, "win": win,
                    "hold_sec": 600, "exit_reason": "x"},
    }


# ───────────────────── 분할 가중 (fractional, 기본값) ─────────────────────

def test_two_group_tag_contributes_half_to_each_bucket():
    # 2그룹 동시발화 1건 → 각 버킷 n=0.5 (중복 집계 방지)
    tags = [_tag(fired=["돌파전략", "모멘텀전략"], pnl=500, win=True)]
    out = ev.compute_ev_by_dimension(tags, "fired_group")
    assert out["돌파전략"]["n"] == 0.5
    assert out["모멘텀전략"]["n"] == 0.5
    assert out["돌파전략"]["wins"] == 0.5


def test_fractional_false_keeps_legacy_double_counting():
    # 하위 호환: fractional=False 면 기존처럼 각 버킷 1건씩
    tags = [_tag(fired=["돌파전략", "모멘텀전략"], pnl=500, win=True)]
    out = ev.compute_ev_by_dimension(tags, "fired_group", fractional=False)
    assert out["돌파전략"]["n"] == 1
    assert out["모멘텀전략"]["n"] == 1


def test_fractional_weighted_ev_math():
    # A 단독승(+1000, w=1) + A·B 동시패(-500, w=0.5)
    # A: n=1.5, win_rate=1/1.5, avg_win=1000, avg_loss=500
    # EV = (1/1.5)*1000 − (0.5/1.5)*500 = 666.667 − 166.667 = 500
    tags = [
        _tag(fired=["A"], pnl=1000, win=True),
        _tag(fired=["A", "B"], pnl=-500, win=False),
    ]
    out = ev.compute_ev_by_dimension(tags, "fired_group")
    a = out["A"]
    assert a["n"] == 1.5
    assert a["wins"] == 1.0
    assert a["avg_win"] == 1000.0
    assert a["avg_loss"] == 500.0
    assert a["ev"] == 500.0
    # B: 0.5 가중 패배 1건뿐 → EV = −500
    b = out["B"]
    assert b["n"] == 0.5
    assert b["ev"] == -500.0


def test_single_key_tags_identical_to_legacy():
    # 단일 그룹 태그만 있으면 fractional 여부와 무관하게 결과 동일
    tags = [
        _tag(fired=["돌파전략"], pnl=1000, win=True),
        _tag(fired=["돌파전략"], pnl=-500, win=False),
    ]
    new = ev.compute_ev_by_dimension(tags, "fired_group")
    old = ev.compute_ev_by_dimension(tags, "fired_group", fractional=False)
    assert new == old


# ───────────────────── 레짐×그룹 층화 (stratified) ─────────────────────

def test_stratified_composite_keys():
    tags = [
        _tag(fired=["돌파전략"], regime="risk_on", pnl=1000, win=True),
        _tag(fired=["돌파전략"], regime="defensive", pnl=-800, win=False),
        _tag(fired=["눌림전략"], regime="risk_on", pnl=-300, win=False),
    ]
    out = ev.compute_ev_stratified(tags)
    assert set(out.keys()) == {"risk_on|돌파전략", "defensive|돌파전략", "risk_on|눌림전략"}
    assert out["risk_on|돌파전략"]["n"] == 1
    assert out["risk_on|돌파전략"]["ev"] == 1000.0
    assert out["defensive|돌파전략"]["ev"] == -800.0


def test_stratified_applies_fractional_weight():
    # 2그룹 동시발화 → 각 복합키에 0.5 가중
    tags = [_tag(fired=["돌파전략", "모멘텀전략"], regime="risk_on", pnl=500, win=True)]
    out = ev.compute_ev_stratified(tags)
    assert out["risk_on|돌파전략"]["n"] == 0.5
    assert out["risk_on|모멘텀전략"]["n"] == 0.5


def test_stratified_skips_tags_missing_regime_or_group():
    tags = [
        _tag(fired=["돌파전략"], regime="", pnl=1000, win=True),    # 레짐 없음
        _tag(fired=[], regime="risk_on", pnl=-500, win=False),      # 그룹 없음
    ]
    assert ev.compute_ev_stratified(tags) == {}


# ───────────────── 레짐 교란 방어 (권고 제외 필터) ─────────────────

def test_regime_positive_layer_excluded_from_recommendations():
    # 전체 평균은 음수지만 risk_on 층에서 EV>0 & n>=min_sample/2 → 권고 제외
    recs = [
        {"target": "레짐양수그룹", "action": "downweight", "reason": "r", "n": 40, "ev": -400.0},
        {"target": "순수음수그룹", "action": "downweight", "reason": "r", "n": 40, "ev": -700.0},
    ]
    stratified = {
        "risk_on|레짐양수그룹": {"n": 15, "wins": 15, "win_rate": 1.0,
                             "avg_win": 500.0, "avg_loss": 0.0, "ev": 500.0},
        "defensive|레짐양수그룹": {"n": 25, "wins": 0, "win_rate": 0.0,
                               "avg_win": 0.0, "avg_loss": 1000.0, "ev": -1000.0},
        "risk_on|순수음수그룹": {"n": 20, "wins": 2, "win_rate": 0.1,
                             "avg_win": 100.0, "avg_loss": 800.0, "ev": -710.0},
    }
    kept, skipped = ev.filter_regime_confounded(recs, stratified, min_sample=30)
    assert [r["target"] for r in kept] == ["순수음수그룹"]
    assert len(skipped) == 1
    assert skipped[0]["target"] == "레짐양수그룹"
    assert skipped[0]["reason"] == "regime_positive_layer"
    assert "risk_on|레짐양수그룹" in skipped[0]["positive_layers"]


def test_regime_positive_layer_too_small_sample_not_excluded():
    # 양수 층이 있어도 층 표본이 min_sample/2 미만이면 권고 유지(노이즈 방어)
    recs = [{"target": "소층그룹", "action": "downweight", "reason": "r", "n": 40, "ev": -400.0}]
    stratified = {
        "risk_on|소층그룹": {"n": 5, "wins": 5, "win_rate": 1.0,
                          "avg_win": 500.0, "avg_loss": 0.0, "ev": 500.0},
    }
    kept, skipped = ev.filter_regime_confounded(recs, stratified, min_sample=30)
    assert [r["target"] for r in kept] == ["소층그룹"]
    assert skipped == []


# ───────────────── run_ev_pruning 통합 (DB, 기존 패턴 동일) ─────────────────

def test_run_ev_pruning_stratified_in_results_and_regime_skip():
    import backend.services.engine.ev_pruning as evp
    import backend.services.engine.trade_tagging as tt
    from backend.services.db import get_connection
    import json

    d = "2099-07-04"

    def _record(order_id, regime, pnl, win):
        tt.record_entry_tag(
            order_id=order_id, symbol="005930", trade_date=d,
            selection_reason={"sources": [], "scores": {}, "llm_note": ""},
            fired_groups=["EVRUN_레짐양수"],
            condition_states={"체결강도": 0.6},
            market_context={"regime": regime, "market_tone": "neutral",
                            "time_bucket": "10:30", "vix": 18.0},
        )
        tt.set_outcome(order_id=order_id,
                       outcome={"realized_pnl": pnl, "win": win,
                                "hold_sec": 600, "exit_reason": "x"})

    def _clear_memory():
        with get_connection() as conn:
            conn.execute(
                "DELETE FROM learning_memories WHERE trade_date = ? AND category = 'ev_pruning'",
                (d,),
            )

    tt._delete_for_test(d)
    _clear_memory()
    try:
        # defensive 25패(-1000) + risk_on 15승(+500)
        # 전체: n=40, EV = 0.375*500 − 0.625*1000 = −437.5 (음수 → 원래 권고 대상)
        # risk_on 층: n=15(>=min_sample/2), EV=+500 → 레짐 교란 방어로 권고 제외
        for i in range(25):
            _record(f"rs_l{i}", "defensive", -1000, False)
        for i in range(15):
            _record(f"rs_w{i}", "risk_on", 500, True)

        result = evp.run_ev_pruning(d, lookback_days=5, min_sample=30, apply=False)

        # 층화 결과가 ev_results 에 포함된다
        strat = result["ev_results"]["regime_stratified"]
        assert strat["risk_on|EVRUN_레짐양수"]["ev"] > 0
        assert strat["defensive|EVRUN_레짐양수"]["ev"] < 0
        # 전체 음수지만 risk_on 층 양수 → 권고 제외 + skipped 기록
        targets = [r["target"] for r in result["recommendations"]]
        assert "EVRUN_레짐양수" not in targets
        skipped = [s for s in result["skipped"] if s["target"] == "EVRUN_레짐양수"]
        assert skipped and skipped[0]["reason"] == "regime_positive_layer"
        # 메모리 evidence 에 층화 결과가 남는다(어느 레짐에서 음수인지 기록)
        with get_connection() as conn:
            mem = conn.execute(
                "SELECT evidence FROM learning_memories "
                "WHERE trade_date = ? AND category = 'ev_pruning'", (d,)
            ).fetchone()
        assert mem is not None
        evidence = json.loads(mem["evidence"])
        assert "regime_stratified" in evidence["ev_results"]
    finally:
        tt._delete_for_test(d)
        _clear_memory()
