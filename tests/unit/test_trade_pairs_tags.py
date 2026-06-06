import backend.services.engine.trade_pairs_tags as tpt


def test_enrich_matches_by_buy_order_id():
    pairs = [{
        "trade_date": "2099-05-01", "symbol": "005930", "name": "삼성전자",
        "pnl_amount": -1700, "pnl_pct": -1.2, "exit_reason": "stop_loss",
        "orders": [
            {"id": "ord-buy-1", "side": "buy"},
            {"id": "ord-sell-1", "side": "sell"},
        ],
    }]
    tags = [{
        "order_id": "ord-buy-1", "symbol": "005930", "trade_date": "2099-05-01",
        "selection_reason": {"sources": ["거래대금순위#3"], "scores": {}, "llm_note": "반도체 강세"},
        "fired_groups": ["돌파전략"],
        "condition_states": {"체결강도": 0.62, "틱거래량배수": 2.3},
        "market_context": {"regime": "neutral"},
        "outcome": {"realized_pnl": -1700, "win": False, "exit_reason": "stop_loss"},
    }]
    out = tpt.enrich_pairs_with_tags(pairs, tags)
    tag = out[0]["entry_tag"]
    assert tag is not None
    assert tag["selection_reason"]["sources"] == ["거래대금순위#3"]
    assert tag["fired_groups"] == ["돌파전략"]
    assert out[0]["selection_summary"] == "거래대금순위#3 · 반도체 강세"
    assert out[0]["buy_reason_summary"] == "돌파전략"


def test_enrich_falls_back_to_symbol_date_when_no_order_id_match():
    pairs = [{
        "trade_date": "2099-05-02", "symbol": "000660", "name": "SK하이닉스",
        "orders": [{"id": "unknown", "side": "buy"}],
    }]
    tags = [{
        "order_id": "different-id", "symbol": "000660", "trade_date": "2099-05-02",
        "selection_reason": {"sources": ["등락률순위#1"], "scores": {}, "llm_note": ""},
        "fired_groups": ["눌림전략"], "condition_states": {}, "market_context": {}, "outcome": {},
    }]
    out = tpt.enrich_pairs_with_tags(pairs, tags)
    assert out[0]["entry_tag"] is not None
    assert out[0]["selection_summary"] == "등락률순위#1"
    assert out[0]["buy_reason_summary"] == "눌림전략"


def test_enrich_no_tag_leaves_summaries_empty():
    pairs = [{"trade_date": "2099-05-03", "symbol": "111111", "orders": [{"id": "x", "side": "buy"}]}]
    out = tpt.enrich_pairs_with_tags(pairs, [])
    assert out[0]["entry_tag"] is None
    assert out[0]["selection_summary"] == ""
    assert out[0]["buy_reason_summary"] == ""
