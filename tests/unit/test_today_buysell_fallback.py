"""당일 매수/매도금액 — KIS 요약(thdt_*) 결손 시 체결원장(trading_orders) 폴백.

KIS 모의계좌가 thdt_buy_amt/thdt_sll_amt를 0/빈값으로 반환해 화면이 '당일 매수 0원'으로
오표시되던 문제. 우리 체결원장에 실제 거래가 있으면 그 금액으로 폴백한다.
"""

import backend.api.routes.account as acct
from backend.api.routes.account import _build_balance_payload

_BASE_SUMMARY = {
    "tot_evlu_amt": "88000000", "ord_psbl_cash": "79000000",
    "scts_evlu_amt": "8000000", "pchs_amt_smtl_amt": "0", "evlu_pfls_smtl_amt": "0",
}


def _data(summary_extra):
    s = dict(_BASE_SUMMARY)
    s.update(summary_extra)
    return {"output1": [], "output2": [s]}


def test_falls_back_to_ledger_when_kis_zero(monkeypatch):
    """KIS thdt_buy_amt=0 이면 체결원장 금액(64,501,240)으로 폴백."""
    monkeypatch.setattr(
        acct, "_today_filled_amount",
        lambda td, side: 64_501_240 if side == "buy" else 66_233_517,
    )
    p = _build_balance_payload(_data({"thdt_buy_amt": "0", "thdt_sll_amt": "0"}))
    assert p["today_buy_amt"] == 64_501_240
    assert p["today_sell_amt"] == 66_233_517


def test_falls_back_when_kis_field_missing(monkeypatch):
    """KIS thdt_* 필드 자체가 없어도(빈값→None) 폴백."""
    monkeypatch.setattr(acct, "_today_filled_amount", lambda td, side: 12_345 if side == "buy" else 0)
    p = _build_balance_payload(_data({}))  # thdt_* 없음
    assert p["today_buy_amt"] == 12_345
    assert p["today_sell_amt"] == 0


def test_kis_value_wins_when_present(monkeypatch):
    """KIS가 정상 값(비0)을 주면 폴백하지 않고 KIS 값을 쓴다(계좌 권위)."""
    called = {"n": 0}

    def _fallback(td, side):
        called["n"] += 1
        return 999

    monkeypatch.setattr(acct, "_today_filled_amount", _fallback)
    p = _build_balance_payload(_data({"thdt_buy_amt": "5000000", "thdt_sll_amt": "3000000"}))
    assert p["today_buy_amt"] == 5_000_000
    assert p["today_sell_amt"] == 3_000_000
    assert called["n"] == 0  # 폴백 미호출
