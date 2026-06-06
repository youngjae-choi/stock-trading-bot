import backend.services.engine.universe_filter as uf


def test_merge_adds_change_rate_rank_to_existing_symbol():
    # 단타 모멘텀: merge 는 거래량 + 등락률 2소스만 받는다 (거래대금 소스 제거)
    volume_items = [{"symbol": "005930", "name": "삼성전자", "price": 1000,
                     "change_rate": 2.3, "volume": 100}]
    change_items = [{"symbol": "005930", "change_rate": 2.3}]
    merged = uf._merge_and_deduplicate(volume_items, change_items)
    row = {r["symbol"]: r for r in merged}["005930"]
    assert row["volume_rank"] == 1
    assert row["change_rate_rank"] == 1


def test_merge_change_rate_only_symbol_is_surfaced():
    # 거래량엔 없고 등락률 순위에만 있는 강세주도 유니버스에 합류
    merged = uf._merge_and_deduplicate(
        [],
        [{"symbol": "111111", "name": "급등주", "price": 500, "change_rate": 12.0}],
    )
    row = {r["symbol"]: r for r in merged}["111111"]
    assert row["change_rate_rank"] == 1
    assert row["volume_rank"] == 9999
    assert row["change_rate"] == 12.0


def test_merge_change_rate_rank_sentinel_when_absent():
    # 등락률 소스 미제공(None) 시 모든 종목 change_rate_rank=9999
    merged = uf._merge_and_deduplicate(
        [{"symbol": "005930", "name": "삼성전자", "price": 1000, "change_rate": 2.3, "volume": 100}],
        None,
    )
    row = {r["symbol"]: r for r in merged}["005930"]
    assert row["change_rate_rank"] == 9999


def test_merge_one_arg_call_still_works():
    # 거래량 소스만으로도 동작 (등락률 소스 없음 → change_rate_rank=9999)
    merged = uf._merge_and_deduplicate(
        [{"symbol": "005930", "name": "삼성전자", "price": 1000, "change_rate": 2.3, "volume": 100}],
    )
    row = {r["symbol"]: r for r in merged}["005930"]
    assert row["change_rate_rank"] == 9999
    assert row["volume_rank"] == 1


def test_score_uses_change_rate_rank_when_present():
    weights = {"change": 0.5, "volume_surge": 0.5}
    items = [
        {"symbol": "A", "change_rate": 1.0, "volume_rank": 9999, "change_rate_rank": 1},
        {"symbol": "B", "change_rate": 1.0, "volume_rank": 9999, "change_rate_rank": 5},
    ]
    ranked = uf._score_and_rank(items, total=5, weights=weights)
    by_sym = {r["symbol"]: r for r in ranked}
    # 등락률 순위 1위가 5위보다 높은 점수
    assert by_sym["A"]["score"] > by_sym["B"]["score"]


def test_score_falls_back_to_change_rate_normalized_when_no_rank():
    weights = {"change": 0.5, "volume_surge": 0.5}
    items = [
        {"symbol": "A", "change_rate": 20.0, "volume_rank": 9999, "change_rate_rank": 9999},
        {"symbol": "B", "change_rate": -10.0, "volume_rank": 9999, "change_rate_rank": 9999},
    ]
    ranked = uf._score_and_rank(items, total=5, weights=weights)
    by_sym = {r["symbol"]: r for r in ranked}
    # 순위 없을 땐 등락률 정규화로 폴백 — +20%가 -10%보다 높은 점수
    assert by_sym["A"]["score"] > by_sym["B"]["score"]


import backend.services.engine.trade_tagging as tt


def test_build_selection_reason_includes_change_rate_rank():
    # 단타 모멘텀: 거래대금순위 태그 제거 — 등락률순위만 surfacing
    candidate = {"symbol": "005930", "change_rate_rank": 3, "volume_rank": 9999}
    sr = tt.build_selection_reason(candidate)
    assert "등락률순위#3" in sr["sources"]
    assert all("거래대금" not in s for s in sr["sources"])


def test_build_selection_reason_ignores_sentinel_change_rate_rank():
    candidate = {"symbol": "005930", "change_rate_rank": 9999, "volume_rank": 2}
    sr = tt.build_selection_reason(candidate)
    assert all("등락률순위" not in s for s in sr["sources"])
    assert "거래량순위#2" in sr["sources"]
