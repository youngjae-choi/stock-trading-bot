"""당일 매매성적 SSOT(compute_daily_score) — 카드 간 정합의 단일 출처."""

from backend.services.engine.trade_pairs import compute_daily_score


def _pair(symbol, trade_date, status, pnl_pct, pnl_amount=0, orders=None, name=None, exit_reason=None):
    return {
        "symbol": symbol, "trade_date": trade_date, "status": status,
        "pnl_pct": pnl_pct, "pnl_amount": pnl_amount, "orders": orders or [],
        "name": name or symbol, "exit_reason": exit_reason,
    }


def test_rep_date_basis_only_today():
    pairs = [
        _pair("A", "2026-06-16", "매도완료", 1.0, 100),    # 승
        _pair("B", "2026-06-16", "매도완료", -2.0, -200),  # 패
        _pair("C", "2026-06-16", "매도완료", -0.5, -50),   # 패
        _pair("D", "2026-06-15", "매도완료", -9.0, -900),  # 전일 종료 → 제외
        _pair("E", "2026-06-16", "매수완료", None, 0),     # 미청산(오늘 매수)
    ]
    s = compute_daily_score("2026-06-16", pairs=pairs)
    assert s["completed"] == 3
    assert s["wins"] == 1 and s["losses"] == 2
    assert s["open_positions"] == 1
    assert s["win_rate"] == round(1 / 3 * 100, 1)
    assert "realized_pnl" not in s  # 돈은 계좌 SSOT(equity_pnl) 전담 — 카운트 전용


def test_losses_match_false_positive_definition():
    # 손실패턴(false_positive)=pnl<0 건수 → SSOT losses와 동일해야 정합
    pairs = [_pair(s, "2026-06-16", "매도완료", p, int(p * 100)) for s, p in
             [("A", -2.53), ("B", -0.62), ("C", -1.66), ("D", -0.58), ("W", 3.2)]]
    s = compute_daily_score("2026-06-16", pairs=pairs)
    assert s["losses"] == 4 and s["wins"] == 1 and s["completed"] == 5


def test_losers_list_matches_losses():
    # SSOT losers 리스트 = 완료·pnl<0 페어, 손실패턴 카드의 단일 출처
    pairs = [
        _pair("A", "2026-06-16", "매도완료", 1.0, 100),               # 승
        _pair("B", "2026-06-16", "매도완료", -2.0, -200, name="베타", exit_reason="stop"),  # 패
        _pair("C", "2026-06-16", "매도완료", -0.5, -50),              # 패
        _pair("D", "2026-06-15", "매도완료", -9.0, -900),             # 전일 → 제외
    ]
    s = compute_daily_score("2026-06-16", pairs=pairs)
    assert len(s["losers"]) == s["losses"] == 2
    syms = {x["symbol"] for x in s["losers"]}
    assert syms == {"B", "C"}
    b = next(x for x in s["losers"] if x["symbol"] == "B")
    assert b["name"] == "베타" and b["pnl_pct"] == -2.0 and b["exit_reason"] == "stop"


def test_fill_counts_exclude_unfilled():
    pairs = [_pair("A", "2026-06-16", "매도완료", 1.0, 10, orders=[
        {"side": "buy", "fill_qty": 10}, {"side": "sell", "fill_qty": 10},
        {"side": "sell", "fill_qty": None},  # 취소·미체결 재시도 → 제외
    ])]
    s = compute_daily_score("2026-06-16", pairs=pairs)
    assert s["buy_fills"] == 1 and s["sell_fills"] == 1


def test_empty_day():
    s = compute_daily_score("2026-06-16", pairs=[])
    assert s["completed"] == 0 and s["win_rate"] == 0.0 and s["symbols"] == 0
