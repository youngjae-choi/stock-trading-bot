import backend.services.engine.ev_analysis as ev


def _tag(*, fired, sources, regime, pnl, win):
    """합성 태그 dict — Phase 1c load_tags 반환 형태와 동일한 키만 사용."""
    return {
        "fired_groups": list(fired),
        "selection_reason": {"sources": list(sources), "scores": {}, "llm_note": ""},
        "market_context": {"regime": regime, "market_tone": "neutral",
                           "time_bucket": "10:30", "vix": 18.0},
        "outcome": {"realized_pnl": pnl, "win": win,
                    "hold_sec": 600, "exit_reason": "x"},
    }


def test_ev_by_fired_group_basic_math():
    # 돌파전략: 2승(+1000,+2000) 2패(-500,-1500), n=4
    tags = [
        _tag(fired=["돌파전략"], sources=[], regime="neutral", pnl=1000, win=True),
        _tag(fired=["돌파전략"], sources=[], regime="neutral", pnl=2000, win=True),
        _tag(fired=["돌파전략"], sources=[], regime="neutral", pnl=-500, win=False),
        _tag(fired=["돌파전략"], sources=[], regime="neutral", pnl=-1500, win=False),
    ]
    out = ev.compute_ev_by_dimension(tags, "fired_group")
    g = out["돌파전략"]
    assert g["n"] == 4
    assert g["wins"] == 2
    assert g["win_rate"] == 0.5
    assert g["avg_win"] == 1500.0          # (1000+2000)/2
    assert g["avg_loss"] == 1000.0         # (|−500|+|−1500|)/2
    # EV = 0.5*1500 − 0.5*1000 = 250
    assert g["ev"] == 250.0


def test_ev_negative_group():
    # 큰 손실 그룹: 1승(+200) 3패(-1000,-1000,-1000)
    tags = [
        _tag(fired=["눌림전략"], sources=[], regime="neutral", pnl=200, win=True),
        _tag(fired=["눌림전략"], sources=[], regime="neutral", pnl=-1000, win=False),
        _tag(fired=["눌림전략"], sources=[], regime="neutral", pnl=-1000, win=False),
        _tag(fired=["눌림전략"], sources=[], regime="neutral", pnl=-1000, win=False),
    ]
    out = ev.compute_ev_by_dimension(tags, "fired_group")
    g = out["눌림전략"]
    assert g["win_rate"] == 0.25
    assert g["avg_win"] == 200.0
    assert g["avg_loss"] == 1000.0
    # EV = 0.25*200 − 0.75*1000 = 50 − 750 = −700
    assert g["ev"] == -700.0


def test_multi_group_tag_counts_in_each_bucket():
    # 한 태그가 2개 그룹 발화 → 두 버킷 모두 +1
    tags = [_tag(fired=["돌파전략", "모멘텀전략"], sources=[], regime="neutral",
                 pnl=500, win=True)]
    out = ev.compute_ev_by_dimension(tags, "fired_group")
    assert out["돌파전략"]["n"] == 1
    assert out["모멘텀전략"]["n"] == 1


def test_selection_source_dimension():
    tags = [
        _tag(fired=[], sources=["등락률순위#3"], regime="neutral", pnl=1000, win=True),
        _tag(fired=[], sources=["거래대금상위"], regime="neutral", pnl=-1000, win=False),
        _tag(fired=[], sources=["등락률순위#3", "거래대금상위"], regime="neutral",
             pnl=-2000, win=False),
    ]
    out = ev.compute_ev_by_dimension(tags, "selection_source")
    assert out["등락률순위#3"]["n"] == 2          # 첫·셋째
    assert out["거래대금상위"]["n"] == 2          # 둘째·셋째


def test_regime_dimension():
    tags = [
        _tag(fired=[], sources=[], regime="risk_on", pnl=1000, win=True),
        _tag(fired=[], sources=[], regime="defensive", pnl=-1000, win=False),
    ]
    out = ev.compute_ev_by_dimension(tags, "regime")
    assert set(out.keys()) == {"risk_on", "defensive"}
    assert out["risk_on"]["wins"] == 1


def test_unsettled_tags_excluded():
    # outcome 비었거나 realized_pnl 없는 태그는 표본에서 제외
    tags = [
        {"fired_groups": ["돌파전략"], "selection_reason": {"sources": []},
         "market_context": {"regime": "neutral"}, "outcome": {}},                 # 미정산
        {"fired_groups": ["돌파전략"], "selection_reason": {"sources": []},
         "market_context": {"regime": "neutral"},
         "outcome": {"win": True}},                                              # pnl 없음
        _tag(fired=["돌파전략"], sources=[], regime="neutral", pnl=1000, win=True),
    ]
    out = ev.compute_ev_by_dimension(tags, "fired_group")
    assert out["돌파전략"]["n"] == 1               # 정산된 1건만


def test_win_inferred_from_pnl_when_win_missing():
    # outcome.win 부재 시 realized_pnl>0 로 승패 판정
    tags = [
        {"fired_groups": ["돌파전략"], "selection_reason": {"sources": []},
         "market_context": {"regime": "neutral"},
         "outcome": {"realized_pnl": 800}},        # win 키 없음 → 양수면 승
    ]
    out = ev.compute_ev_by_dimension(tags, "fired_group")
    assert out["돌파전략"]["wins"] == 1
    assert out["돌파전략"]["win_rate"] == 1.0


def test_empty_tags_returns_empty_dict():
    assert ev.compute_ev_by_dimension([], "fired_group") == {}


def test_unknown_dimension_raises():
    import pytest
    with pytest.raises(ValueError):
        ev.compute_ev_by_dimension([], "nonsense_dim")
