"""account_pnl.compute_account_pnl — 단일 수익 계산 SSOT 검증.

핵심 회귀 방지:
- 모든 % 는 원금(1억) 기준. 현금으로 나누는 버그(+121%) 금지.
- daily_pnl 은 장시작 total_eval baseline 기준. baseline 없으면 None(0 아님).
"""

import backend.services.engine.account_pnl as ap
from backend.services.engine.account_pnl import compute_account_pnl


def _balance(total_eval, stock_eval, purchase, unrealized, cash):
    return {
        "output2": [{
            "tot_evlu_amt": str(total_eval),
            "scts_evlu_amt": str(stock_eval),
            "pchs_amt_smtl_amt": str(purchase),
            "evlu_pfls_smtl_amt": str(unrealized),
            "ord_psbl_cash": str(cash),
        }],
        "output1": [],
    }


def _patch_common(monkeypatch, *, baseline=None):
    monkeypatch.setattr(ap, "_principal", lambda: 100000000)
    import backend.services.engine.daily_capital as dc
    monkeypatch.setattr(dc, "get_total_eval_baseline", lambda d=None: baseline)
    import backend.services.engine.trade_pairs as tp
    monkeypatch.setattr(tp, "get_today_realized_pnl", lambda d: 0)


def test_cumulative_uses_principal_not_cash(monkeypatch):
    _patch_common(monkeypatch)
    r = compute_account_pnl(_balance(108026999, 64991737, 61586057, 3405680, 43035262))
    assert r["cumulative_pnl"] == 8026999
    assert abs(r["cumulative_return_pct"] - 8.03) < 0.01   # ÷1억, ÷현금 아님


def test_realized_equals_cumulative_minus_unrealized(monkeypatch):
    _patch_common(monkeypatch)
    r = compute_account_pnl(_balance(108026999, 64991737, 61586057, 3405680, 43035262))
    assert abs(r["realized_pnl"] - (8026999 - 3405680)) < 2


def test_daily_none_when_no_baseline(monkeypatch):
    _patch_common(monkeypatch, baseline=None)
    r = compute_account_pnl(_balance(115327435, 72292173, 61586057, 10000000, 52032519))
    assert r["daily_pnl"] is None and r["daily_baseline_available"] is False
    assert r["daily_return_pct"] is None
    # 버그 재현 방지: total_eval - 현금 = 63M, /현금 = 121% 가 절대 나오면 안 됨.
    assert r["daily_pnl"] != 63294916
    assert r["cumulative_return_pct"] < 100


def test_daily_uses_total_eval_baseline(monkeypatch):
    _patch_common(monkeypatch, baseline=110000000)
    r = compute_account_pnl(_balance(115327435, 72292173, 61586057, 10000000, 52032519))
    assert r["daily_pnl"] == 115327435 - 110000000   # 5,327,435
    assert r["daily_baseline_available"] is True
    assert abs(r["daily_return_pct"] - round(5327435 / 100000000 * 100, 2)) < 0.001  # ÷1억


def test_cash_falls_back_to_total_minus_stock_when_ord_psbl_zero(monkeypatch):
    _patch_common(monkeypatch)
    r = compute_account_pnl(_balance(115000000, 72000000, 61000000, 5000000, 0))
    assert r["cash"] == 115000000 - 72000000
