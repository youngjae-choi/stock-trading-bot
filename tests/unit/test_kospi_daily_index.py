"""Daily Results의 그날 KOSPI 시초/종가/등락율 — 일별 지수 OHLC 파싱·등락율 계산 (2026-06-22).

등락율은 일별 지수차트 응답(bstp_nmix_prdy_ctrt)이 비어오는 경우가 많아 연속 종가로 계산한다
(전일 종가 대비). 이 계산이 깨지면 등락율이 0으로 표시되던 버그가 재발한다.
"""

import asyncio

import pytest


def test_index_daily_ohlc_computes_change_from_closes(monkeypatch):
    import backend.services.kis.domestic.universe_service as us

    # KIS 일별 지수차트 응답 모사 — prdy_ctrt는 0(비어옴), 종가로 등락율을 계산해야 한다.
    sample = {
        "output2": [
            {"stck_bsop_date": "20260619", "bstp_nmix_oprc": "9288.89", "bstp_nmix_prpr": "9052.42", "bstp_nmix_prdy_ctrt": "0"},
            {"stck_bsop_date": "20260618", "bstp_nmix_oprc": "8884.92", "bstp_nmix_prpr": "9063.84", "bstp_nmix_prdy_ctrt": "0"},
            {"stck_bsop_date": "20260617", "bstp_nmix_oprc": "8622.13", "bstp_nmix_prpr": "8864.24", "bstp_nmix_prdy_ctrt": "0"},
        ]
    }

    async def fake_request(*args, **kwargs):
        return sample
    monkeypatch.setattr(us.kis_client, "request", fake_request)

    rows = asyncio.run(us.get_index_daily_ohlc("0001", "2026-06-17", "2026-06-19"))
    by_date = {r["date"]: r for r in rows}

    # 시초가/종가 파싱
    assert by_date["2026-06-19"]["open"] == 9288.89
    assert by_date["2026-06-19"]["close"] == 9052.42
    # 등락율 = 전일 종가 대비. 6/19 = (9052.42-9063.84)/9063.84*100 ≈ -0.13
    assert by_date["2026-06-19"]["change_rate"] == pytest.approx(-0.13, abs=0.01)
    # 6/18 = (9063.84-8864.24)/8864.24*100 ≈ 2.25
    assert by_date["2026-06-18"]["change_rate"] == pytest.approx(2.25, abs=0.01)
    # 가장 이른 행(6/17)은 전일 종가가 범위에 없어 원값(0) 유지
    assert by_date["2026-06-17"]["change_rate"] == 0.0


def test_index_daily_ohlc_sorted_and_skips_bad_dates(monkeypatch):
    import backend.services.kis.domestic.universe_service as us

    async def fake_request(*args, **kwargs):
        return {"output2": [
            {"stck_bsop_date": "20260618", "bstp_nmix_oprc": "1", "bstp_nmix_prpr": "110"},
            {"stck_bsop_date": "", "bstp_nmix_oprc": "0", "bstp_nmix_prpr": "0"},  # 무효 날짜 → skip
            {"stck_bsop_date": "20260617", "bstp_nmix_oprc": "1", "bstp_nmix_prpr": "100"},
        ]}
    monkeypatch.setattr(us.kis_client, "request", fake_request)

    rows = asyncio.run(us.get_index_daily_ohlc("0001", "2026-06-17", "2026-06-18"))
    assert [r["date"] for r in rows] == ["2026-06-17", "2026-06-18"]  # 오름차순, 무효 제외
    assert rows[1]["change_rate"] == pytest.approx(10.0, abs=0.01)  # (110-100)/100
