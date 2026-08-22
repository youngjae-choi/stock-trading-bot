"""탐색모드 제거(2026-08-22, PM 결정) 후 게이트 동작.

is_exploration_allowed는 항상 False(탐색 완전 제거). select_sizing_params는
비탐색 사이징 파라미터(budget_rate=None → daily_capital 사용, 기존 max_positions)를 반환한다.
"""
import backend.services.engine.exploration_gate as eg


def test_exploration_always_disabled():
    assert eg.is_exploration_allowed() is False


def test_sizing_params_returns_none_rate_and_existing_max():
    assert eg.select_sizing_params({"max_positions": 7}) == (None, 7)
    assert eg.select_sizing_params({"max_positions": 5}) == (None, 5)


def test_sizing_params_defaults_max_to_7_when_missing():
    assert eg.select_sizing_params({}) == (None, 7)
