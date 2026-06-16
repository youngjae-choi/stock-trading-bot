"""EOD 청산 폴백 안전장치 — KIS 잔고조회 실패 시 auto_imported(유령 가능) 미매도.

회귀 방지(2026-06-16): 잔고조회 실패 → DB 포지션 맹목 시장가 매도 → 거부 폭주·CRITICAL.
폴백에서는 auto_imported를 매도 대상에서 제외하고 검증된 봇 포지션만 남겨야 한다.
"""

from backend.services.engine.eod_liquidation import _partition_fallback_positions


def test_fallback_skips_auto_imported():
    positions = [
        {"symbol": "457370", "qty": 979, "auto_imported": True},   # 유령 가능 → 보류
        {"symbol": "005930", "qty": 10, "auto_imported": False},   # 봇 포지션 → 매도
        {"symbol": "000660", "qty": 5},                            # 플래그 없음 → 매도(봇)
    ]
    sellable, skipped = _partition_fallback_positions(positions)
    assert [p["symbol"] for p in sellable] == ["005930", "000660"]
    assert [p["symbol"] for p in skipped] == ["457370"]


def test_fallback_all_auto_imported_yields_no_sell():
    positions = [
        {"symbol": "A", "qty": 1, "auto_imported": True},
        {"symbol": "B", "qty": 2, "auto_imported": True},
    ]
    sellable, skipped = _partition_fallback_positions(positions)
    assert sellable == []
    assert len(skipped) == 2


def test_fallback_empty():
    assert _partition_fallback_positions([]) == ([], [])
