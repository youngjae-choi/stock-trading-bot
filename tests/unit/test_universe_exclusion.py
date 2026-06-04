from backend.services.engine.universe_filter import _is_excluded_product


def test_excludes_preferred_shares():
    assert _is_excluded_product("005935", "삼성전자우") is True
    assert _is_excluded_product("00088K", "진흥기업2우B") is True
    assert _is_excluded_product("014285", "금강공업우") is True
    assert _is_excluded_product("090355", "노루페인트우") is True


def test_excludes_spac():
    assert _is_excluded_product("474930", "신한제13호스팩") is True
    assert _is_excluded_product("123456", "교보14호스팩") is True


def test_keeps_common_stocks():
    assert _is_excluded_product("005930", "삼성전자") is False
    assert _is_excluded_product("000660", "SK하이닉스") is False
    assert _is_excluded_product("005380", "현대차") is False
    # '우'로 끝나지 않는 정상 종목 보호 (오탐 방지)
    assert _is_excluded_product("004990", "롯데지주") is False
