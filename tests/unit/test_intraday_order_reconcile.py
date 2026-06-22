"""장중 주문 정합(reconcile_uncertain_sells_intraday) — 이중매도 방지 우선 (2026-06-22).

주문번호 없는 미확정 매도를 KIS와 대조:
  · KIS에 unaccounted 매도 없음 → 취소(재매도 허용)
  · unaccounted resting(미체결) → 승격(블록 유지, 이중매도 방지)
  · unaccounted 체결 → filled 기록
  · KIS 조회 실패 → 보류
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


def _insert_order(symbol, status, kis_order_no="", qty=594, oid=None):
    from backend.services.db import get_connection
    oid = oid or str(uuid.uuid4())
    with get_connection() as c:
        c.execute(
            "INSERT INTO trading_orders (id, trade_date, signal_id, symbol, name, side, order_type, qty, price, kis_order_no, status, reason, created_at) "
            "VALUES (?, '2026-06-22', '', ?, ?, 'sell', 'market', ?, 0, ?, ?, 'INITIAL_STOP_LOSS:submit_uncertain', '2026-06-22T10:00:00')",
            (oid, symbol, symbol, qty, kis_order_no, status),
        )
    return oid


def _status(oid):
    from backend.services.db import get_connection
    with get_connection() as c:
        return c.execute("SELECT status, kis_order_no FROM trading_orders WHERE id=?", (oid,)).fetchone()


def _mock_kis(monkeypatch, sell_rows, ok=True):
    import backend.services.kis.domestic.service as dsvc

    async def fake(date_str, side="all"):
        if not ok:
            raise RuntimeError("KIS down")
        return {"output1": sell_rows}
    monkeypatch.setattr(dsvc, "get_daily_order_inquiry", fake)


def test_cancel_when_no_kis_order(db, monkeypatch):
    """KIS에 해당 종목 매도가 없으면 제출실패로 취소 → 재매도 허용."""
    import backend.services.engine.order_reconciliation as orc
    oid = _insert_order("368680", "submitted_without_order_no")
    _mock_kis(monkeypatch, [])  # KIS에 매도 없음
    r = asyncio.run(orc.reconcile_uncertain_sells_intraday("2026-06-22"))
    assert _status(oid)["status"] == "cancelled"
    assert len(r["cancelled"]) == 1


def test_promote_when_resting(db, monkeypatch):
    """KIS에 resting(주문번호 있고 미체결) 있으면 승격(블록 유지) — 취소 안 함."""
    import backend.services.engine.order_reconciliation as orc
    oid = _insert_order("368680", "submitted_without_order_no")
    _mock_kis(monkeypatch, [{"pdno": "368680", "odno": "0000099999", "tot_ccld_qty": "0", "tot_ord_qty": "594"}])
    r = asyncio.run(orc.reconcile_uncertain_sells_intraday("2026-06-22"))
    row = _status(oid)
    assert row["status"] == "submitted" and row["kis_order_no"] == "0000099999"
    assert len(r["promoted"]) == 1 and len(r["cancelled"]) == 0


def test_resolve_when_filled(db, monkeypatch):
    """KIS에 체결 있으면 filled 기록."""
    import backend.services.engine.order_reconciliation as orc
    oid = _insert_order("368680", "submitted_without_order_no", qty=594)
    _mock_kis(monkeypatch, [{"pdno": "368680", "odno": "0000099999", "tot_ccld_qty": "594", "tot_ord_qty": "594", "avg_prvs": "8100"}])
    r = asyncio.run(orc.reconcile_uncertain_sells_intraday("2026-06-22"))
    assert _status(oid)["status"] == "filled"
    assert len(r["resolved"]) == 1


def test_double_sell_guard_existing_odno(db, monkeypatch):
    """KIS 매도주문이 이미 다른 로컬 주문(odno 보유)에 매핑됐으면 unaccounted 없음 → 미확정은 취소.

    (살아있는 주문은 그 로컬 주문이 들고 있으므로 미확정 중복분만 취소돼 이중매도 안 남)
    """
    import backend.services.engine.order_reconciliation as orc
    # 살아있는 주문(8bc2, odno 보유, partial)
    _insert_order("368680", "partial", kis_order_no="0000015216", qty=668)
    # 미확정 중복(ef3820, 주문번호 없음)
    oid = _insert_order("368680", "submitted_without_order_no", qty=594)
    # KIS에는 8bc2(0000015216)만 존재 → 이미 매핑됨 → unaccounted 없음
    _mock_kis(monkeypatch, [{"pdno": "368680", "odno": "0000015216", "tot_ccld_qty": "74", "tot_ord_qty": "668"}])
    r = asyncio.run(orc.reconcile_uncertain_sells_intraday("2026-06-22"))
    assert _status(oid)["status"] == "cancelled"
    assert len(r["cancelled"]) == 1


def test_skip_when_kis_query_fails(db, monkeypatch):
    """KIS 조회 실패 시 보류(취소 안 함)."""
    import backend.services.engine.order_reconciliation as orc
    oid = _insert_order("368680", "submitted_without_order_no")
    _mock_kis(monkeypatch, [], ok=False)
    r = asyncio.run(orc.reconcile_uncertain_sells_intraday("2026-06-22"))
    assert _status(oid)["status"] == "submitted_without_order_no"  # 변경 없음
    assert len(r["skipped"]) == 1
