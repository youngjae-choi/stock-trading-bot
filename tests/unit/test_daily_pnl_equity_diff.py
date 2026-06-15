"""당일 손익 A안 — 자본변화 기준(총평가 - 장시작 total_eval baseline).

SSOT 통합(2026-06-15): 계산은 account_pnl.compute_account_pnl 단일 소스에서 온다.
- baseline 은 장시작 total_eval (예수금 아님).
- % 는 원금(1억) 기준으로 나눈다 (예수금/baseline 으로 나누는 버그 금지).
- baseline 미캡처(장전/비거래일)면 daily_pnl_total/daily_pnl_pct = None (0 아님), daily_pnl_available=False.
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
    import backend.services.engine.account_pnl as ap
    import backend.services.engine.daily_capital as dc
    import backend.services.engine.trade_pairs as tp
    monkeypatch.setattr(ap, "_principal", lambda: 100_000_000)
    monkeypatch.setattr(dc, "get_total_eval_baseline", lambda d=None: 102_260_271.0)
    monkeypatch.setattr(tp, "get_today_realized_pnl", lambda d: -1_356_224)
    p = acct._build_balance_payload(_kis(total_eval=99_982_903, unrealized=1_470_411))
    assert p["daily_pnl_total"] == 99_982_903 - 102_260_271  # -2,277,368
    # % 는 원금(1억) 기준.
    assert p["daily_pnl_pct"] == round(-2_277_368 / 100_000_000 * 100, 2)
    assert p["daily_pnl_available"] is True
    # 보조 분해는 유지
    assert p["today_realized_pnl"] == -1_356_224
    assert p["pnl_total"] == 1_470_411


def test_daily_pnl_none_without_baseline(monkeypatch):
    import backend.services.engine.account_pnl as ap
    import backend.services.engine.daily_capital as dc
    import backend.services.engine.trade_pairs as tp
    monkeypatch.setattr(ap, "_principal", lambda: 100_000_000)
    monkeypatch.setattr(dc, "get_total_eval_baseline", lambda d=None: None)  # 장전/비거래일
    monkeypatch.setattr(tp, "get_today_realized_pnl", lambda d: 0)
    p = acct._build_balance_payload(_kis(total_eval=100_000_000))
    assert p["daily_pnl_total"] is None
    assert p["daily_pnl_pct"] is None
    assert p["daily_pnl_available"] is False
