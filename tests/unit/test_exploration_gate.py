from unittest.mock import patch

import backend.services.engine.exploration_gate as eg


def test_allowed_when_setting_on_and_virtual():
    with patch.object(eg, "get_setting", return_value=True), \
         patch.object(eg, "_is_virtual", return_value=True):
        assert eg.is_exploration_allowed() is True


def test_blocked_when_setting_on_but_real_account():
    # 실계좌면 설정이 켜져 있어도 하드 차단
    with patch.object(eg, "get_setting", return_value=True), \
         patch.object(eg, "_is_virtual", return_value=False):
        assert eg.is_exploration_allowed() is False


def test_blocked_when_setting_off_even_if_virtual():
    with patch.object(eg, "get_setting", return_value=False), \
         patch.object(eg, "_is_virtual", return_value=True):
        assert eg.is_exploration_allowed() is False


def test_blocked_when_both_off():
    with patch.object(eg, "get_setting", return_value=False), \
         patch.object(eg, "_is_virtual", return_value=False):
        assert eg.is_exploration_allowed() is False


def test_setting_string_truthy_is_coerced():
    # system_settings JSON 이 "true"/"1" 문자열로 와도 켜진 것으로 본다
    with patch.object(eg, "_is_virtual", return_value=True):
        with patch.object(eg, "get_setting", return_value="true"):
            assert eg.is_exploration_allowed() is True
        with patch.object(eg, "get_setting", return_value="0"):
            assert eg.is_exploration_allowed() is False


def test_sizing_params_always_non_exploration_even_when_allowed():
    # 탐색 분기는 dead code로 제거됨: 유일한 호출부(order_executor)가 비탐색 else에서만
    # 호출하므로, 탐색이 허용된 상태여도 항상 (None, 기존 max_positions) 를 반환한다.
    def _fake_setting(key, default=None):
        return {
            "engine.exploration_mode": True,
            "exploration.budget_rate": 0.95,
            "exploration.max_positions": 40,
        }.get(key, default)

    with patch.object(eg, "_is_virtual", return_value=True), \
         patch.object(eg, "get_setting", side_effect=_fake_setting):
        budget_rate, max_positions = eg.select_sizing_params({"max_positions": 7})
    assert budget_rate is None
    assert max_positions == 7


def test_sizing_params_non_exploration_keeps_existing_max_and_none_rate():
    with patch.object(eg, "_is_virtual", return_value=False), \
         patch.object(eg, "get_setting", return_value=True):
        budget_rate, max_positions = eg.select_sizing_params({"max_positions": 5})
    assert budget_rate is None
    assert max_positions == 5


def test_sizing_params_non_exploration_defaults_max_to_7_when_missing():
    with patch.object(eg, "_is_virtual", return_value=False), \
         patch.object(eg, "get_setting", return_value=True):
        budget_rate, max_positions = eg.select_sizing_params({})
    assert budget_rate is None
    assert max_positions == 7
