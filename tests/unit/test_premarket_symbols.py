"""프리마켓 시장 데이터 — 동일·인접 시간대 현물지수(전일 종가) 제거 + 미국상장 한국 ETF(EWY) 추가.

근거: 아침 브리핑(~08:30 KST)은 KR/JP/HK/CN 증시 개장 전이라 KOSPI/KOSDAQ/닛케이/항셍/상하이
현물은 '전일 종가'(stale)다. 밤사이 마감되는 EWY(미국상장 한국대표 ETF)가 KR 갭 선행지표로 유효.
장중 S2는 KIS 실시간 스냅샷을 쓰므로 이 변경은 프리마켓 브리핑에만 영향.
"""

from backend.services.engine.market_data_fetcher import _SYMBOLS, format_for_prompt

# 프리마켓 시점 stale(전일 종가)이라 제거된 동일·인접 시간대 현물
_STALE_CASH = {"kospi", "kosdaq", "nikkei", "hangseng", "shanghai", "kr_semiconductor", "kr_battery"}


def test_stale_cash_indices_removed():
    assert _STALE_CASH.isdisjoint(_SYMBOLS.keys()), f"stale 현물 잔존: {_STALE_CASH & set(_SYMBOLS)}"


def test_ewy_korea_added():
    assert _SYMBOLS.get("ewy_korea") == "EWY"


def test_overnight_valid_symbols_kept():
    # 밤사이 거래/마감되어 프리마켓에 유효한 지표는 유지
    for k in ("nasdaq", "sp500", "sox", "vix", "usdkrw", "us_10y_yield", "oil_wti"):
        assert k in _SYMBOLS, f"유효 지표 누락: {k}"


def test_format_for_prompt_labels_ewy_and_drops_stale():
    data = {
        "ewy_korea": {"change_pct": 1.5, "direction": "up", "price": 60.0, "prev_close": 59.1},
        "nasdaq": {"change_pct": -2.0, "direction": "down", "price": 100.0, "prev_close": 102.0},
    }
    txt = format_for_prompt(data)
    assert "EWY" in txt
    # 제거된 현물 라벨은 등장하지 않아야 함(데이터도 안 들어옴)
    for bad in ("닛케이", "항셍", "상하이종합"):
        assert bad not in txt
