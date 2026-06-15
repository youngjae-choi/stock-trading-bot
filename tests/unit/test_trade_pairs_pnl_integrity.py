"""trade_pairs 손익 정합 — 0원 미체결 주문 오염 차단 + 완전체결 수량 정합.

회귀 방지(2026-06-15 6/15 검증에서 발견):
- 버그 A: price=0인 미체결 매도주문이 _wavg 가중평균에 합산돼 매도단가가 절반으로
  붕괴 → 손실율 -50%대로 박제 (false_positive). 0원 주문은 평균에서 제외해야 한다.
- 버그(수량): status='filled'인데 fills가 부분수량만 기록(예: 주문 1056, fill 1)하면
  matched_qty가 1로 붕괴해 pnl_amount가 과소. 완전체결 주문은 주문수량이 권위.
"""

import backend.services.engine.trade_pairs as tp
from backend.config import settings
from backend.services import db as db_mod


def _iso_db(tmp_path, monkeypatch):
    p = tmp_path / "tp_integrity.sqlite3"
    monkeypatch.setattr(settings, "APP_DB_PATH", str(p))
    db_mod.initialize_database()
    with db_mod.get_connection() as conn:
        # fills는 initialize_database가 만든 TEXT 스키마라 INTEGER order_id 조인이 어긋남 — 테스트용 단순 스키마로 교체
        conn.executescript(
            """
            DROP TABLE IF EXISTS fills;
            CREATE TABLE IF NOT EXISTS trading_orders(
              id INTEGER PRIMARY KEY AUTOINCREMENT, trade_date TEXT, signal_id TEXT,
              symbol TEXT, name TEXT, side TEXT, order_type TEXT, qty INTEGER, price REAL,
              kis_order_no TEXT, status TEXT, reason TEXT, created_at TEXT);
            CREATE TABLE fills(
              id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER, price REAL, quantity REAL);
            """
        )
        conn.commit()


def _order(conn, td, symbol, side, qty, price, no, status="filled", t="10:00:00"):
    cur = conn.execute(
        "INSERT INTO trading_orders(trade_date,symbol,name,side,order_type,qty,price,kis_order_no,status,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        (td, symbol, "테스트ETF", side, "limit", qty, price, no, status, f"{td}T{t}"),
    )
    return cur.lastrowid


def _fill(conn, order_id, price, qty):
    conn.execute(
        "INSERT INTO fills(order_id, price, quantity) VALUES(?,?,?)", (order_id, price, qty)
    )


def test_zero_price_pending_sell_excluded_from_avg(tmp_path, monkeypatch):
    """미체결(price=0) 매도주문이 평균에 섞여 매도단가를 끌어내리면 안 된다."""
    _iso_db(tmp_path, monkeypatch)
    with db_mod.get_connection() as conn:
        _order(conn, "2026-06-12", "395750", "buy", 530, 24895, "B1", t="09:10:00")
        _order(conn, "2026-06-12", "395750", "sell", 530, 24827, "S1", t="15:00:00")
        # 같은 종목에 price=0 미체결 매도주문(아직 cancelled 전) — 평균 오염원
        _order(conn, "2026-06-15", "395750", "sell", 529, 0, "S2", status="submitted", t="09:05:00")
        conn.commit()
    pairs = tp.get_trade_pairs("2026-06-01", "2026-06-15")
    p = next(x for x in pairs if x["symbol"] == "395750")
    # 매도단가는 24827 부근이어야 하고, 손실율은 -1% 이내
    assert p["sell_price"] == 24827
    assert -1.5 < p["pnl_pct"] < 0


def test_filled_order_uses_order_qty_when_fill_underrecords(tmp_path, monkeypatch):
    """status=filled인데 fill 수량이 부분만 기록되면 주문수량을 권위로 삼는다."""
    _iso_db(tmp_path, monkeypatch)
    with db_mod.get_connection() as conn:
        bid = _order(conn, "2026-06-12", "314700", "buy", 1000, 12180, "B1", t="09:10:00")
        sid = _order(conn, "2026-06-12", "314700", "sell", 1000, 12137, "S1", t="15:00:00")
        _fill(conn, bid, 12180, 1)      # fills가 1주만 기록 (부분 기록 버그)
        _fill(conn, sid, 12137, 1000)
        conn.commit()
    pairs = tp.get_trade_pairs("2026-06-01", "2026-06-15")
    p = next(x for x in pairs if x["symbol"] == "314700")
    assert p["buy_qty"] == 1000          # fill 1이 아니라 주문 1000
    # matched=1000 → pnl_amount = (12137-12180)*1000 = -43000
    assert p["pnl_amount"] == -43000
