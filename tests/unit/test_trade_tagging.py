import backend.services.engine.trade_tagging as tt


def test_record_and_load_roundtrip():
    d = "2099-03-01"
    tt._delete_for_test(d)

    tag_id = tt.record_entry_tag(
        order_id="ord-1",
        symbol="005930",
        trade_date=d,
        selection_reason={"sources": ["등락률순위#3", "거래량급증"],
                          "scores": {"universe_score": 0.36, "llm_suitability": 0.72},
                          "llm_note": "반도체 섹터 강세"},
        fired_groups=["돌파전략"],
        condition_states={"체결강도": 0.62, "틱거래량배수": 2.3, "돌파": True, "눌림": False},
        market_context={"regime": "neutral", "market_tone": "negative",
                        "time_bucket": "10:30", "vix": 18.2},
    )
    assert isinstance(tag_id, str) and tag_id

    tags = tt.load_tags(d)
    assert len(tags) == 1
    row = tags[0]
    assert row["id"] == tag_id
    assert row["order_id"] == "ord-1"
    assert row["symbol"] == "005930"
    assert row["trade_date"] == d
    # JSON 필드가 파이썬 객체로 복원됨
    assert row["selection_reason"]["sources"] == ["등락률순위#3", "거래량급증"]
    assert row["selection_reason"]["scores"]["llm_suitability"] == 0.72
    assert row["fired_groups"] == ["돌파전략"]
    assert row["condition_states"]["돌파"] is True
    assert row["condition_states"]["눌림"] is False
    assert row["market_context"]["regime"] == "neutral"
    assert row["market_context"]["vix"] == 18.2
    # outcome 은 아직 비어 있음 (빈 dict)
    assert row["outcome"] == {}

    tt._delete_for_test(d)


def test_load_tags_empty_returns_empty_list():
    d = "2099-03-02"
    tt._delete_for_test(d)
    assert tt.load_tags(d) == []


def test_set_outcome_fills_by_order_id():
    d = "2099-03-03"
    tt._delete_for_test(d)
    tt.record_entry_tag(
        order_id="ord-out",
        symbol="000660",
        trade_date=d,
        selection_reason={"sources": ["거래량급증"], "scores": {}, "llm_note": ""},
        fired_groups=["눌림전략"],
        condition_states={"체결강도": 0.55},
        market_context={"regime": "neutral", "market_tone": "neutral",
                        "time_bucket": "13:00", "vix": 15.0},
    )

    updated = tt.set_outcome(
        order_id="ord-out",
        outcome={"realized_pnl": -1700, "win": False, "hold_sec": 1820,
                 "exit_reason": "stop_loss"},
    )
    assert updated == 1

    row = tt.load_tags(d)[0]
    assert row["outcome"]["realized_pnl"] == -1700
    assert row["outcome"]["win"] is False
    assert row["outcome"]["hold_sec"] == 1820
    assert row["outcome"]["exit_reason"] == "stop_loss"
    tt._delete_for_test(d)


def test_set_outcome_missing_order_returns_zero():
    updated = tt.set_outcome(order_id="no-such-order", outcome={"win": True})
    assert updated == 0


def test_build_selection_reason_full_candidate():
    candidate = {
        "symbol": "005930", "name": "삼성전자",
        "score": 0.36, "suitability_score": 0.72,
        "change_rate": 2.3, "tsi": 42.0,
        "volume_rank": 5, "volume_surge": 220.0,
        "llm_note": "반도체 섹터 강세 모멘텀",
    }
    sr = tt.build_selection_reason(candidate)
    # sources: 단타 모멘텀 surfacing 근거 (거래대금 제거)
    assert all("거래대금" not in s for s in sr["sources"])
    assert "거래량순위#5" in sr["sources"]
    assert "거래량급증" in sr["sources"]
    # scores: 점수 근거 (universe_score = score, llm_suitability = suitability_score)
    assert sr["scores"]["universe_score"] == 0.36
    assert sr["scores"]["llm_suitability"] == 0.72
    assert sr["scores"]["change_rate"] == 2.3
    assert sr["scores"]["일봉TSI"] == 42.0
    assert sr["llm_note"] == "반도체 섹터 강세 모멘텀"


def test_build_selection_reason_sparse_candidate():
    candidate = {"symbol": "000660", "score": 0.1}
    sr = tt.build_selection_reason(candidate)
    # 누락 필드는 sources/scores 에서 빠지고, 존재하는 것만 들어간다
    assert sr["sources"] == []
    assert sr["scores"] == {"universe_score": 0.1}
    assert sr["llm_note"] == ""


def test_build_selection_reason_ignores_trade_amount_entirely():
    # 단타 모멘텀: trade_rank 가 있어도 거래대금 source 는 생성하지 않는다
    candidate = {"symbol": "005930", "trade_rank": 3, "volume_rank": 2}
    sr = tt.build_selection_reason(candidate)
    assert "거래량순위#2" in sr["sources"]
    assert all("거래대금" not in s for s in sr["sources"])


def test_build_selection_reason_skips_weak_volume_surge():
    # volume_surge 가 100% 미만이면 거래량급증 태그를 붙이지 않는다
    candidate = {"symbol": "005930", "volume_rank": 2, "volume_surge": 40.0}
    sr = tt.build_selection_reason(candidate)
    assert "거래량급증" not in sr["sources"]
    assert "거래량순위#2" in sr["sources"]
