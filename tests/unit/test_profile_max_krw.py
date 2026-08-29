"""프로필별 종목당 최대금액(max_position_krw) 매핑 — 2026-08-29 PM.

사이징 금액모델 위에 프로필 캡을 덧씌워 변동성 프로필(THEME_SPIKE) 블로우업 크기를 줄인다.
resolve_symbol_rule이 프로필 팩의 max_position_krw를 final_rule로 나른다(order_executor가 캡).
"""

from backend.services.engine.rule_resolver import resolve_symbol_rule


def test_profile_max_position_krw_mapped():
    """프로필에 max_position_krw가 있으면 final_rule로 전달된다."""
    pack = {"profiles": {"THEME_SPIKE": {"initial_stop_loss": -0.04, "max_position_krw": 6_000_000}}}
    plan = {"symbol_assignments": [{"code": "999999", "profile": "THEME_SPIKE"}]}
    final = resolve_symbol_rule("999999", {}, pack, plan, {}, {"max_positions": 5}, trade_date="")
    assert final["max_position_krw"] == 6_000_000
    assert final["profile_assigned"] == "THEME_SPIKE"


def test_profile_missing_max_krw_is_none():
    """프로필에 max_position_krw가 없으면 None(캡 없음)."""
    pack = {"profiles": {"LOW_VOL": {"initial_stop_loss": -0.018}}}
    plan = {"symbol_assignments": [{"code": "111111", "profile": "LOW_VOL"}]}
    final = resolve_symbol_rule("111111", {}, pack, plan, {}, {"max_positions": 5}, trade_date="")
    assert final["max_position_krw"] is None


def test_profile_zero_max_krw_is_none():
    """0/음수는 캡 없음(None)으로 정규화."""
    pack = {"profiles": {"MID_VOL": {"max_position_krw": 0}}}
    plan = {"symbol_assignments": [{"code": "222222", "profile": "MID_VOL"}]}
    final = resolve_symbol_rule("222222", {}, pack, plan, {}, {"max_positions": 5}, trade_date="")
    assert final["max_position_krw"] is None


def test_profile_cap_arithmetic():
    """캡 수량 = floor(max_krw / price). THEME_SPIKE 600만·가격 2000 → 3000주."""
    max_krw, price = 6_000_000, 2000.0
    cap = int(max_krw // price)
    assert cap == 3000
