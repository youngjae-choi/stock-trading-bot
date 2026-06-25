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


# ──────────────────────────────────────────────────────────────────────────────
# A2: cost_basis 주입 — 매수 fill 없는 auto_imported 매도가 손익에 포함
# ──────────────────────────────────────────────────────────────────────────────

def test_auto_imported_sell_uses_cost_basis(tmp_path, monkeypatch):
    """매수 주문 없이 매도만 있는 흡수 포지션 — cost_basis로 매수측 보강해 손익 산출."""
    import backend.services.engine.position_cost_basis as cb

    _iso_db(tmp_path, monkeypatch)
    td = "2026-06-08"
    with db_mod.get_connection() as conn:
        _order(conn, td, "457370", "sell", 158, 15473, "S9")
        conn.commit()
    # 전일 흡수 원가 기록(평단 15250, 수량 158)
    cb.upsert_cost_basis("457370", 158, 15250.0, "auto_imported", "2026-06-07")

    pairs = tp.get_trade_pairs(td, td)
    p = next(x for x in pairs if x["symbol"] == "457370")
    assert p["pnl_amount"] == 35234.0  # (15473-15250)*158
    assert p["status"] == "매도완료"
    assert p["cost_basis_source"] == "auto_imported"
    assert p["cost_basis_trade_date"] == "2026-06-07"
    assert tp.get_today_realized_pnl(td) == 35234.0


def test_normal_pair_has_no_cost_basis_fields(tmp_path, monkeypatch):
    """정상 양방향 짝은 cost_basis 영향 없음(source=None)."""
    _iso_db(tmp_path, monkeypatch)
    td = "2026-06-08"
    with db_mod.get_connection() as conn:
        _order(conn, td, "457370", "buy", 158, 15250, "B1")
        _order(conn, td, "457370", "sell", 158, 15473, "S1")
        conn.commit()
    pairs = tp.get_trade_pairs(td, td)
    p = next(x for x in pairs if x["symbol"] == "457370")
    assert p["pnl_amount"] == 35234.0
    assert p["cost_basis_source"] is None
    assert p["cost_basis_trade_date"] is None


def test_sell_only_without_cost_basis_stays_none(tmp_path, monkeypatch):
    """매도만 있고 cost_basis도 없으면 손익 None(기존 동작 불변)."""
    _iso_db(tmp_path, monkeypatch)
    td = "2026-06-08"
    with db_mod.get_connection() as conn:
        _order(conn, td, "457370", "sell", 158, 15473, "S2")
        conn.commit()
    pairs = tp.get_trade_pairs(td, td)
    p = next(x for x in pairs if x["symbol"] == "457370")
    assert p["pnl_amount"] is None
    assert p["cost_basis_source"] is None


# ──────────────────────────────────────────────────────────────────────────────
# A2 Phase 3: daily_summary realized_pnl writer 단일화(trade_pairs 집계)
# ──────────────────────────────────────────────────────────────────────────────

def test_daily_summary_realized_pnl_matches_trade_pairs(tmp_path, monkeypatch):
    """daily_trade_summary.realized_pnl == 그날 완료 페어 pnl_amount 합(흡수 포함)."""
    import asyncio

    import backend.services.engine.position_cost_basis as cb
    import backend.services.engine.daily_summary as ds

    _iso_db(tmp_path, monkeypatch)
    td = "2026-06-08"
    with db_mod.get_connection() as conn:
        _order(conn, td, "457370", "buy", 158, 15250, "B1")
        _order(conn, td, "457370", "sell", 158, 15473, "S1")   # 정상 짝: +35234
        _order(conn, td, "005930", "sell", 10, 71000, "S2")    # 흡수 매도(매수 fill 없음)
        conn.commit()
    cb.upsert_cost_basis("005930", 10, 70000.0, "auto_imported", "2026-06-07")  # +10000

    asyncio.run(ds.run_daily_summary(td))

    pairs_sum = sum(p["pnl_amount"] for p in tp.get_trade_pairs(td, td)
                    if p.get("pnl_amount") is not None and p.get("trade_date") == td)
    with db_mod.get_connection() as conn:
        row = conn.execute(
            "SELECT realized_pnl, pnl_source FROM daily_trade_summary WHERE trade_date=?", (td,)
        ).fetchone()
    assert row is not None
    assert row["realized_pnl"] == pairs_sum == 45234.0
    assert row["pnl_source"] == "fills+cost_basis"


def test_daily_summary_open_position_excluded(tmp_path, monkeypatch):
    """매수만 있고 미청산인 보유 종목은 realized_pnl에서 제외."""
    import asyncio

    import backend.services.engine.daily_summary as ds

    _iso_db(tmp_path, monkeypatch)
    td = "2026-06-08"
    with db_mod.get_connection() as conn:
        _order(conn, td, "457370", "buy", 158, 15250, "B1")
        _order(conn, td, "457370", "sell", 158, 15473, "S1")  # 완료: +35234
        _order(conn, td, "005930", "buy", 10, 70000, "B2")    # 미청산
        conn.commit()

    asyncio.run(ds.run_daily_summary(td))
    with db_mod.get_connection() as conn:
        row = conn.execute(
            "SELECT realized_pnl, pnl_source FROM daily_trade_summary WHERE trade_date=?", (td,)
        ).fetchone()
    assert row["realized_pnl"] == 35234.0
    assert row["pnl_source"] != "fills+cost_basis"  # 흡수 기여 없음
