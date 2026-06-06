"""S3 유니버스 — 단타 모멘텀 선정 (등락률 50% + 거래량급증 50%) 회귀 테스트.

거래대금(trade_amount)은 소스/점수에서 완전히 제거됐다.
점수 = change_w * change_score + surge_w * surge_score
- change_score: change_rate_rank 있으면 순위점수, 없으면 등락률 정규화
- surge_score: vol_inrt(전일대비 거래량증가율, 퍼센트) 정규화 = min(1.0, surge/300)
              surge=0/부재 시 거래량 RANK 점수로 폴백
- _TONE_WEIGHTS: 모든 톤 {"change": 0.5, "volume_surge": 0.5}
"""

import backend.services.engine.universe_filter as uf
import backend.services.kis.domestic.universe_service as us


# ---------------------------------------------------------------------------
# _TONE_WEIGHTS — 2팩터 50/50
# ---------------------------------------------------------------------------

def test_tone_weights_are_two_factor_fifty_fifty():
    for tone, w in uf._TONE_WEIGHTS.items():
        assert set(w.keys()) == {"change", "volume_surge"}, tone
        assert w["change"] == 0.5
        assert w["volume_surge"] == 0.5
        assert "trade" not in w


# ---------------------------------------------------------------------------
# _score_and_rank — 신규 점수 모델
# ---------------------------------------------------------------------------

def _w():
    return {"change": 0.5, "volume_surge": 0.5}


def test_high_change_and_surge_outranks_low():
    items = [
        {"symbol": "HI", "change_rate": 20.0, "change_rate_rank": 1,
         "volume_rank": 1, "volume_surge": 250.0},
        {"symbol": "LO", "change_rate": -5.0, "change_rate_rank": 9999,
         "volume_rank": 50, "volume_surge": 5.0},
    ]
    ranked = uf._score_and_rank(items, total=50, weights=_w())
    by = {r["symbol"]: r for r in ranked}
    assert by["HI"]["score"] > by["LO"]["score"]
    assert by["HI"]["rank"] == 1


def test_trade_amount_no_longer_affects_score():
    # 두 종목이 등락률/급증 동일, trade_rank만 다름 → 점수 동일해야 함
    base = {"change_rate": 5.0, "change_rate_rank": 3,
            "volume_rank": 3, "volume_surge": 150.0}
    items = [
        {"symbol": "A", "trade_rank": 1, "trade_amount": 9_999_999, **base},
        {"symbol": "B", "trade_rank": 9999, "trade_amount": 0, **base},
    ]
    ranked = uf._score_and_rank(items, total=10, weights=_w())
    by = {r["symbol"]: r for r in ranked}
    assert by["A"]["score"] == by["B"]["score"]


def test_surge_score_normalizes_percent():
    # surge=300%(=3배) 이상이면 1.0 포화, surge 큰 쪽이 점수 높음
    items = [
        {"symbol": "BIG", "change_rate": 0.0, "change_rate_rank": 9999,
         "volume_rank": 9999, "volume_surge": 300.0},
        {"symbol": "SMALL", "change_rate": 0.0, "change_rate_rank": 9999,
         "volume_rank": 9999, "volume_surge": 30.0},
    ]
    ranked = uf._score_and_rank(items, total=10, weights=_w())
    by = {r["symbol"]: r for r in ranked}
    assert by["BIG"]["score"] > by["SMALL"]["score"]
    # BIG: change_score=0.5(=(0+30)/60), surge_score=1.0 → 0.5*0.5+0.5*1.0=0.75
    assert by["BIG"]["score"] == 0.75


def test_surge_zero_falls_back_to_volume_rank():
    # volume_surge 부재/0 → 거래량 RANK 점수로 폴백해 여전히 정렬됨
    items = [
        {"symbol": "RANKED", "change_rate": 0.0, "change_rate_rank": 9999,
         "volume_rank": 1, "volume_surge": 0.0},
        {"symbol": "UNRANKED", "change_rate": 0.0, "change_rate_rank": 9999,
         "volume_rank": 9999, "volume_surge": 0.0},
    ]
    ranked = uf._score_and_rank(items, total=10, weights=_w())
    by = {r["symbol"]: r for r in ranked}
    # surge 둘 다 0이지만 volume_rank 1위가 폴백점수로 더 높다
    assert by["RANKED"]["score"] > by["UNRANKED"]["score"]


def test_surge_absent_key_uses_volume_rank_fallback():
    # volume_surge 키 자체가 없어도 폴백
    items = [
        {"symbol": "A", "change_rate": 0.0, "change_rate_rank": 9999, "volume_rank": 1},
        {"symbol": "B", "change_rate": 0.0, "change_rate_rank": 9999, "volume_rank": 40},
    ]
    ranked = uf._score_and_rank(items, total=50, weights=_w())
    by = {r["symbol"]: r for r in ranked}
    assert by["A"]["score"] > by["B"]["score"]


# ---------------------------------------------------------------------------
# _merge_and_deduplicate — trade 소스 불필요 + volume_surge carry-through
# ---------------------------------------------------------------------------

def test_merge_without_trade_source_volume_and_change_only():
    volume_items = [{"symbol": "005930", "name": "삼성전자", "price": 1000,
                     "change_rate": 2.3, "volume": 100, "volume_surge": 180.0}]
    change_items = [{"symbol": "005930", "change_rate": 2.3}]
    merged = uf._merge_and_deduplicate(volume_items, change_items)
    row = {r["symbol"]: r for r in merged}["005930"]
    assert row["volume_rank"] == 1
    assert row["change_rate_rank"] == 1
    assert row["volume_surge"] == 180.0


def test_merge_carries_volume_surge_from_volume_source():
    volume_items = [{"symbol": "111", "name": "급증주", "price": 500,
                     "change_rate": 8.0, "volume": 9000, "volume_surge": 420.0}]
    merged = uf._merge_and_deduplicate(volume_items, None)
    row = {r["symbol"]: r for r in merged}["111"]
    assert row["volume_surge"] == 420.0


def test_merge_change_only_symbol_has_zero_surge():
    merged = uf._merge_and_deduplicate(
        [],
        [{"symbol": "222", "name": "강세주", "price": 700, "change_rate": 15.0}],
    )
    row = {r["symbol"]: r for r in merged}["222"]
    assert row["volume_rank"] == 9999
    assert row["change_rate_rank"] == 1
    assert row["volume_surge"] == 0.0


# ---------------------------------------------------------------------------
# get_volume_rank — volume_surge(vol_inrt) 파싱
# ---------------------------------------------------------------------------

def test_volume_surge_keys_include_vol_inrt():
    assert "vol_inrt" in us._VOLUME_SURGE_KEYS


def test_pick_float_parses_vol_inrt():
    row = {"vol_inrt": "72.63"}
    assert us._pick_float(row, us._VOLUME_SURGE_KEYS) == 72.63
