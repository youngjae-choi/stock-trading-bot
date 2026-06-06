import backend.services.engine.position_integrity as pi


def test_detect_subtracts_reconciled_qty(monkeypatch, tmp_path):
    # net 100, reconciled 100 → 더 이상 잔여로 안 잡힘
    monkeypatch.setattr(pi, "_reconciled_qty_by_symbol", lambda _d: {"321260": 100})
    # _raw_residuals: 실제 집계 결과를 흉내 (symbol 321260 net_qty=100)
    monkeypatch.setattr(pi, "_raw_residual_rows", lambda _d: [
        {"symbol": "321260", "name": "프로이천", "first_trade_date": "2026-05-04",
         "buy_qty": 100, "sell_qty": 0, "net_qty": 100}
    ])
    out = pi.detect_legacy_residual_positions("2026-06-06")
    assert out == []  # 100 - 100 = 0 → 제외


def test_detect_keeps_unreconciled_remainder(monkeypatch):
    monkeypatch.setattr(pi, "_reconciled_qty_by_symbol", lambda _d: {"321260": 30})
    monkeypatch.setattr(pi, "_raw_residual_rows", lambda _d: [
        {"symbol": "321260", "name": "프로이천", "first_trade_date": "2026-05-04",
         "buy_qty": 100, "sell_qty": 0, "net_qty": 100}
    ])
    out = pi.detect_legacy_residual_positions("2026-06-06")
    assert len(out) == 1
    assert out[0]["net_qty"] == 70  # 100 - 30


import backend.services.engine.residual_reconciliation as rr


def test_residual_reconcile_records_phantom(monkeypatch):
    import asyncio
    monkeypatch.setattr(rr, "_detect_residuals", lambda _d: [
        {"symbol": "321260", "name": "프로이천", "net_qty": 100}
    ])
    async def fake_holdings():
        return {"321260": 0}  # KIS 미보유 → 전량 phantom
    monkeypatch.setattr(rr, "_kis_held_qty_map", fake_holdings)
    recorded = []
    monkeypatch.setattr(rr, "_record_reconciliation", lambda **kw: recorded.append(kw))
    r = asyncio.run(rr.reconcile_residual_positions_with_kis("2026-06-06"))
    assert r["reconciled"] == 1
    assert recorded[0]["symbol"] == "321260"
    assert recorded[0]["reconciled_qty"] == 100


def test_residual_reconcile_skips_on_query_failure(monkeypatch):
    import asyncio
    monkeypatch.setattr(rr, "_detect_residuals", lambda _d: [{"symbol": "321260", "net_qty": 100}])
    async def boom():
        raise RuntimeError("kis fail")
    monkeypatch.setattr(rr, "_kis_held_qty_map", boom)
    recorded = []
    monkeypatch.setattr(rr, "_record_reconciliation", lambda **kw: recorded.append(kw))
    r = asyncio.run(rr.reconcile_residual_positions_with_kis("2026-06-06"))
    assert r.get("skipped") is True
    assert recorded == []  # 조회 실패 시 아무것도 기록 안 함
