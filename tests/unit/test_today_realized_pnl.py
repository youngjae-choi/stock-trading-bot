"""당일 실현손익 집계 — 단타 청산 손익이 실시간 당일손익에 반영되는지.

버그: Today Control 당일손익·Trading Monitor 평가손익이 미실현(evlu_pfls)만 봐서
청산 완료 시 0이 됐다. get_today_realized_pnl로 청산 실현분을 합산해 통합 표시한다.
"""

import backend.services.engine.trade_pairs as tp
from backend.config import settings
from backend.services import db as db_mod


def _iso_db(tmp_path, monkeypatch):
    p = tmp_path / "realized_pnl.sqlite3"
    monkeypatch.setattr(settings, "APP_DB_PATH", str(p))
    db_mod.initialize_database()
    with db_mod.get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS trading_orders(
              id INTEGER PRIMARY KEY AUTOINCREMENT, trade_date TEXT, signal_id TEXT,
              symbol TEXT, name TEXT, side TEXT, order_type TEXT, qty INTEGER, price REAL,
              kis_order_no TEXT, status TEXT, reason TEXT, created_at TEXT);
            CREATE TABLE IF NOT EXISTS fills(
              id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER, price REAL, quantity REAL);
            """
        )
        conn.commit()


def _order(conn, td, symbol, side, qty, price, no, status="filled"):
    conn.execute(
        "INSERT INTO trading_orders(trade_date,symbol,name,side,order_type,qty,price,kis_order_no,status,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        (td, symbol, "한캠", side, "limit", qty, price, no, status, f"{td}T10:0{no[-1]}:00"),
    )


def test_no_trades_returns_zero(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)
    assert tp.get_today_realized_pnl("2026-06-08") == 0.0


def test_closed_pair_realized_pnl(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)
    td = "2026-06-08"
    with db_mod.get_connection() as conn:
        _order(conn, td, "457370", "buy", 158, 15250, "B1")
        _order(conn, td, "457370", "sell", 158, 15473, "S1")
        conn.commit()
    # (15473 - 15250) * 158 = 35234  (반올림 평균가 기준 trade_pairs와 동일 계산)
    assert tp.get_today_realized_pnl(td) == 35234.0


def test_open_position_excluded(tmp_path, monkeypatch):
    """매수만 있고 매도 없는 보유중 종목은 실현손익에서 제외(pnl_amount=None)."""
    _iso_db(tmp_path, monkeypatch)
    td = "2026-06-08"
    with db_mod.get_connection() as conn:
        _order(conn, td, "005930", "buy", 10, 70000, "B2")
        conn.commit()
    assert tp.get_today_realized_pnl(td) == 0.0
