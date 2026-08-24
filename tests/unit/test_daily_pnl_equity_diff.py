"""당일 손익 — 계좌(전일 종가총평가 대비) 기준 (2026-08-24 통일).

SSOT: account_pnl.compute_account_pnl. 당일손익 = 라이브 total_eval − 전일 종가총평가(prev EOD).
- baseline을 '당일 9시'에서 '전일 종가'로 바꿔 EOD 요약(Daily Results·리뷰)과 라이브 화면을 일치시킴.
- % 는 전일 종가총평가 대비(계좌 잔고 대비 복리 — PM 2026-07-06 원칙 유지, baseline만 전일종가).
- 전일 종가총평가 없으면(첫 거래일 등) daily_pnl_total/pct = None (0 아님), daily_pnl_available=False.
"""

import backend.api.routes.account as acct


def _kis(total_eval, stock_eval=0, unrealized=0):
    return {
        "output1": [],
        "output2": [{
            "tot_evlu_amt": str(total_eval),
            "scts_evlu_amt": str(stock_eval),
            "dnca_tot_amt": "100000000",
            "evlu_pfls_smtl_amt": str(unrealized),
        }],
    }


def test_daily_pnl_is_close_to_close(monkeypatch):
    """당일손익 = 라이브 total_eval − 전일 종가총평가."""
    import backend.services.engine.account_pnl as ap
    import backend.services.engine.trade_pairs as tp
    monkeypatch.setattr(ap, "_principal", lambda: 100_000_000)
    # 전일 종가총평가 = 102,260,271 (당일 9시 baseline이 아니라 전일 종가 baseline)
    monkeypatch.setattr(ap, "load_eod_total_eval_by_date", lambda: {"2026-06-11": 102_260_271.0})
    monkeypatch.setattr(tp, "get_today_realized_pnl", lambda d: -1_356_224)
    p = acct._build_balance_payload(_kis(total_eval=99_982_903, unrealized=1_470_411))
    assert p["daily_pnl_total"] == 99_982_903 - 102_260_271  # -2,277,368
    # % 는 전일 종가총평가(102,260,271) 대비.
    assert p["daily_pnl_pct"] == round(-2_277_368 / 102_260_271 * 100, 2)
    assert p["daily_pnl_available"] is True
    # 보조 분해는 유지
    assert p["today_realized_pnl"] == -1_356_224
    assert p["pnl_total"] == 1_470_411


def test_daily_pnl_none_without_prior_eod(monkeypatch):
    """전일 종가총평가가 없으면 daily_pnl None(허위 0 금지)."""
    import backend.services.engine.account_pnl as ap
    import backend.services.engine.trade_pairs as tp
    monkeypatch.setattr(ap, "_principal", lambda: 100_000_000)
    monkeypatch.setattr(ap, "load_eod_total_eval_by_date", lambda: {})  # 전일 종가 없음
    monkeypatch.setattr(tp, "get_today_realized_pnl", lambda d: 0)
    p = acct._build_balance_payload(_kis(total_eval=100_000_000))
    assert p["daily_pnl_total"] is None
    assert p["daily_pnl_pct"] is None
    assert p["daily_pnl_available"] is False
