import backend.services.engine.order_preflight as pf


def test_budget_cap_blocks_when_cumulative_reaches_budget(monkeypatch):
    monkeypatch.setattr(pf, "get_baseline", lambda _d=None: 1_000_000.0)
    monkeypatch.setattr(pf, "get_active_budget_rate", lambda _d=None: 0.5)
    monkeypatch.setattr(pf, "get_cumulative_buy_amount", lambda _d=None: 500_000.0)
    blocked, reason = pf._budget_cap_check(trade_date="2099-01-10")
    assert blocked is True
    assert "예산" in reason


def test_budget_cap_allows_when_under_budget(monkeypatch):
    monkeypatch.setattr(pf, "get_baseline", lambda _d=None: 1_000_000.0)
    monkeypatch.setattr(pf, "get_active_budget_rate", lambda _d=None: 0.5)
    monkeypatch.setattr(pf, "get_cumulative_buy_amount", lambda _d=None: 200_000.0)
    blocked, _ = pf._budget_cap_check(trade_date="2099-01-10")
    assert blocked is False


def test_budget_cap_allows_when_no_baseline(monkeypatch):
    monkeypatch.setattr(pf, "get_baseline", lambda _d=None: None)
    monkeypatch.setattr(pf, "get_active_budget_rate", lambda _d=None: 0.5)
    monkeypatch.setattr(pf, "get_cumulative_buy_amount", lambda _d=None: 999_999.0)
    blocked, _ = pf._budget_cap_check(trade_date="2099-01-10")
    assert blocked is False
