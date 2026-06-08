from backend.services.engine.order_executor import OrderExecutor


def test_calc_profile_qty_uses_profile_rate():
    ex = OrderExecutor.__new__(OrderExecutor)
    # total_eval 1억, HIGH_VOL 8% → 목표 800만, 가용 충분, price 1만 → 800주
    assert ex._calc_profile_qty(100_000_000, 0.08, 50_000_000, 10_000) == 800


def test_calc_profile_qty_capped_by_deployable():
    ex = OrderExecutor.__new__(OrderExecutor)
    # 목표 800만이나 가용 300만 → 300주
    assert ex._calc_profile_qty(100_000_000, 0.08, 3_000_000, 10_000) == 300


def test_calc_profile_qty_zero_when_no_room():
    ex = OrderExecutor.__new__(OrderExecutor)
    assert ex._calc_profile_qty(100_000_000, 0.08, 0, 10_000) == 0
    assert ex._calc_profile_qty(100_000_000, 0.0, 5_000_000, 10_000) == 0
