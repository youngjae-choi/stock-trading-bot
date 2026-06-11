"""당일 손익 A안 — 자본변화 기준(총평가-장시작자본) (PM 결정 2026-06-11).

배경: 부품 조립식(실현 FIFO + 평가손익)은 고회전일에 수수료·제세금·짝맞춤 누락으로
실제 자본 변화와 큰 오차(6/11: 표시 +0.11% vs 실제 -2.23%). 당일손익 헤드라인을
equity-diff로 교체해 항상 계좌 잔고와 일치시킨다. 실현/평가 분해는 보조 표기 유지.
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


def test_daily_pnl_is_equity_diff(monkeypatch):
    import backend.services.engine.daily_capital as dc
    import backend.services.engine.trade_pairs as tp
    monkeypatch.setattr(dc, "get_baseline", lambda d=None: 102_260_271.0)
    monkeypatch.setattr(tp, "get_today_realized_pnl", lambda d: -1_356_224)
    p = acct._build_balance_payload(_kis(total_eval=99_982_903, unrealized=1_470_411))
    assert p["daily_pnl_total"] == 99_982_903 - 102_260_271  # -2,277,368
    assert p["daily_pnl_pct"] == round(-2_277_368 / 102_260_271 * 100, 2)  # -2.23
    # 보조 분해는 유지
    assert p["today_realized_pnl"] == -1_356_224
    assert p["pnl_total"] == 1_470_411


def test_daily_pnl_zero_without_baseline(monkeypatch):
    import backend.services.engine.daily_capital as dc
    import backend.services.engine.trade_pairs as tp
    monkeypatch.setattr(dc, "get_baseline", lambda d=None: None)  # 장전/비거래일
    monkeypatch.setattr(tp, "get_today_realized_pnl", lambda d: 0)
    p = acct._build_balance_payload(_kis(total_eval=100_000_000))
    assert p["daily_pnl_total"] == 0
    assert p["daily_pnl_pct"] == 0.0
