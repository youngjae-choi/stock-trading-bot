"""Phase B — FillPoller hardening (드리프트 예방, 2026-06-24).

B3: 주문 filled인데 fills 기록 실패/스킵 → CRITICAL + 운영 알림(fail-loud).
B2: output2 체결필드(tot_ccld_qty) N회 연속 부재 → 1회 WARNING 알림, 해소 시 리셋.
B2: 체결가 0원(qty>0) → 지정가 폴백, 둘 다 0이면 기록은 하되 CRITICAL + 알림.
B1: fills.symbol을 원주문 심볼(원본 유지)로 저장.

모든 KIS 호출과 알림 함수는 mock, DB는 tmp 파일을 monkeypatch한다(prod DB 미접촉).
"""

from __future__ import annotations

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


@pytest.fixture(autouse=True)
def _reset_module_state():
    """모듈 전역 추적 dict/set을 테스트 간 격리한다."""
    from backend.services.engine import fill_poller as fp

    fp._CCLD_FIELD_MISSING.clear()
    fp._CCLD_MISSING_ALERTED.clear()
    fp._PARTIAL_PROGRESS.clear()
    fp._REMAINDER_REORDERED.clear()
    yield
    fp._CCLD_FIELD_MISSING.clear()
    fp._CCLD_MISSING_ALERTED.clear()
    fp._PARTIAL_PROGRESS.clear()
    fp._REMAINDER_REORDERED.clear()


def _today():
    from backend.services.engine.fill_poller import _now_kst

    return _now_kst().strftime("%Y-%m-%d")


def _insert_order(symbol, side="buy", qty=10, price=1000.0, status="submitted",
                  kis_order_no="ODNO1", oid=None):
    from backend.services.db import get_connection
    from backend.services.engine.fill_poller import _now_kst

    oid = oid or str(uuid.uuid4())
    # created_at은 8h 컷오프 안에 들도록 현재 시각, trade_date는 오늘로.
    now = _now_kst().isoformat()
    with get_connection() as c:
        c.execute(
            "INSERT INTO trading_orders "
            "(id, trade_date, signal_id, symbol, name, side, order_type, qty, price, "
            " kis_order_no, status, reason, created_at) "
            "VALUES (?, ?, '', ?, ?, ?, 'limit', ?, ?, ?, ?, '', ?)",
            (oid, _today(), symbol, symbol, side, qty, price, kis_order_no, status, now),
        )
    return oid


def _fill_rows(order_id):
    from backend.services.db import get_connection

    with get_connection() as c:
        return c.execute(
            "SELECT symbol, quantity, price FROM fills WHERE order_id = ?", (order_id,)
        ).fetchall()


def _capture_alerts(monkeypatch):
    """_send_ops_alert를 가로채 호출 인자를 수집한다."""
    from backend.services.engine import fill_poller as fp

    calls = []
    monkeypatch.setattr(fp, "_send_ops_alert", lambda title, body: calls.append((title, body)))
    return calls


# ── B3 ───────────────────────────────────────────────────────────────────


def test_b3_normal_fill_records_no_alert(db, monkeypatch, caplog):
    """정상 체결: fills 행 1건, CRITICAL/알림 없음."""
    from backend.services.engine import fill_poller as fp

    alerts = _capture_alerts(monkeypatch)
    oid = _insert_order("005930", side="buy", qty=10, price=1000.0)
    kis = {"tot_ccld_qty": "10", "avg_prvs": "1000", "sll_buy_dvsn_cd": "02", "odno": "ODNO1", "pdno": "005930"}

    with caplog.at_level("CRITICAL"):
        fp._mark_order_filled(_get_order(oid), kis)

    rows = _fill_rows(oid)
    assert len(rows) == 1
    assert rows[0][1] == 10
    assert alerts == []
    assert "CRIT" not in caplog.text


def test_b3_filled_but_fill_skipped_alerts(db, monkeypatch, caplog):
    """주문은 filled인데 delta<=0이고 기존 fills도 없으면 CRITICAL + 알림."""
    from backend.services.engine import fill_poller as fp

    alerts = _capture_alerts(monkeypatch)
    oid = _insert_order("005930", side="buy", qty=10, price=1000.0)
    # tot_ccld_qty=0 → qty=0이 아니라 order.qty로 폴백되지 않도록 명시적으로 0 처리.
    # delta<=0 경로를 타려면 qty>0인데 recorded_before>=qty여야 한다.
    # 이미 동일 수량 fill을 미리 넣어 delta<=0 + recorded_before>0 (정상 재관측)로 만든 뒤,
    # 여기서는 recorded_before<=0 + qty>0 케이스를 위해 ccld_qty를 0으로 만든다.
    # qty>0이면서 delta<=0이고 recorded_before<=0인 상황: ccld가 0이면 qty가 order.qty로 폴백됨.
    # 따라서 fills INSERT가 무시되는 시나리오를 직접 시뮬레이션: get_connection을 패치해
    # fills INSERT가 rowcount=0이 되도록 한다.
    kis = {"tot_ccld_qty": "10", "avg_prvs": "1000", "sll_buy_dvsn_cd": "02", "odno": "ODNO1", "pdno": "005930"}

    # fills 테이블에 동일 PK가 항상 충돌하도록? 대신 INSERT OR IGNORE가 스킵되도록
    # _recorded_fill_qty를 패치해 INSERT 후에도 증가하지 않은 것처럼 보이게 한다.
    monkeypatch.setattr(fp, "_recorded_fill_qty", lambda order_id: 0)

    with caplog.at_level("CRITICAL"):
        fp._mark_order_filled(_get_order(oid), kis)

    # recorded_after도 0으로 패치되어 있으므로 기록 실패로 판정 → CRITICAL + 알림
    assert any("CRIT" in r.message for r in caplog.records if r.levelname == "CRITICAL")
    assert len(alerts) == 1
    assert "체결기록 실패" in alerts[0][0]


def test_b3_partial_reobservation_no_alert(db, monkeypatch):
    """이미 전량 기록된 주문을 다시 filled 처리(delta<=0, recorded_before>0)면 정상 → 알림 없음."""
    from backend.services.engine import fill_poller as fp

    alerts = _capture_alerts(monkeypatch)
    oid = _insert_order("005930", side="buy", qty=10, price=1000.0)
    kis = {"tot_ccld_qty": "10", "avg_prvs": "1000", "sll_buy_dvsn_cd": "02", "odno": "ODNO1", "pdno": "005930"}

    # 1차: 정상 기록 (recorded_before=0, delta=10)
    fp._mark_order_filled(_get_order(oid), kis)
    assert len(_fill_rows(oid)) == 1

    # 2차 재관측: recorded_before=10, qty=10 → delta=0. recorded_before>0이므로 정상, 알림 없음.
    fp._mark_order_filled(_get_order(oid), kis)
    assert alerts == []
    assert len(_fill_rows(oid)) == 1  # 중복 기록 없음


# ── B2: ccld 필드 반복 부재 ────────────────────────────────────────────────


def _mock_kis_empty_output1(monkeypatch):
    from backend.services.engine import fill_poller as fp

    async def fake(date_str, side="all"):
        return {"output1": []}  # 항상 미매칭 → output2 폴백

    # poll_once는 모듈 최상단 import(fp.get_daily_order_inquiry)를 호출하므로 fp에 패치
    monkeypatch.setattr(fp, "get_daily_order_inquiry", fake)


def test_b2_ccld_field_missing_alerts_after_threshold(db, monkeypatch):
    """output2 체결필드 N회 연속 부재 → 임계 도달 시 1회만 알림, 해소 시 리셋."""
    from backend.services.engine import fill_poller as fp

    alerts = _capture_alerts(monkeypatch)
    oid = _insert_order("Q520100", side="buy", qty=5, price=2000.0, kis_order_no="ODNO9")

    _mock_kis_empty_output1(monkeypatch)

    # output2가 체결필드 없는 dict를 반환 (keys는 있지만 tot_ccld_qty 부재)
    async def fake_out2(symbol, date_str, order_no):
        return {"odno": order_no, "prdt_name": "ETN"}

    monkeypatch.setattr(fp, "_fetch_symbol_output2", fake_out2)

    # 3회 미만: 알림 없음
    for _ in range(fp._CCLD_MISSING_THRESHOLD - 1):
        asyncio.run(fp.poll_once(_today()))
    assert alerts == []
    assert fp._CCLD_FIELD_MISSING.get(oid) == fp._CCLD_MISSING_THRESHOLD - 1

    # 임계 도달: 알림 1회
    asyncio.run(fp.poll_once(_today()))
    assert len(alerts) == 1
    assert "반복 부재" in alerts[0][0]

    # 다시 부재해도 중복 알림 없음
    asyncio.run(fp.poll_once(_today()))
    assert len(alerts) == 1

    # 해소: output2가 체결수량을 주면 카운터/알림 상태 리셋
    async def fake_out2_filled(symbol, date_str, order_no):
        return {"odno": order_no, "tot_ccld_qty": "5", "tot_ord_qty": "5", "pchs_avg_pric": "2000"}

    monkeypatch.setattr(fp, "_fetch_symbol_output2", fake_out2_filled)
    asyncio.run(fp.poll_once(_today()))
    assert oid not in fp._CCLD_FIELD_MISSING
    assert oid not in fp._CCLD_MISSING_ALERTED


# ── B2: 가격 0 가드 ────────────────────────────────────────────────────────


def test_b2_zero_price_falls_back_to_order_price(db, monkeypatch, caplog):
    """체결가 0 & qty>0 → 주문 지정가로 폴백, CRITICAL 0원 알림 없음."""
    from backend.services.engine import fill_poller as fp

    alerts = _capture_alerts(monkeypatch)
    oid = _insert_order("Q520100", side="buy", qty=5, price=2000.0)
    # KIS 체결가 0, 주문 지정가 2000 → 폴백
    kis = {"tot_ccld_qty": "5", "avg_prvs": "0", "sll_buy_dvsn_cd": "02", "odno": "ODNO1", "pdno": "520100"}

    with caplog.at_level("WARNING"):
        fp._mark_order_filled(_get_order(oid), kis)

    rows = _fill_rows(oid)
    assert len(rows) == 1
    assert rows[0][2] == 2000.0  # 지정가 폴백
    assert "체결가 0" in caplog.text  # WARNING 폴백 로그
    # 0원 CRITICAL 알림은 없음 (폴백 성공)
    assert all("0원" not in t for t, _ in alerts)


def test_b2_zero_price_both_zero_records_and_alerts(db, monkeypatch, caplog):
    """체결가/지정가 모두 0 & qty>0 → 기록은 하되 CRITICAL + 알림."""
    from backend.services.engine import fill_poller as fp

    alerts = _capture_alerts(monkeypatch)
    oid = _insert_order("Q520100", side="buy", qty=5, price=0.0)
    kis = {"tot_ccld_qty": "5", "avg_prvs": "0", "sll_buy_dvsn_cd": "02", "odno": "ODNO1", "pdno": "520100"}

    with caplog.at_level("CRITICAL"):
        fp._mark_order_filled(_get_order(oid), kis)

    rows = _fill_rows(oid)
    assert len(rows) == 1  # 기록은 유지 (영구 submitted 방지)
    assert rows[0][2] == 0.0
    assert any("0원" in t for t, _ in alerts)
    assert "0원" in caplog.text


# ── B1: 심볼 일관성 ────────────────────────────────────────────────────────


def test_b1_fill_symbol_uses_order_symbol(db, monkeypatch):
    """fills.symbol은 KIS pdno(무Q) 대신 원주문 심볼(Q형)을 저장한다."""
    from backend.services.engine import fill_poller as fp

    _capture_alerts(monkeypatch)
    oid = _insert_order("Q520100", side="buy", qty=5, price=2000.0)
    # KIS pdno는 무Q형(520100)으로 옴
    kis = {"tot_ccld_qty": "5", "avg_prvs": "2000", "sll_buy_dvsn_cd": "02", "odno": "ODNO1", "pdno": "520100"}

    fp._mark_order_filled(_get_order(oid), kis)

    rows = _fill_rows(oid)
    assert len(rows) == 1
    assert rows[0][0] == "Q520100"  # 원주문 심볼 유지


# ── helpers ───────────────────────────────────────────────────────────────


def _get_order(oid):
    from backend.services.db import get_connection

    with get_connection() as c:
        row = c.execute("SELECT * FROM trading_orders WHERE id = ?", (oid,)).fetchone()
    return dict(row)
