"""과거 시세 수집기(market_data.history) — 파싱·페이징·유니버스(룩어헤드 방지)."""
from __future__ import annotations

import asyncio

import backend.services.market_data.history as h


def _mst_line(code: str, name: str, group: str, tail_len: int) -> bytes:
    head = code.ljust(9).encode() + b"KR0000000000" + name.encode("cp949")
    tail = b" " + group.encode() + b"0" * (tail_len - 3)
    return head + tail


def test_parse_master_keeps_common_only():
    raw = b"\n".join([
        _mst_line("005930", "삼성전자", "ST", 228),
        _mst_line("005935", "삼성전자우", "ST", 228),   # 우선주(코드끝≠0)
        _mst_line("069500", "KODEX 200", "EF", 228),    # ETF
        _mst_line("123450", "하나스팩1호", "ST", 228),   # 스팩
    ])
    items = h.parse_master(raw, "kospi", 228)
    assert [i["symbol"] for i in items] == ["005930"]


class _FakeClient:
    """FHKST03010230 흉내: FID_INPUT_HOUR_1 이전(포함) 120개를 역순으로 준다."""

    def __init__(self, day="20261002", times=None):
        self.day = day
        self.times = times or [f"{hh:02d}{mm:02d}" for hh in range(9, 16) for mm in range(60)
                               if "0900" <= f"{hh:02d}{mm:02d}" <= "1530" and not ("1521" <= f"{hh:02d}{mm:02d}" <= "1529")]
        self.calls = 0

    async def get(self, path, tr_id, params):
        self.calls += 1
        cut = params["FID_INPUT_HOUR_1"][:4]
        sel = [t for t in reversed(self.times) if t <= cut][:120]
        return {"output2": [{"stck_bsop_date": self.day, "stck_cntg_hour": t + "00", "stck_oprc": "100",
                             "stck_hgpr": "101", "stck_lwpr": "99", "stck_prpr": "100", "cntg_vol": "10",
                             "acml_tr_pbmn": "1000"} for t in sel]}


def test_fetch_minutes_pages_full_day():
    fake = _FakeClient()
    bars = asyncio.run(h.fetch_minutes(fake, "005930", "20261002"))
    assert len(bars) == len(fake.times) == 382  # 09:00~15:20(381) + 15:30 종가
    assert bars[0]["time"] == "0900" and bars[-1]["time"] == "1530"
    assert fake.calls == 4  # 120개씩 역순 4회


def test_fetch_minutes_drops_other_days():
    """과거포함(Y) 페이징이 전일 봉을 섞어도 대상일만 남긴다."""
    fake = _FakeClient(day="20261001")
    assert asyncio.run(h.fetch_minutes(fake, "005930", "20261002")) == []


def test_liquidity_universe_uses_previous_day():
    amounts = {"20261001": [(5e9, "A"), (9e9, "B"), (1e9, "C")], "20261002": [(99e9, "C")]}
    assert h.liquidity_universe("20261001", amounts, 2) == ["B", "A"]  # 당일(1002) 급등 C는 미반영


def test_market_hours_pause_window():
    from datetime import datetime
    assert h.in_market_hours(datetime(2026, 10, 6, 10, 0, tzinfo=h.KST))
    assert not h.in_market_hours(datetime(2026, 10, 6, 16, 0, tzinfo=h.KST))
    assert not h.in_market_hours(datetime(2026, 10, 4, 10, 0, tzinfo=h.KST))  # 일요일


def test_map_bounded_caps_in_flight():
    """동시 요청 수가 n을 넘지 않고 전 항목을 처리한다(모의키 2 → 초당 한도 보호)."""
    state = {"now": 0, "peak": 0, "seen": []}

    async def fn(x):
        state["now"] += 1
        state["peak"] = max(state["peak"], state["now"])
        await asyncio.sleep(0.01)
        state["seen"].append(x)
        state["now"] -= 1

    asyncio.run(h._map_bounded(2, list(range(9)), fn))
    assert state["peak"] == 2
    assert sorted(state["seen"]) == list(range(9))


def test_daily_fetch_start_refetches_unfinalized_last_row():
    """장중에 받은 미완성 마지막 행은 확정 전까지 그 날부터 다시 받는다(2026-10-07 부분 일봉 버그)."""
    assert h.daily_fetch_start("20261007", final=False) == "20261007"
    assert h.daily_fetch_start("20261007", final=True) == "20261008"


def test_parse_index_rows_maps_fields_and_filters_range():
    rows = [{"stck_bsop_date": "20261016", "bstp_nmix_prpr": "5668.05", "bstp_nmix_oprc": "5653.99",
             "bstp_nmix_hgpr": "5809.94", "bstp_nmix_lwpr": "5590.33", "acml_vol": "286453", "acml_tr_pbmn": "20021281"},
            {"stck_bsop_date": "20260930", "bstp_nmix_prpr": "1"}, {"stck_bsop_date": ""}]
    out = h.parse_index_rows(rows, "20261001", "20261016")
    assert out == [{"date": "20261016", "open": 5653.99, "high": 5809.94, "low": 5590.33, "close": 5668.05,
                    "volume": 286453.0, "amount": 20021281.0}]


class _FakeIndexClient:
    """FHKUP03500100 흉내: DATE_2 이하 날짜를 최신순 최대 3개씩."""

    def __init__(self, days):
        self.days = days

    async def get(self, path, tr_id, params):
        sel = [d for d in sorted(self.days, reverse=True) if d <= params["FID_INPUT_DATE_2"]][:3]
        return {"output2": [{"stck_bsop_date": d, "bstp_nmix_prpr": "100", "bstp_nmix_oprc": "99",
                             "bstp_nmix_hgpr": "101", "bstp_nmix_lwpr": "98"} for d in sel]}


def test_fetch_index_daily_pages_back_to_start():
    days = ["20261001", "20261002", "20261005", "20261006", "20261007", "20261008", "20261012"]
    out = asyncio.run(h.fetch_index_daily(_FakeIndexClient(days), "0001", "20261002", "20261012"))
    assert [r["date"] for r in out] == days[1:]


def test_extras_live_in_separate_folders(tmp_path, monkeypatch):
    """ETF·지수는 보통주 폴더(daily/, minute/)에 섞이면 안 된다(유니버스 오염 방지)."""
    monkeypatch.setattr(h, "ROOT", tmp_path)
    assert h.etf_daily_path("069500").parent.name == "daily_etf"
    assert h.etf_minute_path("20261016").parts[-3] == "minute_etf"
    assert h.index_path("0001").parent.name == "index"
    assert h._merge_write(h.index_path("0001"), [{"date": "20261016", "open": 1, "high": 1, "low": 1,
                                                  "close": 1, "volume": 0, "amount": 0}], h.INDEX_COLS) == 1
    assert not (tmp_path / "daily").exists()
