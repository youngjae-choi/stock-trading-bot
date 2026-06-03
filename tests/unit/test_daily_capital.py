import asyncio

import backend.services.engine.daily_capital as dc


def test_capture_is_idempotent_and_readable():
    d = "2099-01-02"
    dc._delete_baseline(d)
    assert dc.get_baseline(d) is None
    assert dc.capture_baseline(1_000_000.0, trade_date=d) == 1_000_000.0
    assert dc.capture_baseline(7_777.0, trade_date=d) == 1_000_000.0
    assert dc.get_baseline(d) == 1_000_000.0
    dc._delete_baseline(d)


def test_capture_rejects_nonpositive():
    d = "2099-01-03"
    dc._delete_baseline(d)
    assert dc.capture_baseline(0.0, trade_date=d) is None
    assert dc.capture_baseline(-5.0, trade_date=d) is None
    assert dc.get_baseline(d) is None


def test_active_budget_rate_defaults_to_neutral_when_no_application(monkeypatch):
    monkeypatch.setattr(dc, "get_today_application", lambda _d: None)
    assert dc.get_active_budget_rate("2099-01-04") == 0.8


def test_active_budget_rate_from_applied_settings(monkeypatch):
    monkeypatch.setattr(
        dc, "get_today_application",
        lambda _d: {"applied_settings": {"daily_budget_rate": 0.9, "max_positions": 12}},
    )
    assert dc.get_active_budget_rate("2099-01-05") == 0.9
    assert dc.get_active_max_positions("2099-01-05") == 12


def test_seed_sets_carry_budget_rate():
    from backend.services.db import _default_regime_sets
    sets = {s["id"]: s for s in _default_regime_sets()}
    assert sets["SET-RISK_ON"]["settings"]["daily_budget_rate"] == 0.90
    assert sets["SET-NEUTRAL"]["settings"]["daily_budget_rate"] == 0.80
    assert sets["SET-RISK_OFF"]["settings"]["daily_budget_rate"] == 0.50
    assert sets["SET-VOLATILE"]["settings"]["daily_budget_rate"] == 0.30


def test_cumulative_buy_amount():
    d = "2099-01-06"
    dc._delete_orders_for_test(d)
    dc._insert_order_for_test(d, "005930", "buy", 10, 1000.0, "submitted")
    dc._insert_order_for_test(d, "000660", "buy", 5, 2000.0, "filled")
    dc._insert_order_for_test(d, "005930", "sell", 10, 1000.0, "filled")
    assert dc.get_cumulative_buy_amount(d) == 10 * 1000.0 + 5 * 2000.0
    dc._delete_orders_for_test(d)


def test_capture_job_uses_balance_deposit(monkeypatch):
    import backend.services.scheduler as sched

    d = "2099-01-09"
    dc._delete_baseline(d)

    async def fake_balance():
        return {"output2": [{"ord_psbl_cash": "1234567"}]}

    monkeypatch.setattr(sched, "get_balance", fake_balance, raising=False)
    monkeypatch.setattr(sched, "_today_kst", lambda: d, raising=False)
    asyncio.run(sched.job_capture_capital_baseline())
    assert dc.get_baseline(d) == 1234567.0
    dc._delete_baseline(d)
