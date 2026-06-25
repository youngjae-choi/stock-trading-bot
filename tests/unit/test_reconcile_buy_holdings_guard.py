"""EOD orphan BUY 취소 가드 — KIS 실보유 대조 (TASK A1).

orphan 매수가 output1 매칭이 없을 때 무조건 취소하면 실주문 유실 위험이 있다.
취소 전 KIS 잔고를 대조한다:
  · 보유 >= 주문수량 → 체결기록(취소 안 함)
  · 0 < 보유 < 주문수량 → 보류(skipped, kis_holding_partial_hold)
  · 보유 <= 0 → 취소(eod_reconcile_no_kis_fill)
  · KIS 보유조회 실패 → 보류(skipped, kis_holdings_query_failed) — 절대 취소 안 함
동일 종목 orphan 매수 2건은 보유분을 중복으로 크레딧하지 않는다.
"""

import asyncio
import tempfile
import uuid

import pytest


@pytest.fixture()
def db(monkeypatch):
    from backend.config import settings as cfg
    from backend.services.db import initialize_database
    from backend.services.engine.order_executor import _ensure_orders_table
    from backend.services.engine.fill_poller import _ensure_fills_table

    tmp = tempfile.mktemp(suffix=".sqlite3")
    monkeypatch.setattr(cfg, "APP_DB_PATH", tmp)
    initialize_database()
    _ensure_orders_table()
    _ensure_fills_table()
    return tmp


def _insert_buy(symbol, qty=10, price=1000, oid=None, status="submitted"):
    from backend.services.db import get_connection
    oid = oid or str(uuid.uuid4())
    with get_connection() as c:
        c.execute(
            "INSERT INTO trading_orders (id, trade_date, signal_id, symbol, name, side, order_type, qty, price, kis_order_no, status, reason, created_at) "
            "VALUES (?, '2026-06-22', '', ?, ?, 'buy', 'market', ?, ?, '', ?, '', '2026-06-22T10:00:00')",
            (oid, symbol, symbol, qty, price, status),
        )
    return oid


def _status(oid):
    from backend.services.db import get_connection
    with get_connection() as c:
        return c.execute("SELECT status, reason FROM trading_orders WHERE id=?", (oid,)).fetchone()


def _fills_count(oid):
    from backend.services.db import get_connection
    with get_connection() as c:
        return c.execute("SELECT COUNT(*) AS n FROM fills WHERE order_id=?", (oid,)).fetchone()["n"]


def _mock_kis(monkeypatch, *, daily_output1=None, held_map=None, held_raises=False):
    """get_daily_order_inquiry(output1) 와 _kis_held_qty_map 둘 다 mock."""
    import backend.services.kis.domestic.service as dsvc
    import backend.services.engine.order_reconciliation as orc

    async def fake_inquiry(date_str, side="all"):
        return {"output1": daily_output1 or []}
    monkeypatch.setattr(dsvc, "get_daily_order_inquiry", fake_inquiry)

    async def fake_held():
        if held_raises:
            raise RuntimeError("KIS balance down")
        return dict(held_map or {})
    monkeypatch.setattr(orc, "_kis_held_qty_map", fake_held, raising=False)


def test_buy_full_holding_credited_not_cancelled(db, monkeypatch):
    """KIS 보유 >= 주문수량 → 체결기록, 취소 안 함."""
    import backend.services.engine.order_reconciliation as orc
    oid = _insert_buy("368680", qty=10)
    _mock_kis(monkeypatch, daily_output1=[], held_map={"368680": 10})
    r = asyncio.run(orc.reconcile_orders_with_kis("2026-06-22"))
    assert _status(oid)["status"] == "filled"
    assert _fills_count(oid) == 1
    assert len(r["resolved"]) == 1
    assert r["resolved"][0].get("source") == "kis_holdings_guard"
    assert len(r["cancelled"]) == 0


def test_buy_partial_holding_held_not_cancelled(db, monkeypatch):
    """0 < 보유 < 주문수량 → 보류(skipped), 취소도 체결기록도 안 함."""
    import backend.services.engine.order_reconciliation as orc
    oid = _insert_buy("368680", qty=10)
    _mock_kis(monkeypatch, daily_output1=[], held_map={"368680": 4})
    r = asyncio.run(orc.reconcile_orders_with_kis("2026-06-22"))
    row = _status(oid)
    assert row["status"] == "submitted"  # 변경 없음
    assert _fills_count(oid) == 0
    assert any(s.get("reason") == "kis_holding_partial_hold" for s in r["skipped"])
    assert len(r["cancelled"]) == 0


def test_buy_zero_holding_cancelled(db, monkeypatch):
    """보유 <= 0 → 취소(eod_reconcile_no_kis_fill)."""
    import backend.services.engine.order_reconciliation as orc
    oid = _insert_buy("368680", qty=10)
    _mock_kis(monkeypatch, daily_output1=[], held_map={})
    r = asyncio.run(orc.reconcile_orders_with_kis("2026-06-22"))
    row = _status(oid)
    assert row["status"] == "cancelled"
    assert row["reason"] == "eod_reconcile_no_kis_fill"
    assert len(r["cancelled"]) == 1


def test_buy_holdings_query_failed_not_cancelled(db, monkeypatch):
    """KIS 보유조회 실패 → 보류(skipped), 절대 취소 안 함."""
    import backend.services.engine.order_reconciliation as orc
    oid = _insert_buy("368680", qty=10)
    _mock_kis(monkeypatch, daily_output1=[], held_raises=True)
    r = asyncio.run(orc.reconcile_orders_with_kis("2026-06-22"))
    row = _status(oid)
    assert row["status"] == "submitted"  # 변경 없음
    assert _fills_count(oid) == 0
    assert any(s.get("reason") == "kis_holdings_query_failed" for s in r["skipped"])
    assert len(r["cancelled"]) == 0


def test_two_orphan_buys_same_symbol_only_one_credited(db, monkeypatch):
    """동일 종목 orphan 매수 2건 + 보유는 1건분만 → 정확히 1건만 체결, 나머지는 보류."""
    import backend.services.engine.order_reconciliation as orc
    oid1 = _insert_buy("368680", qty=10, oid="aaaa")
    oid2 = _insert_buy("368680", qty=10, oid="bbbb")
    _mock_kis(monkeypatch, daily_output1=[], held_map={"368680": 10})
    r = asyncio.run(orc.reconcile_orders_with_kis("2026-06-22"))
    statuses = sorted([_status(oid1)["status"], _status(oid2)["status"]])
    # 정확히 하나만 filled, 다른 하나는 보유 소진으로 취소(보유 0)
    assert statuses.count("filled") == 1
    assert len(r["resolved"]) == 1
    # 남은 한 건은 remaining_held=0 → 취소
    assert statuses.count("cancelled") == 1


def test_buy_etn_q_prefix_matched(db, monkeypatch):
    """ETN: 주문 심볼 Q520100 / KIS 보유 520100 → norm_symbol 매칭으로 체결기록."""
    import backend.services.engine.order_reconciliation as orc
    oid = _insert_buy("Q520100", qty=5)
    _mock_kis(monkeypatch, daily_output1=[], held_map={"520100": 5})
    r = asyncio.run(orc.reconcile_orders_with_kis("2026-06-22"))
    assert _status(oid)["status"] == "filled"
    assert len(r["resolved"]) == 1
