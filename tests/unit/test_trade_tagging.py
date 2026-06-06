import backend.services.engine.trade_tagging as tt


def test_record_and_load_roundtrip():
    d = "2099-03-01"
    tt._delete_for_test(d)

    tag_id = tt.record_entry_tag(
        order_id="ord-1",
        symbol="005930",
        trade_date=d,
        selection_reason={"sources": ["등락률순위#3", "거래대금상위"],
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
    assert row["selection_reason"]["sources"] == ["등락률순위#3", "거래대금상위"]
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
