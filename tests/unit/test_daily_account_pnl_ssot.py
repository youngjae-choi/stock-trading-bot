"""계좌 당일손익(종가-종가) SSOT — Daily Results·리뷰가 공유하는 단일 계산.

account_pnl.daily_account_pnl = 종가총평가[오늘] − 종가총평가[직전거래일].
실측 앵커(2026-08 값)로 Daily Results 표 컬럼을 정확히 재현하는지 검증한다.
"""

import backend.services.engine.account_pnl as ap

# 실측 종가총평가(equity_eod_total_eval) — 2026-08 라이브 DB에서 확인한 값
_EOD = {
    "2026-08-19": 86_858_354.0,
    "2026-08-20": 86_858_354.0,
    "2026-08-21": 87_778_388.0,
    "2026-08-24": 88_001_426.0,
}


def test_close_to_close_reproduces_daily_results():
    """08-24: 88,001,426 − 87,778,388 = +223,038 (Daily Results P&L 계좌와 일치)."""
    r = ap.daily_account_pnl("2026-08-24", eod_by_date=_EOD)
    assert r["account_pnl"] == 223_038
    assert r["account_pnl_pct"] == 0.25  # Daily Results RETURN 컬럼과 일치(전일 종가 대비)
    assert r["available"] is True
    assert r["eod_total_eval"] == 88_001_426.0
    assert r["prior_eod"] == 87_778_388.0


def test_uses_prior_trading_day_not_calendar_day():
    """08-21: 직전 거래일 08-20(86,858,354) 대비 → +920,034 (표와 일치)."""
    r = ap.daily_account_pnl("2026-08-21", eod_by_date=_EOD)
    assert r["account_pnl"] == 920_034


def test_flat_day_zero():
    """08-20: 08-19와 동일(86,858,354) → 0원 (표의 +0원과 일치)."""
    r = ap.daily_account_pnl("2026-08-20", eod_by_date=_EOD)
    assert r["account_pnl"] == 0


def test_unavailable_without_prior():
    """직전 종가총평가가 없으면 available=False, account_pnl=None (허위 숫자 금지)."""
    r = ap.daily_account_pnl("2026-08-24", eod_by_date={"2026-08-24": 88_001_426.0})
    assert r["available"] is False
    assert r["account_pnl"] is None


def test_anchor_used_as_prior_eod():
    """앵커(2026-07-23=1억)가 직전 종가로 쓰인다 — 계좌 리셋 후 첫날 계좌P&L 정합."""
    eod = dict(ap._EOD_ANCHORS)  # {"2026-07-23": 1억}
    eod["2026-07-24"] = 100_500_000.0
    r = ap.daily_account_pnl("2026-07-24", eod_by_date=eod)
    assert r["account_pnl"] == 500_000
