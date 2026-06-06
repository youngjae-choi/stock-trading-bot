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
