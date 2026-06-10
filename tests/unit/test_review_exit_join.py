"""S10 복기 — 시그널↔매도주문 exit 조인 (2026-06-10 버그 수정).

배경: trading_signals에 exit_reason 컬럼이 없어 체결 시그널 전부가 'executed_no_exit'로
분류됐다(실제로는 TRAILING_STOP/INITIAL_STOP_LOSS/DAILY_FORCE_EXIT 청산). 그 결과
trailing_quality=0, EV 가지치기 표본 0 — 학습 루프 입력이 비어 있었다.
수정: trading_orders(side='sell')의 reason을 심볼별로 조인해 exit 버킷을 채운다.
또한 미체결 EOD 취소(buy 주문 전부 cancelled/failed)된 시그널은 거래/승패에서 제외한다.
"""

from backend.services.engine.review_audit import (
    _fallback_exit_reason,
    _normalize_exit_reason,
    build_exit_reason_map,
)


def test_normalize_exit_reason_maps_known_reasons():
    assert _normalize_exit_reason("TRAILING_STOP") == "trailing_stop"
    assert _normalize_exit_reason("INITIAL_STOP_LOSS") == "initial_stop_loss"
    # 복기 소비자(전략 방향 추천)가 'eod' 키를 참조 — DAILY_FORCE_EXIT는 eod로 정규화
    assert _normalize_exit_reason("DAILY_FORCE_EXIT") == "eod"


def test_fallback_uses_sell_order_reason_via_exit_map():
    signal = {"symbol": "476260", "status": "executed"}
    exit_map = {"476260": "initial_stop_loss"}
    assert _fallback_exit_reason(signal, exit_map) == "initial_stop_loss"


def test_fallback_without_exit_map_keeps_legacy_bucket():
    signal = {"symbol": "999999", "status": "executed"}
    assert _fallback_exit_reason(signal, {}) == "executed_no_exit"


def test_build_exit_reason_map_from_orders(tmp_path, monkeypatch):
    import sqlite3
    import backend.services.engine.review_audit as ra

    db = tmp_path / "t.sqlite3"
    con = sqlite3.connect(db)
    con.execute(
        """CREATE TABLE trading_orders (
            id TEXT, trade_date TEXT, signal_id TEXT, symbol TEXT, name TEXT,
            side TEXT, order_type TEXT, qty INTEGER, price REAL,
            kis_order_no TEXT, status TEXT, reason TEXT, created_at TEXT)"""
    )
    rows = [
        # 정상 청산 2건 — 마지막 매도의 reason 채택
        ("1", "2026-06-10", "", "476260", "", "sell", "limit", 797, 15187.0, "", "filled", "INITIAL_STOP_LOSS", "t1"),
        ("2", "2026-06-10", "", "114800", "", "sell", "limit", 12149, 1010.0, "", "filled", "DAILY_FORCE_EXIT", "t2"),
        # 취소된 매도는 무시
        ("3", "2026-06-10", "", "043200", "", "sell", "limit", 1, 777.0, "", "cancelled", "TRAILING_STOP", "t3"),
    ]
    con.executemany("INSERT INTO trading_orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()

    class _Conn:
        def __enter__(self):
            self._c = sqlite3.connect(db)
            self._c.row_factory = sqlite3.Row
            return self._c
        def __exit__(self, *a):
            self._c.close()

    monkeypatch.setattr(ra, "get_connection", lambda: _Conn())
    m = build_exit_reason_map("2026-06-10")
    assert m == {"476260": "initial_stop_loss", "114800": "eod"}
