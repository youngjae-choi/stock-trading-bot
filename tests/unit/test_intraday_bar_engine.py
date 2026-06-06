import backend.services.engine.intraday_bar_engine as ibe


def _tick(symbol="005930", price=1000.0, cntg_vol=10, shnu_rate=60.0,
          prdy_ctrt=2.0, stck_cntg_hour="103000",
          shnu_cntg_csnu=0, seln_cntg_csnu=0):
    """합성 H0STCNT0 틱(명명 키). 라이브 WS 불필요."""
    return {
        "symbol": symbol,
        "price": price,
        "cntg_vol": cntg_vol,
        "shnu_rate": shnu_rate,
        "prdy_ctrt": prdy_ctrt,
        "stck_cntg_hour": stck_cntg_hour,
        "shnu_cntg_csnu": shnu_cntg_csnu,
        "seln_cntg_csnu": seln_cntg_csnu,
    }


def test_single_tick_opens_one_bar():
    eng = ibe.BarEngine()
    eng.ingest_tick(_tick(price=1000.0, cntg_vol=10, stck_cntg_hour="103000"))
    bars = eng.get_bars("005930")
    assert len(bars) == 1
    b = bars[-1]
    assert b.open == 1000.0
    assert b.high == 1000.0
    assert b.low == 1000.0
    assert b.close == 1000.0
    assert b.volume == 10
    assert b.bucket == "103000"  # 10초 버킷 라벨 HHMMSS (초는 10초 내림)


def test_same_bucket_ticks_aggregate_into_one_bar():
    eng = ibe.BarEngine()
    # 103000~103009 → 같은 10초 버킷
    eng.ingest_tick(_tick(price=1000.0, cntg_vol=10, stck_cntg_hour="103001"))
    eng.ingest_tick(_tick(price=1005.0, cntg_vol=5, stck_cntg_hour="103004"))
    eng.ingest_tick(_tick(price=998.0, cntg_vol=7, stck_cntg_hour="103009"))
    bars = eng.get_bars("005930")
    assert len(bars) == 1
    b = bars[-1]
    assert b.open == 1000.0   # 첫 틱
    assert b.high == 1005.0
    assert b.low == 998.0
    assert b.close == 998.0   # 마지막 틱
    assert b.volume == 22


def test_next_bucket_opens_new_bar():
    eng = ibe.BarEngine()
    eng.ingest_tick(_tick(price=1000.0, cntg_vol=10, stck_cntg_hour="103005"))
    eng.ingest_tick(_tick(price=1010.0, cntg_vol=4, stck_cntg_hour="103011"))  # 다음 버킷 103010
    bars = eng.get_bars("005930")
    assert len(bars) == 2
    assert bars[0].bucket == "103000"
    assert bars[1].bucket == "103010"
    assert bars[1].open == 1010.0
    assert bars[1].close == 1010.0


def test_symbols_are_isolated():
    eng = ibe.BarEngine()
    eng.ingest_tick(_tick(symbol="AAA", price=100.0, stck_cntg_hour="103000"))
    eng.ingest_tick(_tick(symbol="BBB", price=200.0, stck_cntg_hour="103000"))
    assert eng.get_bars("AAA")[-1].close == 100.0
    assert eng.get_bars("BBB")[-1].close == 200.0
    assert eng.get_bars("CCC") == []


def test_rolling_window_caps_bar_count():
    eng = ibe.BarEngine(max_bars=3)
    for i in range(5):
        # 각기 다른 10초 버킷: 초를 0,10,20,30,40으로
        hhmmss = "1030" + f"{i*10:02d}"
        eng.ingest_tick(_tick(price=1000.0 + i, cntg_vol=1, stck_cntg_hour=hhmmss))
    bars = eng.get_bars("005930")
    assert len(bars) == 3            # 최근 3개만 유지
    assert bars[0].bucket == "103020"
    assert bars[-1].bucket == "103040"


def test_running_vwap_is_volume_weighted():
    eng = ibe.BarEngine()
    eng.ingest_tick(_tick(price=1000.0, cntg_vol=10, stck_cntg_hour="103001"))
    eng.ingest_tick(_tick(price=1020.0, cntg_vol=30, stck_cntg_hour="103004"))
    # VWAP = (1000*10 + 1020*30) / (10+30) = (10000+30600)/40 = 1015.0
    assert eng.get_vwap("005930") == 1015.0


def test_vwap_none_when_no_volume():
    eng = ibe.BarEngine()
    assert eng.get_vwap("005930") is None
    eng.ingest_tick(_tick(price=1000.0, cntg_vol=0, stck_cntg_hour="103000"))
    # 거래량 0뿐이면 VWAP 정의 불가 → None
    assert eng.get_vwap("005930") is None


def test_day_high_tracks_max_price():
    eng = ibe.BarEngine()
    eng.ingest_tick(_tick(price=1000.0, cntg_vol=1, stck_cntg_hour="103000"))
    eng.ingest_tick(_tick(price=1030.0, cntg_vol=1, stck_cntg_hour="103010"))
    eng.ingest_tick(_tick(price=1010.0, cntg_vol=1, stck_cntg_hour="103020"))
    assert eng.get_day_high("005930") == 1030.0


def test_prior_day_high_seed_and_breakout_basis():
    eng = ibe.BarEngine()
    # 전일 고가를 외부(전일 일봉)에서 주입
    eng.set_prior_day_high("005930", 1050.0)
    assert eng.get_prior_day_high("005930") == 1050.0
    # 당일 고가는 prior-day high와 별개로 추적
    eng.ingest_tick(_tick(price=1000.0, cntg_vol=1, stck_cntg_hour="103000"))
    assert eng.get_day_high("005930") == 1000.0
    assert eng.get_prior_day_high("005930") == 1050.0
