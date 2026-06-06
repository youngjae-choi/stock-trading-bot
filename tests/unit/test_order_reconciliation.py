import backend.services.engine.order_reconciliation as orc


def test_match_finds_kis_fill_by_symbol_and_qty():
    kis_rows = [
        {"pdno": "005380", "odno": "0000099999", "tot_ccld_qty": "17"},
        {"pdno": "000660", "odno": "0000088888", "tot_ccld_qty": "5"},
    ]
    m = orc._match_orphan_to_kis_fills({"symbol": "005380", "qty": 17}, kis_rows)
    assert m is not None
    assert m["odno"] == "0000099999"


def test_match_returns_none_when_no_symbol():
    kis_rows = [{"pdno": "000660", "odno": "0000088888", "tot_ccld_qty": "5"}]
    assert orc._match_orphan_to_kis_fills({"symbol": "005380", "qty": 17}, kis_rows) is None


def test_match_returns_none_when_zero_filled_qty():
    kis_rows = [{"pdno": "005380", "odno": "0000099999", "tot_ccld_qty": "0"}]
    assert orc._match_orphan_to_kis_fills({"symbol": "005380", "qty": 17}, kis_rows) is None


def test_match_prefers_qty_match_when_multiple_same_symbol():
    kis_rows = [
        {"pdno": "005380", "odno": "A", "tot_ccld_qty": "3"},
        {"pdno": "005380", "odno": "B", "tot_ccld_qty": "17"},
    ]
    m = orc._match_orphan_to_kis_fills({"symbol": "005380", "qty": 17}, kis_rows)
    assert m["odno"] == "B"


def test_query_failure_skips_not_cancels(monkeypatch):
    """KIS 조회가 실패하면 orphan을 취소하지 말고 보류해야 한다(실주문 유실 방지)."""
    import asyncio
    orphan = {"id": "o1", "symbol": "005380", "side": "buy", "qty": 17}
    monkeypatch.setattr(orc, "_load_orphan_orders", lambda _d: [orphan])
    cancelled = []
    monkeypatch.setattr(orc, "_set_order_cancelled", lambda oid, reason: cancelled.append(oid))

    async def boom(*a, **k):
        raise RuntimeError("token issuance failed")

    import backend.services.kis.domestic.service as svc
    monkeypatch.setattr(svc, "get_daily_order_inquiry", boom)

    r = asyncio.run(orc.reconcile_orders_with_kis("2026-06-05"))
    assert cancelled == []                # 취소 안 함
    assert r["cancelled"] == []
    assert len(r["skipped"]) == 1         # 보류
    assert r["skipped"][0]["reason"] == "kis_query_failed"
