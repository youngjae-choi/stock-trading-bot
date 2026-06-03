from backend.services.engine.order_executor import OrderExecutor


def test_budget_qty_equal_weight():
    ex = OrderExecutor()
    qty = ex._calc_budget_qty(baseline=1_000_000.0, budget_rate=0.9, max_positions=12,
                              price=1_000.0, available_cash=1_000_000.0)
    assert qty == 75


def test_budget_qty_clamps_to_available_cash():
    ex = OrderExecutor()
    qty = ex._calc_budget_qty(baseline=1_000_000.0, budget_rate=0.9, max_positions=12,
                              price=1_000.0, available_cash=30_000.0)
    assert qty == 30


def test_budget_qty_zero_when_no_baseline():
    ex = OrderExecutor()
    qty = ex._calc_budget_qty(baseline=None, budget_rate=0.9, max_positions=12,
                              price=1_000.0, available_cash=1_000_000.0)
    assert qty == 0


def test_budget_qty_guards_bad_inputs():
    ex = OrderExecutor()
    assert ex._calc_budget_qty(1_000_000.0, 0.0, 12, 1_000.0, 1_000_000.0) == 0
    assert ex._calc_budget_qty(1_000_000.0, 0.9, 0, 1_000.0, 1_000_000.0) == 0
    assert ex._calc_budget_qty(1_000_000.0, 0.9, 12, 0.0, 1_000_000.0) == 0
