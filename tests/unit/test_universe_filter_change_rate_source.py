import backend.services.engine.universe_filter as uf


def test_merge_adds_change_rate_rank_to_existing_symbol():
    volume_items = [{"symbol": "005930", "name": "삼성전자", "price": 1000,
                     "change_rate": 2.3, "volume": 100}]
    trade_items = [{"symbol": "005930", "trade_amount": 5000}]
    change_items = [{"symbol": "005930", "change_rate": 2.3}]
    merged = uf._merge_and_deduplicate(volume_items, trade_items, change_items)
    row = {r["symbol"]: r for r in merged}["005930"]
    assert row["volume_rank"] == 1
    assert row["trade_rank"] == 1
    assert row["change_rate_rank"] == 1


def test_merge_change_rate_only_symbol_is_surfaced():
    # 거래량/거래대금엔 없고 등락률 순위에만 있는 강세주도 유니버스에 합류
    merged = uf._merge_and_deduplicate(
        [],
        [],
        [{"symbol": "111111", "name": "급등주", "price": 500, "change_rate": 12.0}],
    )
    row = {r["symbol"]: r for r in merged}["111111"]
    assert row["change_rate_rank"] == 1
    assert row["volume_rank"] == 9999
    assert row["trade_rank"] == 9999
    assert row["change_rate"] == 12.0


def test_merge_change_rate_rank_sentinel_when_absent():
    # 등락률 소스 미제공(None) 시 모든 종목 change_rate_rank=9999
    merged = uf._merge_and_deduplicate(
        [{"symbol": "005930", "name": "삼성전자", "price": 1000, "change_rate": 2.3, "volume": 100}],
        [],
        None,
    )
    row = {r["symbol"]: r for r in merged}["005930"]
    assert row["change_rate_rank"] == 9999


def test_merge_two_arg_call_still_works():
    # 하위호환: 기존 2-인자 호출(등락률 소스 없음)도 동작
    merged = uf._merge_and_deduplicate(
        [{"symbol": "005930", "name": "삼성전자", "price": 1000, "change_rate": 2.3, "volume": 100}],
        [{"symbol": "005930", "trade_amount": 5000}],
    )
    row = {r["symbol"]: r for r in merged}["005930"]
    assert row["change_rate_rank"] == 9999
    assert row["trade_rank"] == 1
