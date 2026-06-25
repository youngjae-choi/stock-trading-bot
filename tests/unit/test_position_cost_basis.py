"""원가 보조 원장(position_cost_basis) — 매수 fill 없는 포지션의 원가 단일출처.

배경(A2): KIS 보유 흡수(auto_imported)·정합(reconciled) 포지션은 매수 fill이 DB에 없어
fills 기반 손익이 matched_qty=0으로 거래를 통째로 누락한다. 이 원장이 매수측 원가를
보강해 trade_pairs가 손익·승패를 집계할 수 있게 한다.
"""

import backend.services.engine.position_cost_basis as cb
from backend.config import settings
from backend.services import db as db_mod


def _iso_db(tmp_path, monkeypatch):
    p = tmp_path / "cost_basis.sqlite3"
    monkeypatch.setattr(settings, "APP_DB_PATH", str(p))
    db_mod.initialize_database()


def test_create_and_get(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)
    cb.upsert_cost_basis("457370", 158, 15250.0, "auto_imported", "2026-06-24")
    row = cb.get_cost_basis("457370", "2026-06-24")
    assert row is not None
    assert row["qty"] == 158
    assert row["avg_price"] == 15250.0
    assert row["source"] == "auto_imported"
    assert row["trade_date"] == "2026-06-24"
    assert row["norm_symbol"] == "457370"


def test_idempotent_double_upsert(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)
    cb.upsert_cost_basis("457370", 158, 15250.0, "auto_imported", "2026-06-24")
    cb.upsert_cost_basis("457370", 200, 16000.0, "auto_imported", "2026-06-24")  # 같은 키 → 교체
    with db_mod.get_connection() as conn:
        n = conn.execute("SELECT COUNT(*) c FROM position_cost_basis").fetchone()["c"]
    assert n == 1
    row = cb.get_cost_basis("457370", "2026-06-24")
    assert row["qty"] == 200 and row["avg_price"] == 16000.0


def test_missing_returns_none(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)
    assert cb.get_cost_basis("999999", "2026-06-24") is None


def test_most_recent_on_or_before(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)
    # T-1 흡수 → T 조회 시 T-1 행을 반환(매도일 기준 가장 최근 원가)
    cb.upsert_cost_basis("457370", 158, 15250.0, "auto_imported", "2026-06-23")
    row = cb.get_cost_basis("457370", "2026-06-24")
    assert row is not None and row["trade_date"] == "2026-06-23"
    # 조회일이 흡수일보다 이전이면 None
    assert cb.get_cost_basis("457370", "2026-06-22") is None


def test_etn_q_normalization(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)
    # Q부착형으로 저장, 무Q형으로 조회 — norm_symbol 키로 일치
    cb.upsert_cost_basis("Q520100", 10, 9000.0, "auto_imported", "2026-06-24")
    row = cb.get_cost_basis("520100", "2026-06-24")
    assert row is not None and row["norm_symbol"] == "520100"
    assert row["symbol"] == "Q520100"  # 원본 보존


def test_bulk_map(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)
    cb.upsert_cost_basis("457370", 158, 15250.0, "auto_imported", "2026-06-24")
    cb.upsert_cost_basis("005930", 10, 70000.0, "reconciled", "2026-06-23")
    m = cb.get_cost_basis_map(["457370", "005930", "999999"], "2026-06-24")
    assert set(m.keys()) == {"457370", "005930"}
    assert m["457370"]["qty"] == 158
    assert m["005930"]["source"] == "reconciled"


def test_add_position_auto_imported_writes_cost_basis(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)
    from backend.services.engine.position_manager import PositionManager

    pm = PositionManager()
    pm.add_position("457370", "한캠", 158, 15250.0, {}, auto_imported=True)
    rows = cb.get_cost_basis_map(["457370"], "2999-12-31")
    assert "457370" in rows
    assert rows["457370"]["qty"] == 158
    assert rows["457370"]["avg_price"] == 15250.0
    assert rows["457370"]["source"] == "auto_imported"


def test_add_position_non_auto_imported_writes_nothing(tmp_path, monkeypatch):
    _iso_db(tmp_path, monkeypatch)
    from backend.services.engine.position_manager import PositionManager

    pm = PositionManager()
    pm.add_position("005930", "삼성전자", 10, 70000.0, {}, auto_imported=False)
    cb.ensure_table()  # 일반 진입은 테이블 자체를 만들지 않으므로 조회용으로 보장
    with db_mod.get_connection() as conn:
        n = conn.execute("SELECT COUNT(*) c FROM position_cost_basis").fetchone()["c"]
    assert n == 0


def test_residual_reconcile_records_cost_basis(tmp_path, monkeypatch):
    """KIS 실보유 확인된 잔여(kis_qty>0)는 source='reconciled'로 원가 기록."""
    import asyncio

    import backend.services.engine.residual_reconciliation as rr

    _iso_db(tmp_path, monkeypatch)
    monkeypatch.setattr(rr, "_detect_residuals", lambda _d: [
        {"symbol": "321260", "name": "프로이천", "net_qty": 100}
    ])

    async def held():
        return {"321260": 100}  # 전량 실보유 → phantom 0, reconciled 원가 기록 대상

    async def avg():
        return {"321260": 5000.0}

    monkeypatch.setattr(rr, "_kis_held_qty_map", held)
    monkeypatch.setattr(rr, "_kis_held_avg_map", avg)
    asyncio.run(rr.reconcile_residual_positions_with_kis("2026-06-24"))

    row = cb.get_cost_basis("321260", "2026-06-24")
    assert row is not None
    assert row["qty"] == 100 and row["avg_price"] == 5000.0
    assert row["source"] == "reconciled"
