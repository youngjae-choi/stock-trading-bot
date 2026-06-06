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
