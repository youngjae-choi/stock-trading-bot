"""WS 재구독 시 보유종목 우선 — 상한 절단으로 보유가 미구독되던 버그 (2026-06-11).

배경: refresh_candidates가 구독 목록을 [후보..., 보유...] 순서로 만들고 WS 매니저가
상한(41)에서 뒤를 잘라, 장중 재선별 직후 보유종목이 일시 미구독(손절 틱 공백)되는
현상 발생(13:25~13:31 "74개>41" 경고 3건, PM 목격). 보유를 항상 앞에 두고
상한 내 후보만 덧붙이도록 정렬을 고정한다.
"""

from backend.services.engine.decision_engine import _subscription_symbols


def test_holdings_always_first_and_kept_under_cap():
    held = [f"H{i:02d}" for i in range(12)]
    candidates = [f"C{i:02d}" for i in range(70)]
    out = _subscription_symbols(held, candidates, cap=41)
    assert out[:12] == held              # 보유가 맨 앞
    assert len(out) == 41                # 상한 준수(매니저 절단에 의존하지 않음)
    assert set(held).issubset(set(out))  # 보유는 절대 잘리지 않음


def test_dedup_held_symbol_in_candidates():
    out = _subscription_symbols(["A", "B"], ["B", "C"], cap=41)
    assert out == ["A", "B", "C"]


def test_holdings_over_cap_still_all_included():
    held = [f"H{i:02d}" for i in range(45)]
    out = _subscription_symbols(held, ["C1"], cap=41)
    # 보유가 상한을 넘는 극단 상황 — 보유는 자르지 않는다(구독 실패는 매니저/KIS에서 드러남)
    assert out == held
